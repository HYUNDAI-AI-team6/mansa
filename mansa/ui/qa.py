"""기술 Q&A 화면: 질문 전(U1) → 대화(답변 U2 / 되묻기·답변 불가 U3).

관리자 '질문 테스트'도 test_mode=True 로 같은 화면을 다시 쓴다.
"""
import logging # 질문 처리에 실패한 원인을 서버 로그에 남기려고 쓴다

from dataclasses import dataclass, field
from functools import cache, partial
from html import escape

import gradio as gr

from core.schemas import Answer, AnswerSection, Clarify, NoAnswer, SourceView
from features.history.service import HistoryService
from features.history.store import MemoryHistoryStore
from features.master.equipment import EquipmentModelService
from features.qa.answer_guard import build_no_answer
from features.qa.clarify_policy import MODEL_QUESTION
from features.qa.factory import build_qa_service, build_source_service
from features.qa.service import QAService
from features.qa.source_service import SourceService
from ui import components as ui
from ui import icons
from ui import mock_data as mock
from ui.theme import BRAND, TEXT2

SOURCE_KINDS = {"tech": "매뉴얼", "secure": "안전 조항"} # 근거 원문 창 탭 이름
KIND_COLOR = {"매뉴얼": "blue", "안전 조항": "orange"}
QUIET = {"show_progress": "hidden"}  # 로딩은 우리가 그린 '찾는 중' 표시로 보여 준다
THINKING_TEXT = "문서에서 답을 찾고 있어요"
OUTPUT_COUNT = 15  # _render() 가 돌려주는 값 개수 = build() 의 outs 개수
DISCLAIMER = '<p class="disclaimer">참고용 안내이며 법적 판단이 아닙니다.</p>'
# shortcut: 로그인 기능이 없어 모든 질문을 회원 1로 저장한다, features/auth 가 생기면 로그인 계정 ID로 바꾼다.
MEMBER_ID = 1
RULES = [
    ("chat", "모델·부위가 비었거나 후보가 여럿", "실제 등록된 후보로 선택지를 보여 줘요"),
    ("search", "근거 점수가 낮을 때", "찾을 수 없다고 답하고 확인할 부서를 안내해요"),
    ("x", "문서 범위 밖 질문", "일반 지식으로 채우지 않아요"),
    ("refresh", "출처·수치가 원문과 다를 때", "다시 만들고, 계속 틀리면 답변 불가로 바꿔요"),
]


@dataclass
class QAView:
    """기술 Q&A 화면 바깥(app.py)에서 쓰는 부분.

    reset: 메뉴로 들어올 때 질문 전 화면으로 되돌리기.
    open_history: 질문 기록에서 고른 지난 대화를 열기.
    """

    reset_outputs: list = field(default_factory=list)
    reset_inputs: list = field(default_factory=list)
    links: dict = field(default_factory=dict)

    def reset(self) -> tuple:
        """대화를 비우고 모델 선택까지 처음으로 돌린 질문 전 화면 값을 돌려준다."""
        return (*_render(_empty_state()), "")

    def open_history(self, conversation_id: int) -> tuple:
        """질문 기록에서 고른 대화를 저장된 질문·답변 그대로 펼친다. 이어서 질문하면 같은 대화에 저장된다.
        
        앱을 다시 켜 기록이 사라진 대화처럼 찾을 수 없으면 질문 전 화면을 보여 준다.
        """
        try:
            conversation = history_service().get_conversation(MEMBER_ID, conversation_id)
        except LookupError:
            return self.reset()
        turns = [{"q": t.question, "kind": "answer", "answer": t.answer} for t in conversation.turns]
        state = {**_empty_state(), "turns": turns, "conversation_id" :conversation.id}
        return (*_render(state), "")


# ------------------------------------------------------------------ HTML 조각
def task_cards_html() -> str:
    """'자주 찾는 작업' 카드 4개 (시연용 고정 데이터)."""
    cards = "".join(
        '<div class="card task-card">'
        f"{ui.tag(t['place'], 'blue')}<h4>{escape(t['title'])}</h4><p>{escape(t['meta'])}</p>"
        f'<div class="tags">{ui.tag("절차")}{ui.tag("사양")}{ui.tag("안전", "orange")}</div></div>'
        for t in mock.FREQUENT_TASKS
    )
    return f'<div class="task-cards">{cards}</div>'


