"""기술 Q&A 화면: 질문 전(U1) → 대화(답변 U2 / 되묻기·답변 불가 U3).

관리자 '질문 테스트'도 test_mode=True 로 같은 화면을 다시 쓴다.
"""

from dataclasses import dataclass, field
from html import escape

import gradio as gr

from ui import components as ui
from ui import icons
from ui import mock_data as mock
from ui.theme import BRAND, TEXT2

DEPT_COLOR = {"유지보수팀": "blue", "안전팀": "orange", "검사·품질팀": "teal"}
QUIET = {"show_progress": "hidden"}  # 로딩은 우리가 그린 '찾는 중' 표시로 보여 준다
THINKING_TEXT = "문서에서 답을 찾고 있어요"
OUTPUT_COUNT = 15  # _render() 가 돌려주는 값 개수 = build() 의 outs 개수
DISCLAIMER = '<p class="disclaimer">참고용 안내이며 법적 판단이 아닙니다.</p>'
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

    def open_history(self, index: int) -> tuple:
        """질문 기록 index 번 대화를 펼쳐 대화 화면으로 보여 준다."""
        state = {"turns": mock.history_turns(index), "pending": None, "model": ""}
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


def source_list_html() -> str:
    """'근거 목록' 카드. 줄을 누르면 위 '근거 원문' 창에 그 근거를 띄운다."""
    rows = "".join(
        f'<button type="button" class="src-row" data-i="{i}">{ui.tag(s.dept, DEPT_COLOR[s.dept])}'
        f"<b>{escape(s.title)}</b><span>{escape(s.loc)}</span></button>"
        for i, s in enumerate(mock.SOURCES)
    )
    return f'<div class="card source-list"><h3>근거 목록</h3>{rows}</div>'


def _rows(items: list[tuple[str, str]]) -> str:
    """'이름 ··· 값' 줄 목록을 만든다."""
    return "".join(
        f'<div class="kv"><span>{escape(k)}</span><b>{escape(v)}</b></div>' for k, v in items
    )


def _source_link(text: str) -> str:
    """파란 출처 링크 한 줄."""
    return f'<div class="src-link">{icons.svg("link", BRAND, 16)}{escape(text)}</div>'


def _section(title: str, dept_tag: str, body: str, extra_class: str = "") -> str:
    """답변 카드 안의 영역 상자(① 절차, ② 사양 등)."""
    head = f'<div class="sec-head"><h4>{title}</h4>{dept_tag}</div>'
    return f'<div class="ans-sec {extra_class}">{head}{body}</div>'


def _safety_html(safety: list[tuple[str, str]]) -> str:
    """③ 안전 요건 상자: 안전 조항 목록 + 안전관리자 확인 안내."""
    items = "".join(
        f'<div class="safe-item"><b>{escape(t)}</b><span>{escape(s)}</span></div>'
        for t, s in safety
    )
    notice = (
        f'<div class="safe-notice">{icons.svg("info", "#C2410C", 16)}'
        "AI가 문서에서 찾은 참고 정보입니다. 최종 판단은 안전관리자 확인이 필요합니다.</div>"
    )
    head = f"{icons.svg('shield', '#C2410C', 18)}<h4>③ 안전 요건</h4>"
    return (
        f'<div class="ans-sec safety"><div class="sec-head">{head}'
        f"{ui.tag('안전팀', 'orange')}</div>{items}{notice}</div>"
    )


