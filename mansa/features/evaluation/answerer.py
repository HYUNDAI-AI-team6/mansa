"""평가 대상 응답기. 테스트셋 문항을 받아 AnswerRecord를 돌려준다."""

import time
from collections.abc import Callable
from typing import Protocol

import openai
from pydantic import BaseModel

from config import LLM_MODEL
from core.exceptions import LlmError
from core.llm import complete
from features.evaluation.models import AnswerRecord, TestCase

ANSWER_PROMPT = """너는 승강기 유지보수 기술 문서를 바탕으로 답하는 Q&A 도우미다.
아래 질문에 한국어로 바로 답해라.
수치에는 반드시 단위를 붙이고, 모르면 모른다고 답해라.

질문: {question}"""


class AnswerOutput(BaseModel):
    """응답기 LLM의 응답 형식."""

    answer: str


class Answerer(Protocol):
    """평가할 Q&A 응답기. 실제 파이프라인이 생기면 이 형태로 어댑터를 추가한다."""

    name: str

    def answer(self, case: TestCase) -> AnswerRecord:
        """문항 하나에 답한다. 호출 실패는 예외 대신 error가 채워진 AnswerRecord로 돌려준다."""
        ...


class LlmAnswerer:
    """shortcut: core.llm.complete로 질문만 보내는 임시 응답기. 문서 검색을 하지 않으므로
    cited_ids·retrieved_ids는 항상 None이다. 실제 Q&A 파이프라인이 완성되면 그 어댑터로 바꾼다.
    """

    def __init__(self, call: Callable[..., dict] = complete):
        """call은 테스트용 호출 함수다(기본값 core.llm.complete)."""
        self.name = f"llm ({LLM_MODEL})"
        self._call = call

    def answer(self, case: TestCase) -> AnswerRecord:
        """LLM에 질문을 보내고 답변·지연을 기록한다. 유료 외부 API(OpenAI)를 호출한다.

        LlmError와 문항 하나에 국한될 수 있는 openai 오류는 error가 채워진 AnswerRecord로 돌려준다.
        인증·권한·모델 없음 오류는 모든 문항이 같은 이유로 실패하므로 그대로 올려 보낸다.
        지연 시간에는 complete의 재시도 시간이 포함된다.
        """
        prompt = ANSWER_PROMPT.format(question=case.question)
        started = time.perf_counter()
        try:
            result = self._call(case.workflow, prompt, AnswerOutput)
        except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError):
            raise
        # ContentFilterFinishReasonError는 APIError가 아니라 OpenAIError 하위라 따로 잡는다.
        except (LlmError, openai.APIError, openai.ContentFilterFinishReasonError) as exc:
            return AnswerRecord(case_id=case.id, error=str(exc))
        # shortcut: complete()가 토큰 사용량을 돌려주지 않아 tokens=None("값 없음")이다.
        # 실제 Q&A 파이프라인 어댑터를 붙일 때 토큰 측정을 추가한다.
        return AnswerRecord(
            case_id=case.id,
            answer_text=result["answer"],
            latency_sec=time.perf_counter() - started,
            tokens=None,
        )