def recent_changes_html() -> str:
    """'최근 변경사항' 카드 (최근 7일 추가 문서, 이동 없이 목록만)."""
    rows = "".join(
        f'<div class="list-row"><b>{escape(c["title"])}</b><span>{escape(c["meta"])}</span></div>'
        for c in mock.RECENT_CHANGES
    )
    head = '<div class="card-head"><h3>최근 변경사항</h3><span>최근 7일</span></div>'
    return f'<div class="card list-card">{head}{rows}</div>'


def recent_questions_html() -> str:
    """'최근 질문' 카드(3개). 줄을 누르면 그 질문을 다시 보낸다."""
    rows = "".join(
        f'<button type="button" class="list-row click" data-i="{i}"><b>{escape(q["title"])}</b>'
        f"<span>{escape(q['meta'])}</span></button>"
        for i, q in enumerate(mock.RECENT_QUESTIONS)
    )
    return (
        f'<div class="card list-card"><div class="card-head"><h3>최근 질문</h3></div>{rows}</div>'
    )


def _kind(src: SourceView) -> str:
    """근거의 탭 이름(매뉴얼 / 안전 조항). 문서 종류를 모르면 매뉴얼로 본다."""
    return SOURCE_KINDS.get(src.doc_type, "매뉴얼")


def _loc(src: SourceView) -> str:
    """근거 위치 글자: 페이지 · 조항(있는 것만)."""
    page = f"p.{src.page}" if src.page is not None else ""
    return " · ".join(part for part in (page, src.clause) if part)


def source_list_html(sources: list[SourceView] | None) -> str:
    """'근거 목록' 카드. 줄을 누르면 위 '근거 원문' 창에 그 근거를 띄운다. None 이면 불러오기 실패다"""
    if sources is None:
        rows = '<p class="note">근거를 불러오지 못했어요</p>'
    elif not sources:
        rows = '<p class="note">표시할 근거가 없어요</p>'
    else:
        rows = "".join(
            f'<button type="button" class="src-row" data-i="{i}">'
            f"{ui.tag(_kind(s), KIND_COLOR[_kind(s)])}"
            f"<b>{escape(s.doc_name)}</b><span>{escape(_loc(s))}</span></button>"
            for i, s in enumerate(sources)
        )
    return f'<div class="card source-list"><h3>근거 목록</h3>{rows}</div>'


def _source_link(text: str) -> str:
    """파란 출처 링크 한 줄."""
    return f'<div class="src-link">{icons.svg("link", BRAND, 16)}{escape(text)}</div>'


def _section(title: str, dept_tag: str, body: str, extra_class: str = "") -> str:
    """답변 카드 안의 영역 상자(① 절차, ② 사양 등)."""
    head = f'<div class="sec-head"><h4>{title}</h4>{dept_tag}</div>'
    return f'<div class="ans-sec {extra_class}">{head}{body}</div>'


def _section_body(section: AnswerSection) -> str:
    """영역 본문(줄마다 문단)과 근거 ID 줄. 근거에 내용이 없던 영역은 안내 문구만 보여 준다."""
    paras = "".join(f"<p>{escape(line)}</p>" for line in section.text.splitlines() if line.strip())
    if not paras:
        return '<p class="note">근거 문서에 해당 내용이 없어요</p>'
    # 안전 영역은 근거가 없어도 안전 참고 문구가 붙어 있어 근거 줄만 뺀다.
    return paras + (_source_link("근거 " + ", ".join(section.source_ids)) if section.source_ids else "")