def answer_html(ans: mock.Answer) -> str:
    """답변 카드(U2): ① 작업 절차 ② 사양 수치 ③ 안전 요건 ④ 기준 차이 + 출처."""
    steps = "".join(f"<li>{escape(s)}</li>" for s in ans.procedure)
    proc = _section(
        "① 작업 절차",
        ui.tag("유지보수팀", "blue"),
        f"<ol>{steps}</ol>{_source_link('[매뉴얼명] 5.3.2 · p.42')}",
    )
    spec = _section(
        "② 사양 수치",
        ui.tag("유지보수팀", "blue"),
        _rows(ans.specs) + _source_link("[매뉴얼명] 표 5-2 · p.44"),
    )
    diff = _section(
        "④ 기준 차이",
        ui.tag("기준 차이", "yellow"),
        _rows(ans.diffs)
        + '<p class="note">조건이 다르면 단정해서 비교하지 않아요</p>'
        + _source_link("산업안전보건기준 규칙 제○○조"),
    )
    head = (
        f'<div class="ans-head">{ui.ai_avatar()}<h3>답변</h3>{ui.tag(ans.model, "blue")}'
        f'{ui.tag(ans.place)}<span class="grow"></span>'
        '<span class="meta">근거 4개 · 2개 부서</span></div>'
    )
    body = f'{proc}<div class="ans-grid">{spec}{diff}</div>{_safety_html(ans.safety)}'
    return f'<div class="card answer-card">{head}{body}{DISCLAIMER}</div>'


def no_answer_html() -> str:
    """답변 불가 카드(U3 아래쪽)."""
    card = (
        '<div class="card no-answer"><div class="na-head">'
        f'<span class="na-icon">{icons.svg("alert", TEXT2, 18)}</span>'
        "<h4>문서에서 찾을 수 없습니다</h4></div>"
        "<p>등록된 매뉴얼·안전 문서 범위 밖의 질문이에요. "
        "일반 지식으로 채워서 답하지 않아요.</p></div>"
    )
    return f'<div class="bot-row">{ui.ai_avatar()}{card}</div>'


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


def source_html(src: mock.Source) -> str:
    """오른쪽 '근거 원문' 창 내용."""
    paras = [f"<p>{escape(t)}</p>" for t in src.lines]
    highlight = f'<div class="hl">{escape(src.highlight)}</div>'
    body = "".join(paras[:1]) + highlight + "".join(paras[1:])
    where = f"{escape(src.title)} · {escape(src.loc)}"
    meta = (
        f'<div class="src-meta">{ui.tag(src.dept, DEPT_COLOR[src.dept])}<span>{where}</span></div>'
    )
    heading = f'<span class="src-heading">{escape(src.heading)}</span>'
    return f'{meta}<div class="src-body">{heading}{body}</div>'


def turns_html(turns: list[dict]) -> str:
    """지금까지의 대화(질문 말풍선 + 답변/되묻기/답변 불가 카드)를 그린다."""
    out = []
    for turn in turns:
        out.append(ui.user_bubble(turn["q"]))
        if turn["kind"] == "clarify":
            out.append(skipped_clarify_html())
            continue
        if turn["kind"] != "answer":
            out.append(no_answer_html())
            continue
        out.append(answer_html(turn["answer"]))
    return "".join(out)


# ------------------------------------------------------------------ 대화 상태
def _empty_state() -> dict:
    """대화 상태 초기값: 끝난 대화 목록, 되묻는 중인 질문, 마지막으로 고른 모델."""
    return {"turns": [], "pending": None, "model": ""}


def _render(state: dict, thinking: str = "") -> tuple:
    """대화 상태에 맞게 화면 전체(질문 전/대화, 되묻기, 근거 창 등)를 다시 그린다.

    thinking 에 질문을 넣으면 그 질문 말풍선과 '답을 찾는 중' 표시를 대화 끝에 붙인다
    (답이 나오기 전까지 보여 주는 로딩 화면). 반환 순서는 build() 의 outputs 목록과 같다.
    """
    turns, pending = state["turns"], state["pending"]
    in_conv = bool(turns) or pending is not None or bool(thinking)
    show_answer = not thinking and pending is None and bool(turns) and turns[-1]["kind"] == "answer"
    convo = turns_html(turns) + (ui.user_bubble(pending["q"]) if pending else "")
    if thinking:
        convo += ui.user_bubble(thinking) + ui.typing_html(THINKING_TEXT)
    return (
        state,
        gr.Column(visible=not in_conv),
        gr.Column(visible=in_conv),
        convo,
        gr.Row(visible=pending is not None),
        gr.Column(visible=show_answer),
        gr.HTML(visible=show_answer),
        gr.HTML(visible=in_conv and not show_answer and not thinking),
        source_html(mock.SOURCES[0]),
        "매뉴얼",
        "",
        "",
        None,  # 되묻기 카드: 모델·부위는 매번 새로 고르고
        None,
        gr.Button(interactive=False),  # 둘 다 고르기 전에는 '선택하고 계속'을 막는다
    )


