class LlmError(Exception):
    """LLM 호출이 시간 초과나 응답 형식 오류로 재시도 후에도 실패했을 때 발생한다."""