def answer_html(ans: Answer) -> str:
    """답변 카드(U2): ① 작업 절차 ② 사양 수치 ③ 안전 요건 ④ 기준 차이 + 영역별 근거 ID."""
    # shortcut: 청크에 부서 메타데이터가 없어 부서 태그를 고정으로 붙인다, 메타데이터가 생기면 근거의 부서로 바꾼다
    maint, safe = ui.tag("유지보수팀", "blue"), ui.tag("안전팀", "orange")
    proc = _section("① 작업 절차", maint, _section_body(ans.procedure))
    spec = _section("② 사양 수치", maint, _section_body(ans.spec))
    diff = _section("④ 기준 차이", ui.tag("기준 차이", "yellow"), _section_body(ans.diff))
    safety = _section("③ 안전 요건", safe, _section_body(ans.safety), "safety")
    sections = (ans.procedure, ans.spec, ans.safety, ans.diff)
    count = len({i for s in sections for i in s.source_ids})
    head = (
        f'<div class="ans-head">{ui.ai_avatar()}<h3>답변</h3><span class="grow"></span>'
        f'<span class="meta">근거 {count}개</span></div>'
    )
    body = f'{proc}<div class="ans-grid">{spec}{diff}</div>{safety}'
    return f'<div class="card answer-card">{head}{body}{DISCLAIMER}</div>'


def no_answer_html(message: str = "", reason: str = "") -> str:
    """답변 불가 카드(U3 아래쪽). message.reason 은 서비스가 정한 안내 문구·이유다(목데이터 대화는 비어 있다).
    
    문서를 찾지 못한 경우와 처리 중 실패(llm_failure)를 제목으로 구분한다.
    """
    text = message or "등록된 매뉴얼·안전 문서 범위 밖의 질문이에요. 일반 지식으로 채워서 답하지 않아요."
    title = "지금은 답변할 수 없습니다" if reason == "llm_failure" else "문서에서 찾을 수 없습니다"
    card = (
        '<div class="card no-answer"><div class="na-head">'
        f'<span class="na-icon">{icons.svg("alert", TEXT2, 18)}</span>'
        f"<h4>{title}</h4></div>"
        f"<p>{escape(text)}</p></div>"
    )
    return f'<div class="bot-row">{ui.ai_avatar()}{card}</div>'


def clarify_head_html(ask: str) -> str:
    """되묻기 카드 윗부분: 서비스가 물은 질문(모델 또는 부위)과 선택지 이름표."""
    label = "설비 모델" if ask == MODEL_QUESTION else "부위"
    return (
        "<h4>조금만 더 알려주세요</h4>"
        f"<p>{escape(ask)} 고르면 바로 찾아볼께요.</p>"
        f'<span class="label">{label}</span>'
    )


def skipped_clarify_html() -> str:
    """되묻기에 답하지 않고 다음 질문으로 넘어간 경우, 그 되묻기를 기록으로만 남긴다."""
    card = (
        '<div class="card static-clarify"><h4>조금만 더 알려 주세요</h4>'
        "<p>모델·부위를 고르지 않고 다음 질문으로 넘어갔어요.</p></div>"
    )
    return f'<div class="bot-row">{ui.ai_avatar()}{card}</div>'


def rules_html() -> str:
    """되묻기·답변 불가 때 오른쪽에 보이는 안내 카드."""
    rows = "".join(
        f'<div class="rule">{icons.svg(i, BRAND, 18)}'
        f"<div><b>{escape(t)}</b><span>{escape(d)}</span></div></div>"
        for i, t, d in RULES
    )
    return f'<div class="card rules"><h3>이럴 때 되묻거나 답하지 않아요</h3>{rows}</div>'


def source_html(src: SourceView | None, empty: str = "근거를 고르면 원문이 여기에 보여요") -> str:
    """오른쪽 '근거 원문' 창 내용: 근거 청크(강조)와 같은 페이지의 앞뒤 문단."""
    if src is None:
        return f'<p class="note">{escape(empty)}</p>'
    before = f"<p>{escape(src.before)}</p>" if src.before else ""
    after = f"<p>{escape(src.after)}</p>" if src.after else ""
    body = f'{before}<div class="hl">{escape(src.text)}</div>{after}'
    kind = _kind(src)
    where = " · ".join(part for part in (src.doc_name, _loc(src)) if part)
    meta = f'<div class="src-meta">{ui.tag(kind, KIND_COLOR[kind])}<span>{escape(where)}</span></div>'
    return f'{meta}<div class="src-body">{body}</div>'



def turns_html(turns: list[dict]) -> str:
    """지금까지의 대화(질문 말풍선 + 답변/되묻기/답변 불가 카드)를 그린다."""
    out = []
    for turn in turns:
        out.append(ui.user_bubble(turn["q"]))
        if turn["kind"] == "clarify":
            out.append(skipped_clarify_html())
            continue
        if turn["kind"] != "answer":
            out.append(no_answer_html(turn.get("message", ""), turn.get("reason", "")))
            continue
        out.append(answer_html(turn["answer"]))
    return "".join(out)


