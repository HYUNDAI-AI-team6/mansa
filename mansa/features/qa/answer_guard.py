from core.schemas import Evidence, Intent, NoAnswer, NoAnswerReason

# shortcut: 임시 기준값이다. 실제 검색 점수 분포를 확인한 뒤 조정한다.
MIN_EVIDENCE_SCORE = 0.3
DEFAULT_CONTACT = "안전관리팀"

_NO_ANSWER_MESSAGES: dict[NoAnswerReason, str] = {
    "insufficient_evidence": "문서에서 찾을 수 없습니다. {contact}에 확인해 주세요.",
    "out_of_scope": "장비 기술 문서로 답할 수 있는 질문이 아닙니다. {contact}에 확인해 주세요.",
    "llm_failure": "지금은 답변을 만들 수 없습니다. 잠시 후 다시 시도하거나 {contact}에 확인해 주세요.",
}


def is_sufficient(
    intent: Intent, evidence: Evidence, min_score: float = MIN_EVIDENCE_SCORE
) -> bool:
    """근거만으로 답변을 써도 되는지 판단한다.

    범위 밖 질문이거나, 근거가 없거나, 가장 높은 근거 점수가 min_score 미만이면 False다.
    점수만 보는 형식 검사이며 근거 내용이 질문에 실제로 답하는지는 확인하지 않는다.
    """
    if intent.intent == "out_of_scope" or not evidence.chunks:
        return False
    return max(c.score for c in evidence.chunks) >= min_score


def build_no_answer(
    intent: Intent | None, reason: NoAnswerReason, contact: str = DEFAULT_CONTACT
) -> NoAnswer:
    """답변 불가 안내를 만든다. LLM을 부르지 않으므로 일반 지식으로 내용을 채우지 않는다.

    intent는 질문 분석 자체가 실패했을 때 None일 수 있다. 지금은 안내 문구에 쓰지 않지만
    질문 종류별 담당 부서 안내를 붙일 자리로 받아 둔다.
    알 수 없는 reason이면 KeyError가 발생한다.
    """
    message = _NO_ANSWER_MESSAGES[reason].format(contact=contact)
    return NoAnswer(reason=reason, message=message, contact=contact)
