import logging
import re
from collections.abc import Callable
from dataclasses import replace

from pydantic import BaseModel

from core import llm
from core.schemas import Answer, AnswerDraft, AnswerSection, Evidence
from features.evaluation.scoring import contains_number
from features.qa.diff_checker import build_comparison, format_comparison

logger = logging.getLogger(__name__)

SAFETY_NOTICE = "AI가 문서에서 찾은 참고 정보이며 최종 판단은 안전관리자 확인이 필요합니다."
DOC_TYPE_LABELS = {"tech": "매뉴얼", "secure": "안전 문서"}
PROMPT = """너는 장비 유지보수 기술 문서 Q&A 도우미다. 아래 [근거]에 있는 내용만 사용해 [질문]에 답한다.

규칙:
- 답을 4개 영역으로 나눈다. procedure(작업 절차), spec(사양·수치), safety(안전 요건), diff(매뉴얼과 안전 기준의 차이).
- 각 영역의 source_ids에는 그 영역을 쓸 때 참고한 근거 ID만 넣는다. 근거에 없는 ID를 만들지 않는다.
- 근거에 없는 내용은 쓰지 않는다. 쓸 내용이 없는 영역은 text를 빈 문자열, source_ids를 빈 목록으로 둔다.
- 수치와 단위는 근거에 적힌 그대로 쓴다.
- 안전 참고 문구는 쓰지 않는다. 시스템이 따로 붙인다.
- [코드로 비교한 결과]가 있으면 diff 영역은 그 결과를 바탕으로 쓴다. 값·단위·판정(충족·미충족·동일·다름·비교 불가)을 바꾸지 않고, 환산한 값은 새로 쓰지 않으며, 그 줄의 [근거 ID]를 diff 영역의 source_ids에 넣는다. "비교 불가"는 그 이유와 함께 그대로 알린다. 결과가 "없음"이면 [근거]만 보고 쓴다.

[질문]
{question}

[근거]
{evidence}

[코드로 비교한 결과]
{comparison}"""

# 근거 원문과 대조할 "숫자+단위". 예: "0.5mm", "10%", "40 N·m"
# shortcut: 한글 단위(회·개·초 등)와 단위 없는 숫자는 단계 번호와 구분하기 어려워 검사하지 않는다, 오답이 보이면 범위를 넓힌다
# 앞에 영문·숫자가 붙은 값(모델 번호 HC20022US1 등)은 수치가 아니라서 뺀다
_UNIT_NUMBER = re.compile(r"(?<![A-Za-z\d.,])\d+(?:[.,]\d+)*\s*[a-zA-Zµ%°][a-zA-Zµ%°·/²³]*")


def _comparison_text(question: str, evidence: Evidence) -> str:
    """근거 청크의 수치를 코드로 비교한 결과 글. 비교에 실패해도 답변 생성은 막지 않으므로 오류는 로그만 남기고 빈 글을 돌려준다."""
    try:
        return format_comparison(build_comparison(evidence, question))
    except Exception:
        logger.exception("diff comparison failed")
        return ""


def _assumed_values(question: str, evidence: Evidence) -> dict[str, list[str]]:
    """근거 청크 ID별로, 표에 단위가 적혀 있지 않아 코드가 단위를 붙여 읽은 값("PIT: 1250" → "1250 mm")을 돌려준다.

    답변에 "1250 mm"라고 쓰면 원문에는 "1250"뿐이라 근거 검사가 거절하므로, 그 영역이 인용한 청크에서
    읽은 값은 원문에 있는 것으로 인정한다. 환산한 값(1.25 m)은 여기에 없어서 여전히 거절된다.
    """
    try:
        items = build_comparison(evidence, question)
    except Exception:
        logger.exception("diff comparison failed")
        return {}
    assumed: dict[str, list[str]] = {}
    for item in items:
        assumed.setdefault(item.tech.source_id, []).append(f"{item.tech.value:g} {item.tech.unit}")
    return assumed


class _SectionOutput(BaseModel):
    """LLM이 채울 답변 영역 하나."""

    text: str
    source_ids: list[str]


class _DraftOutput(BaseModel):
    """LLM이 채울 답변 4개 영역."""

    procedure: _SectionOutput
    spec: _SectionOutput
    safety: _SectionOutput
    diff: _SectionOutput


class AnswerGenerator:
    """검색 근거만으로 4개 영역 답변을 만들고 근거·수치를 검사한다(QAService의 Generator 구현).
    
    complete에는 보통 core.llm.complete를 쓰고, 테스트에는 가짜 함수로 바꿔 끼운다.
    """

    def __init__(self, complete: Callable[..., dict] = llm.complete) -> None:
        """LLM 호출 함수를 받아 둔다."""
        self._complete = complete

    def generate(self, question: str, evidence: Evidence) -> AnswerDraft:
        """근거만 사용해 절차·사양·안전·기준 차이 답변과 영역별 근거 ID를 만든다.
        
        유료 외부 API(OpenAI)를 호출한다. 재시도 후에도 실패하면 complete가 LlmError를 발생시킨다.
        """
        evidence_text = "\n\n".join(
            f"[ID: {c.chunk_id}] ({DOC_TYPE_LABELS.get(c.doc_type, c.doc_type)})\n{c.text}"
            for c in evidence.chunks
        )
        comparison = _comparison_text(question, evidence)
        prompt = PROMPT.format(question=question, evidence=evidence_text, comparison=comparison or "없음")
        result = self._complete("L2", prompt, _DraftOutput)
        return AnswerDraft(**{name: AnswerSection(**section) for name, section in result.items()})

    def verify_sources(self, draft: AnswerDraft, evidence: Evidence, question: str = "") -> AnswerDraft | None:
        """답변이 근거와 맞으면 draft를, 맞지 않으면 None을 반환한다. LLM은 부르지 않는다.
        
        4개 영역이 모두 비었거나, 글이 있는 영역에 근거 ID가 없거나 근거에 없는 ID가 있거나,
        글에 나온 숫자+단위가 그 영역이 인용한 근거 원문에 없으면 맞지 않는 것으로 본다.
        질문에 있던 숫자+단위(예: "1000kg 모델")는 답에 되풀이해도 새로 지어낸 값이 아니므로 통과시킨다.
        """
        texts = {c.chunk_id: c.text for c in evidence.chunks}
        assumed = _assumed_values(question, evidence)
        sections = [draft.procedure, draft.spec, draft.safety, draft.diff]
        if not any(s.text.strip() for s in sections):
            return None
        for section in sections:
            if not section.text.strip():
                continue
            if not section.source_ids or any(i not in texts for i in section.source_ids):
                return None
            extra = [text for i in section.source_ids for text in assumed.get(i, [])]
            cited = "\n".join([question, *(texts[i] for i in section.source_ids), *extra])
            if not all(contains_number(cited, n.strip()) for n in _UNIT_NUMBER.findall(section.text)):
                return None
        return draft
    
def attach_notice(draft: AnswerDraft) -> Answer:
    """안전 요건 영역 맨 앞에 안전 참고 문구를 붙여 최종 답변을 만든다.

    LLM 출력과 상관없이 코드가 항상 붙이므로 안전 영역이 비어 있어도 문구는 들어간다.
    draft는 바꾸지 않고 새 Answer를 반환한다.
    """
    body = draft.safety.text
    safety_text = f"{SAFETY_NOTICE}\n\n{body}" if body else SAFETY_NOTICE
    return Answer(
        procedure=draft.procedure,
        spec=draft.spec,
        safety=replace(draft.safety, text=safety_text),
        diff=draft.diff,
    )