def _thinking(state: dict, question: str) -> tuple:
    """답이 나오기 전 화면: 질문과 '답을 찾는 중'을 먼저 보여 준다(대화 상태는 아직 안 바꾼다)."""
    return (gr.skip(), *_render(state, thinking=question.strip())[1:])


def _ask(question: str, model: str, state: dict):
    """질문을 보내고 결과(답변·되묻기·답변 불가)를 대화에 더한다. 빈 질문은 무시한다.

    먼저 '찾는 중' 화면을 보여 주고, 결과가 나오면 그 화면으로 바꾼다.
    지금은 mock_data.mock_ask 를 부른다. 기술 Q&A 기능이 생기면 그 함수로 바꾼다.
    """
    if not (question or "").strip():
        yield tuple(gr.skip() for _ in range(OUTPUT_COUNT))
        return
    turns = list(state["turns"])
    if state["pending"] is not None:
        turns.append({"q": state["pending"]["q"], "kind": "clarify"})
    state = {"turns": turns, "pending": None, "model": model or state["model"]}
    yield _thinking(state, question)
    mock.wait()
    result = mock.mock_ask(question, state["model"])
    if result["type"] == "clarify":
        state["pending"] = {"q": question.strip()}
    elif result["type"] == "answer":
        state["turns"].append({"q": question.strip(), "kind": "answer", "answer": result["answer"]})
        state["model"] = result["answer"].model  # 이어지는 질문도 같은 모델로 찾는다
    else:
        state["turns"].append({"q": question.strip(), "kind": "no_answer"})
    yield _render(state)


def _continue(model: str, part: str, state: dict):
    """되묻기에서 고른 모델로 답변을 만든다. part 는 지금 목데이터에서는 쓰지 않는다."""
    if state["pending"] is None:
        yield _render(state)
        return
    question = state["pending"]["q"]
    yield _thinking({**state, "pending": None}, question)
    mock.wait()
    answer = mock.mock_answer_for(question, model)
    turns = state["turns"] + [{"q": question, "kind": "answer", "answer": answer}]
    yield _render({"turns": turns, "pending": None, "model": model})


def _cancel(state: dict) -> tuple:
    """되묻기를 취소한다. 앞선 대화가 없으면 질문 전 화면으로 돌아간다."""
    return _render({**state, "pending": None})


def _pick_source(evt: gr.SelectData) -> tuple[str, str]:
    """근거 목록에서 누른 근거를 원문 창에 띄우고 탭(매뉴얼/안전 조항)을 맞춘다."""
    src = mock.SOURCES[evt.index]
    return source_html(src), src.kind


def _pick_recent(state: dict, evt: gr.SelectData):
    """최근 질문 줄을 누르면 그 질문을 다시 보낸다(목데이터)."""
    yield from _ask(mock.RECENT_QUESTIONS[evt.index]["title"], "", state)


def _model_classes(model: str) -> gr.Dropdown:
    """모델을 고르면 글자색을 진하게, 고르지 않으면 안내 문구처럼 흐리게 한다."""
    return gr.Dropdown(elem_classes=["model-select", "filled"] if model else ["model-select"])