# ------------------------------------------------------------------ 대화 상태
def _empty_state() -> dict:
    """대화 상태 초기값: 끝난 대화 목록, 되묻는 중인 질문, 마지막으로 고른 모델, 저장된 대화 ID."""
    return {"turns": [], "pending": None, "model": "", "conversation_id": None}


def _render(state: dict, thinking: str = "") -> tuple:
    """대화 상태에 맞게 화면 전체(질문 전/대화, 되묻기, 근거 창 등)를 다시 그린다.

    thinking 에 질문을 넣으면 그 질문 말풍선과 '답을 찾는 중' 표시를 대화 끝에 붙인다
    (답이 나오기 전까지 보여 주는 로딩 화면). 반환 순서는 build() 의 outputs 목록과 같다.
    """
    turns, pending = state["turns"], state["pending"]
    in_conv = bool(turns) or pending is not None or bool(thinking)
    show_answer = not thinking and pending is None and bool(turns) and turns[-1]["kind"] == "answer"
    convo = turns_html(turns) + (ui.user_bubble(pending["q"]) if pending else "")
    sources = _load_sources(state) if show_answer else []
    first = sources[0] if sources else None
    if thinking:
        convo += ui.user_bubble(thinking) + ui.typing_html(THINKING_TEXT)
    return (
        state,
        gr.Column(visible=not in_conv),
        gr.Column(visible=in_conv),
        convo,
        gr.Row(visible=pending is not None),
        gr.Column(visible=show_answer),
        gr.HTML(source_list_html(sources), visible=show_answer),
        gr.HTML(visible=in_conv and not show_answer and not thinking),
        source_html(first),
        _kind(first) if first else "매뉴얼",
        "",
        "",
        clarify_head_html(pending["ask"]) if pending else "",
        gr.Radio(choices=pending["options"] if pending else [], value=None), # 서비스가 준 후보로 매번 새로 고른다
        gr.Button(interactive=False),  # 고르기 전에는 '선택하고 계속'을 막는다
    )


def _thinking(state: dict, question: str) -> tuple:
    """답이 나오기 전 화면: 질문과 '답을 찾는 중'을 먼저 보여 준다(대화 상태는 아직 안 바꾼다)."""
    return (gr.skip(), *_render(state, thinking=question.strip())[1:])


@cache
def history_service() -> HistoryService:
    """기술 Q&A가 저장하고 질문 기록 화면이 읽는 대화 기록. 둘이 같은 기록을 쓰도록 하나만 만든다."""
    return HistoryService(MemoryHistoryStore())


@cache
def _service() -> QAService:
    """기술 Q&A 서비스. Chroma 청크를 모두 읽어 느리므로 처음 질문할 때 한 번만 만든다."""
    return build_qa_service(history=history_service())


@cache
def _test_service() -> QAService:
    """관리자 '질문 테스트'용 서비스. 질문 기록에 남지 않게 따로 만든 기록에 저장한다."""
    # shortcut: 기록만 다른데 Chroma 청크를 한 번 더 읽는다, 질문 테스트 첫 질문이 느리면 검색 부품을 공유한다
    return build_qa_service(history=HistoryService(MemoryHistoryStore()))


@cache
def _sources() -> SourceService:
    """근거 원문 서비스. Chroma 청크를 모두 읽어 느리므로 처음 쓸 때 한번만 만든다."""
    return build_source_service()


def _load_sources(state: dict) -> list[SourceView] | None:
    """마지막 답변의 근거 ID(영역 순서, 중복 제거)로 근거 원문을 찾는다. 불러오지 못하면 None 이다.
    
    지워진 청크처럼 찾을 수 없는 근거는 뺴고 보여 준다. 목데이터 답변은 근거 ID가 없어 빈 리스트다.
    """
    answer = state["turns"][-1].get("answer") if state["turns"] else None
    if not isinstance(answer, Answer):
        return []
    sections = (answer.procedure, answer.spec, answer.safety, answer.diff)
    ids = list(dict.fromkeys(i for s in sections for i in s.source_ids))
    try:
        service = _sources()
    except Exception:
        logging.getLogger(__name__).exception("failed to load source chunks")
        return None
    found = []
    for chunk_id in ids:
        try:
            found.append(service.get_source(chunk_id))
        except LookupError:
            continue
    return found


