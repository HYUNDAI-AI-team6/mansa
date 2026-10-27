from dataclasses import replace

from core.schemas import Answer, AnswerDraft

SAFETY_NOTICE = "AI가 문서에서 찾은 참고 정보이며 최종 판단은 안전관리자 확인이 필요합니다."


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
