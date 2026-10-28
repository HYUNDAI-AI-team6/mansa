import re
from collections.abc import Callable
from dataclasses import replace

from pydantic import BaseModel

from core import llm
from core.schemas import Answer, AnswerDraft, AnswerSection, Evidence
from features.evaluation.scoring import contains_number

SAFETY_NOTICE = "AI가 문서에서 찾은 참고 정보이며 최종 판단은 안전관리자 확인이 필요합니다."
DOC_TYPE_LABELS = {"tech": "매뉴얼", "secure": "안전 문서"}
PROMPT = """너는 장비 유지보수 기술 문서 Q&A 도우미다. 아래 [근거]에 있는 내용만 사용해 [질문]에 답한다.

규칙:
- 답을 4개 영역으로 나눈다. procedure(작업 절차), spec(사양·수치), safety(안전 요건), diff(매뉴얼과 안전 기준의 차이).
- 각 영역의 source_ids에는 그 영역을 쓸 때 참고한 근거 ID만 넣는다. 근거에 없는 ID를 만들지 않는다.
- 근거에 없는 내용은 쓰지 않는다. 쓸 내용이 없는 영역은 text를 빈 문자열, source_ids를 빈 목록으로 둔다.
- 수치와 단위는 근거에 적힌 그대로 쓴다.
- 안전 참고 문구는 쓰지 않는다. 시스템이 따로 붙인다.

[질문]
{question}

[근거]
{evidence}"""

# 근거 원문과 대조할 "숫자+단위". 예: "0.5mm", "10%", "40 N·m"
# shortcut: 한글 단위(회·개·초 등)와 단위 없는 숫자는 단계 번호와 구분하기 어려워 검사하지 않는다, 오답이 보이면 범위를 넓힌다
_UNIT_NUMBER = re.compile(r"\d+(?:[.,]\d+)*\s*[a-zA-Zµ%°][a-zA-Zµ%°·/²³]*")


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
        result = self._complete("L2", PROMPT.format(question=question, evidence=evidence_text), _DraftOutput)
        return AnswerDraft(**{name: AnswerSection(**section) for name, section in result.items()})

    def verify_sources(self, draft: AnswerDraft, evidence: Evidence) -> AnswerDraft | None:
        """답변이 근거와 맞으면 draft를, 맞지 않으면 None을 반환한다. LLM은 부르지 않는다.
        
        4개 영역이 모두 비었거나, 글이 있는 영역에 근거 ID가 없거나 근거에 없는 ID가 있거나,
        글에 나온 숫자+단위가 그 영역이 인용한 근거 원문에 없으면 맞지 않는 것으로 본다.
        """
        texts = {c.chunk_id: c.text for c in evidence.chunks}
        sections = [draft.procedure, draft.spec, draft.safety, draft.diff]
        if not any(s.text.strip() for s in sections):
            return None
        for section in sections:
            if not section.text.strip():
                continue
            if not section.source_ids or any(i not in texts for i in section.source_ids):
                return None
            cited = "\n".join(texts[i] for i in section.source_ids)
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