def _query(question: str, state: dict, *hints: str, test_mode: bool = False) -> Answer | Clarify | NoAnswer:
    """고른 모델·부위(hints)를 질문 앞에 붙여 Q&A 서비스에 묻는다. 유료 LLM API를 호출한다.
    
    test_mode면 질문 기록에 남지 않는 질문 테스트용 서비스에 묻는다.
    """
    text = " ".join([*(h for h in hints if h), question])
    try:
        service = _test_service() if test_mode else _service()
        return service.answer(text, state["conversation_id"], MEMBER_ID)
    except Exception:
        # Chroma·DB 접속이나 설정 오류가 나도 '찾는 중'에 멈추지 않게 답변 불가로 바꾼다
        logging.getLogger(__name__).exception("qa answer failed")
        return build_no_answer(None, "llm_failure") 


def _apply(state: dict, question: str, result: Answer | Clarify | NoAnswer) -> dict:
    """서비스 결과를 더한 새 대화 상태. 되묻기면 질문을 보류하고 되물은 내용·선택지와 함께 선택을 기다린다."""
    if isinstance(result, Clarify):
        return {**state, "pending": {"q": question, "ask": result.question, "options": result.options}}
    if isinstance(result, Answer):
        turn = {"q": question, "kind": "answer", "answer": result}
        state = {**state, "conversation_id": result.conversation_id}
    else:
        turn = {"q": question, "kind": "no_answer", "message": result.message, "reason": result.reason}
    return {**state, "turns": [*state["turns"], turn]}


def _ask(question: str, model: str, state: dict, test_mode: bool = False):
    """질문을 보내고 결과(답변·되묻기·답변 불가)를 대화에 더한다. 빈 질문은 무시한다.

    먼저 '찾는 중' 화면을 보여 주고, 결과가 나오면 그 화면으로 바꾼다.
    """
    question = (question or "").strip()
    if not question:
        yield tuple(gr.skip() for _ in range(OUTPUT_COUNT))
        return
    turns = list(state["turns"])
    if state["pending"] is not None:
        turns.append({"q": state["pending"]["q"], "kind": "clarify"})
    state = {**state, "turns": turns, "pending": None, "model": model or state["model"]}
    yield _thinking(state, question)
    yield _render(_apply(state, question, _query(question, state, state["model"], test_mode=test_mode)))


def _continue(choice: str, state: dict, test_mode: bool = False):
    """되묻기에서 고른 값(모델 또는 부위)을 질문에 붙여 다시 묻는다. 모델을 골랐으면 다음 질문에도 쓴다."""
    pending = state["pending"]
    if pending is None:
        yield _render(state)
        return
    is_model = pending["ask"] == MODEL_QUESTION
    state = {**state, "pending": None, "model": choice if is_model else state["model"]}
    part = "" if is_model else choice
    yield _thinking(state, pending["q"])
    yield _render(_apply(state, pending["q"], _query(pending["q"], state, state["model"], part, test_mode=test_mode)))


def _cancel(state: dict) -> tuple:
    """되묻기를 취소한다. 앞선 대화가 없으면 질문 전 화면으로 돌아간다."""
    return _render({**state, "pending": None})


def _pick_source(state: dict, evt: gr.SelectData) -> tuple:
    """근거 목록에서 누른 근거를 원문 창에 띄우고 탭(매뉴얼/안전 조항)을 맞춘다."""
    sources = _load_sources(state) or []
    if evt.index >= len(sources):
        return source_html(None), gr.skip()
    src = sources[evt.index]
    return source_html(src), _kind(src)


def _pick_recent(state: dict, evt: gr.SelectData):
    """최근 질문 줄을 누르면 그 질문을 다시 보낸다(목데이터)."""
    yield from _ask(mock.RECENT_QUESTIONS[evt.index]["title"], "", state)


