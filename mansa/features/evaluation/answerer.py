"""평가 대상 응답기. 테스트셋 문항을 받아 AnswerRecord를 돌려준다."""

from collections.abc import Callable
from typing import Protocol

from features.evaluation.codex_cli import CodexError, CodexResult, run_codex
from features.evaluation.models import AnswerRecord, TestCase

ANSWER_PROMPT = """너는 승강기 유지보수 기술 문서를 바탕으로 답하는 Q&A 도우미다.
파일을 읽거나 명령을 실행하지 말고 아래 질문에 한국어로 바로 답해라.
수치에는 반드시 단위를 붙이고, 모르면 모른다고 답해라.

질문: {question}"""


class Answerer(Protocol):
    """평가할 Q&A 응답기. 실제 파이프라인이 생기면 이 형태로 어댑터를 추가한다."""

    name: str

    def answer(self, case: TestCase) -> AnswerRecord:
        """문항 하나에 답한다. 호출 실패는 예외 대신 error가 채워진 AnswerRecord로 돌려준다."""
        ...


class CodexAnswerer:
    """shortcut: Codex CLI로 질문만 보내는 임시 응답기. 문서 검색을 하지 않으므로
    cited_ids·retrieved_ids는 항상 None이다. 실제 Q&A 파이프라인이 완성되면 그 어댑터로 바꾼다.
    """

    def __init__(self, model: str | None = None, call: Callable[..., CodexResult] = run_codex):
        """model은 Codex에 넘길 모델명(None이면 Codex 기본값), call은 테스트용 호출 함수다."""
        self.name = f"codex-cli ({model})" if model else "codex-cli"
        self._model = model
        self._call = call

    def answer(self, case: TestCase) -> AnswerRecord:
        """Codex에 질문을 보내고 답변·지연·토큰을 기록한다. Codex를 실행한다(사용량 소모)."""
        try:
            result = self._call(ANSWER_PROMPT.format(question=case.question), model=self._model)
        except CodexError as exc:
            return AnswerRecord(case_id=case.id, error=str(exc))
        return AnswerRecord(
            case_id=case.id,
            answer_text=result.text,
            latency_sec=result.latency_sec,
            tokens=result.tokens,
        )