def _pick_tab(kind: str) -> str:
    """원문 창 탭을 바꾸면 그 종류의 첫 근거를 보여 준다."""
    src = next(s for s in mock.SOURCES if s.kind == kind)
    return source_html(src)


# ------------------------------------------------------------------ 화면 구성
def _build_ask(test_mode: bool) -> dict:
    """질문 전 화면(U1): 질문 카드, 자주 찾는 작업, 오른쪽 최근 질문·최근 변경사항."""
    c = {}
    with gr.Column(elem_classes=["qa-ask"]) as c["view"]:
        with gr.Row(elem_classes=["body-row"]):
            with gr.Column(elem_classes=["content"]):
                gr.HTML(ui.section_title("질문하기"), padding=False)
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
    choices = [("설비 모델 선택 (선택 사항)", "")] + [(m, m) for m in mock.MODELS]
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
    """되묻기 카드(U3): 모델·부위 후보를 골라 이어서 찾는다."""
    with gr.Row(visible=False, elem_classes=["bot-row", "clarify-row"]) as c["clarify"]:
        gr.HTML(ui.ai_avatar(), padding=False, scale=0, min_width=32)
        with gr.Column(elem_classes=["card", "clarify-card"]):
            gr.HTML(
                "<h4>조금만 더 알려 주세요</h4>"
                "<p>어느 모델의 어떤 부위인가요? 고르면 바로 찾아볼게요.</p>"
                '<span class="label">설비 모델</span>',
                padding=False,
            )
            c["clar_model"] = ui.chip_radio(mock.MODELS, empty=True)
            gr.HTML('<span class="label">부위</span>', padding=False)
            c["clar_part"] = ui.chip_radio(mock.CLARIFY_PARTS, empty=True)
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
        c["viewer"] = gr.HTML(source_html(mock.SOURCES[0]), padding=False)
    c["src_list"] = ui.click_list(source_list_html())


def build(test_mode: bool = False) -> QAView:
    """기술 Q&A 화면을 만들고 이벤트를 연결한다. 호출한 위치(화면 Column 안)에 그려진다."""
    state = gr.State(_empty_state())
    ask = _build_ask(test_mode)
    conv = _build_conv(test_mode)
    outs = [state, ask["view"], conv["view"], conv["turns"], conv["clarify"]]
    outs += [conv["src_panel"], conv["src_list"], conv["rules"], conv["viewer"], conv["src_tab"]]
    outs += [ask["text"], conv["follow"]]
    outs += [conv["clar_model"], conv["clar_part"], conv["cont"]]

    ask["ask"].click(_ask, [ask["text"], ask["model"], state], outs, **QUIET)
    ask["text"].submit(_ask, [ask["text"], ask["model"], state], outs, **QUIET)
    conv["send"].click(_ask, [conv["follow"], ask["model"], state], outs, **QUIET)
    conv["follow"].submit(_ask, [conv["follow"], ask["model"], state], outs, **QUIET)
    for btn, text in zip(ask["examples"], mock.EXAMPLE_QUESTIONS, strict=True):
        btn.click(lambda t=text: t, None, ask["text"])
    if "recent" in ask:
        ask["recent"].select(_pick_recent, state, outs, **QUIET)
    ui.enable_when_filled(ask["text"], ask["ask"])
    ui.enable_when_filled(conv["follow"], conv["send"])
    ui.enable_when_chosen([conv["clar_model"], conv["clar_part"]], conv["cont"])
    conv["cont"].click(_continue, [conv["clar_model"], conv["clar_part"], state], outs, **QUIET)
    conv["cancel"].click(_cancel, state, outs)
    conv["src_list"].select(_pick_source, None, [conv["viewer"], conv["src_tab"]])
    conv["src_tab"].input(_pick_tab, conv["src_tab"], conv["viewer"])
    ask["model"].change(_model_classes, ask["model"], ask["model"])
    return QAView(reset_outputs=[*outs, ask["model"]])