def _model_classes(model: str) -> gr.Dropdown:
    """모델을 고르면 글자색을 진하게, 고르지 않으면 안내 문구처럼 흐리게 한다."""
    return gr.Dropdown(elem_classes=["model-select", "filled"] if model else ["model-select"])


def _pick_tab(kind: str, state: dict) -> str:
    """원문 창 탭을 바꾸면 그 종류의 첫 근거를 보여 준다."""
    src = next((s for s in _load_sources(state) or [] if _kind(s) == kind), None)
    return source_html(src, f"이 답변에는 {kind} 근거가 없어요")


# ------------------------------------------------------------------ 화면 구성
def _build_ask(test_mode: bool) -> dict:
    """질문 전 화면(U1): 질문 카드, 자주 찾는 작업, 오른쪽 최근 질문·최근 변경사항."""
    c = {}
    with gr.Column(elem_classes=["qa-ask"]) as c["view"]:
        with gr.Row(elem_classes=["body-row"]):
            with gr.Column(elem_classes=["content"]):
                caption = "테스트 질문은 질문 기록에 남지 않아요" if test_mode else ""
                gr.HTML(ui.section_title("질문하기", caption), padding=False)
                _question_card(c)
                if not test_mode:
                    gr.HTML(ui.section_title("자주 찾는 작업"), padding=False)
                    gr.HTML(task_cards_html(), padding=False)
            if not test_mode:
                with gr.Column(elem_classes=["right-panel"]):
                    c["recent"] = ui.click_list(recent_questions_html())
                    gr.HTML(recent_changes_html(), padding=False)
    return c


def _model_row(c: dict) -> None:
    """설비 모델 선택 줄. 고르지 않아도 질문할 수 있다(값은 빈 문자열)."""
    # 질문 분석은 등록된 모델 이름만 남기므로 기준정보의 모델 이름을 그대로 보여준다.
    names = [m.name for m in EquipmentModelService().list_models()]
    choices = [("설비 모델 선택 (선택 사항)", "")] + [(n, n) for n in names]
    with gr.Row(elem_classes=["model-row"]):
        c["model"] = gr.Dropdown(
            choices=choices,
            value="",
            show_label=False,
            container=False,
            elem_classes=["model-select"],
            scale=0,
            min_width=300,
        )


def _question_card(c: dict) -> None:
    """모델 선택 + 질문 입력 + 예시 질문 + 질문하기 버튼 카드(연파랑 카드 하나)."""
    with gr.Column(elem_classes=["question-panel"]):
        _model_row(c)
        with gr.Column(elem_classes=["question-box"]):
            c["text"] = gr.Textbox(
                placeholder="예: [모델 A] 메인 로프 점검할 때 기준이 뭐야?",
                lines=2,
                max_lines=5,
                show_label=False,
                container=False,
                elem_classes=["q-text"],
            )
            with gr.Row(elem_classes=["q-actions"]):
                c["examples"] = [
                    gr.Button(t, elem_classes=["chip"], scale=0, min_width=0)
                    for t in mock.EXAMPLE_QUESTIONS
                ]
                gr.HTML("", padding=False, scale=1)
                c["ask"] = gr.Button(
                    "질문하기",
                    elem_classes=["btn-primary"],
                    scale=0,
                    min_width=110,
                    interactive=False,
                )


def _build_conv(test_mode: bool) -> dict:
    """대화 화면(U2·U3): 질문·답변 목록, 되묻기 카드, 만족 버튼, 이어서 질문, 오른쪽 근거."""
    c = {}
    with gr.Column(visible=False, elem_classes=["qa-conv"]) as c["view"]:
        with gr.Row(elem_classes=["body-row", "chat-layout"]):
            with gr.Column(elem_classes=["content", "conv"]):
                if test_mode:
                    gr.HTML(ui.tag("테스트 질문은 질문 기록에 남지 않아요"), padding=False)
                with gr.Column(elem_classes=["chat-scroll"]):
                    c["turns"] = ui.chat_html()
                    _clarify_card(c)
                with gr.Row(elem_classes=["chat-input"]):
                    c["follow"] = gr.Textbox(
                        placeholder="이어서 질문하기",
                        show_label=False,
                        container=False,
                        scale=1,
                        max_lines=3,
                        elem_classes=["chat-text"],
                    )
                    c["send"] = gr.Button(
                        "", elem_classes=["send-btn"], scale=0, min_width=40, interactive=False
                    )
            with gr.Column(elem_classes=["right-panel", "wide", "side-scroll"]):
                _source_panel(c)
                c["rules"] = gr.HTML(rules_html(), visible=False, padding=False)
    return c


def _clarify_card(c: dict) -> None:
    """되묻기 카드(U3): 서비스가 되물은 모델 또는 부위 후보 하나를 골라 이어서 찾는다."""
    with gr.Row(visible=False, elem_classes=["bot-row", "clarify-row"]) as c["clarify"]:
        gr.HTML(ui.ai_avatar(), padding=False, scale=0, min_width=32)
        with gr.Column(elem_classes=["card", "clarify-card"]):
            c["clar_head"]= gr.HTML(padding=False)
            # 선택지는 되묻기마다 _render가 Clarify.options로 바꿔 넣는다.
            c["clar_pick"] = ui.chip_radio(mock.MODELS, empty=True)
            with gr.Row(elem_classes=["clarify-actions"]):
                c["cont"] = gr.Button(
                    "선택하고 계속",
                    elem_classes=["btn-primary", "sm-btn"],
                    scale=0,
                    min_width=0,
                    interactive=False,
                )
                c["cancel"] = gr.Button(
                    "취소", elem_classes=["btn-secondary", "sm-btn"], scale=0, min_width=0
                )


def _source_panel(c: dict) -> None:
    """오른쪽 '근거 원문' 창과 '근거 목록'."""
    with gr.Column(elem_classes=["card", "source-card"]) as c["src_panel"]:
        gr.HTML("<h3>근거 원문</h3>", padding=False)
        c["src_tab"] = gr.Radio(
            ["매뉴얼", "안전 조항"],
            value="매뉴얼",
            show_label=False,
            container=False,
            elem_classes=["chip-radio"],
        )
        c["viewer"] = gr.HTML(source_html(None), padding=False)
    c["src_list"] = ui.click_list(source_list_html([]))



def build(test_mode: bool = False) -> QAView:
    """기술 Q&A 화면을 만들고 이벤트를 연결한다. 호출한 위치(화면 Column 안)에 그려진다."""
    state = gr.State(_empty_state())
    ask = _build_ask(test_mode)
    conv = _build_conv(test_mode)
    outs = [state, ask["view"], conv["view"], conv["turns"], conv["clarify"]]
    outs += [conv["src_panel"], conv["src_list"], conv["rules"], conv["viewer"], conv["src_tab"]]
    outs += [ask["text"], conv["follow"]]
    outs += [conv["clar_head"], conv["clar_pick"], conv["cont"]]
    ask_fn = partial(_ask, test_mode=test_mode) # 질문 테스트 화면은 질문 기록에 남지 않는 서비스로 묻는다
    ask["ask"].click(ask_fn, [ask["text"], ask["model"], state], outs, **QUIET)
    ask["text"].submit(ask_fn, [ask["text"], ask["model"], state], outs, **QUIET)
    conv["send"].click(ask_fn, [conv["follow"], ask["model"], state], outs, **QUIET)
    conv["follow"].submit(ask_fn, [conv["follow"], ask["model"], state], outs, **QUIET)
    for btn, text in zip(ask["examples"], mock.EXAMPLE_QUESTIONS, strict=True):
        btn.click(lambda t=text: t, None, ask["text"])
    if "recent" in ask:
        ask["recent"].select(_pick_recent, state, outs, **QUIET)
    ui.enable_when_filled(ask["text"], ask["ask"])
    ui.enable_when_filled(conv["follow"], conv["send"])
    ui.enable_when_chosen([conv["clar_pick"]], conv["cont"])
    conv["cont"].click(partial(_continue, test_mode= test_mode), [conv["clar_pick"], state], outs, **QUIET)
    conv["cancel"].click(_cancel, state, outs)
    conv["src_list"].select(_pick_source, state, [conv["viewer"], conv["src_tab"]])
    conv["src_tab"].input(_pick_tab, [conv["src_tab"], state], conv["viewer"])
    ask["model"].change(_model_classes, ask["model"], ask["model"])
    return QAView(reset_outputs=[*outs, ask["model"]])
