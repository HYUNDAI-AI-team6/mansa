"""평가 대상 응답기. 테스트셋 문항을 받아 AnswerRecord를 돌려준다."""

import time
from collections.abc import Callable, Iterable
from typing import Protocol

import openai
from langchain_core.callbacks import get_usage_metadata_callback

from config import LLM_MODEL
from core.exceptions import LlmError
from core.schemas import Answer, AnswerSection, Clarify, Intent, NoAnswer, ScoredChunk
from features.evaluation.models import AnswerRecord, TestCase
from features.qa.factory import build_qa_service, build_retriever
from features.qa.service import QAService, Retriever
from features.retrieval.retriever import merge_evidence

# 평가 질문의 대화 기록 주인. 평가용 QAService는 메모리 기록만 쓰므로 실제 회원과 섞이지 않는다.
EVAL_MEMBER_ID = 0


class Answerer(Protocol):
    """평가할 Q&A 응답기. 실제 파이프라인이 생기면 이 형태로 어댑터를 추가한다."""

    name: str

    def answer(self, case: TestCase) -> AnswerRecord:
        """문항 하나에 답한다. 호출 실패는 예외 대신 error가 채워진 AnswerRecord로 돌려준다."""
        ...


class RecordingRetriever:
    """검색 결과를 기록하고 그대로 돌려주는 Retriever 래퍼. 문항마다 reset으로 비운다."""

    def __init__(self, inner: Retriever) -> None:
        """실제 검색을 맡을 retriever를 받는다."""
        self._inner = inner
        self.manual: list[ScoredChunk] = []
        self.safety: list[ScoredChunk] = []

    def reset(self) -> None:
        """이전 문항의 검색 기록을 지운다."""
        self.manual, self.safety = [], []

    def search_manual(self, question: str, intent: Intent) -> list[ScoredChunk]:
        """매뉴얼 검색 결과를 기록하고 반환한다."""
        self.manual = self._inner.search_manual(question, intent)
        return self.manual

    def search_safety(self, question: str, intent: Intent) -> list[ScoredChunk]:
        """안전 문서 검색 결과를 기록하고 반환한다."""
        self.safety = self._inner.search_safety(question, intent)
        return self.safety


class QaAnswerer:
    """실제 기술 Q&A 파이프라인(QAService)으로 답하고 근거·지연·토큰을 기록하는 응답기.

    근거는 청크 ID 대신 "파일명#p페이지" 키로 기록한다(문서를 다시 올려도 정답표가 깨지지 않게).
    검색 근거는 답변 생성에 넘긴 근거와 같도록 기록한 검색 결과를 merge_evidence로 다시 합친다.
    """

    def __init__(
        self,
        retriever: Retriever | None = None,
        build: Callable[..., QAService] = build_qa_service,
    ) -> None:
        """retriever·build는 테스트용이다. 기본값은 실제 Chroma 검색과 build_qa_service다.

        분류표 파일을 읽으므로 평가를 실행할 때 만든다. Chroma는 질문할 때 호출한다.
        """
        self.name = f"qa-service ({LLM_MODEL})"
        self._recorder = RecordingRetriever(retriever or build_retriever())
        self._service = build(retriever=self._recorder)

    def answer(self, case: TestCase) -> AnswerRecord:
        """문항 하나를 QAService에 보내고 결과를 AnswerRecord로 바꾼다.

        유료 외부 API(OpenAI 채팅·임베딩)와 Chroma를 호출한다. tokens는 그동안 호출된 채팅 LLM
        사용량 합계이며 임베딩 토큰은 빠진다. 사용량이 기록되지 않으면 None이다.
        LlmError와 문항 하나에 국한될 수 있는 openai 오류, 파이프라인의 llm_failure 답변 불가는
        error가 채워진 AnswerRecord로 돌려준다. 인증·권한·모델 없음 오류와 Chroma 접속 실패 같은
        그 밖의 예외는 모든 문항이 같은 이유로 실패하므로 그대로 올려 보낸다.
        """
        self._recorder.reset()
        started = time.perf_counter()
        try:
            with get_usage_metadata_callback() as usage:
                result = self._service.answer(case.question, None, EVAL_MEMBER_ID)
        except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError):
            raise
        # ContentFilterFinishReasonError는 APIError가 아니라 OpenAIError 하위라 따로 잡는다.
        except (LlmError, openai.APIError, openai.ContentFilterFinishReasonError) as exc:
            return AnswerRecord(case_id=case.id, error=str(exc))
        if isinstance(result, NoAnswer) and result.reason == "llm_failure":
            return AnswerRecord(case_id=case.id, error=f"QA pipeline llm_failure: {result.message}")
        evidence = merge_evidence(self._recorder.manual, self._recorder.safety).chunks
        return AnswerRecord(
            case_id=case.id,
            answer_text=_answer_text(result),
            cited_ids=_cited_keys(result, evidence),
            retrieved_ids=_page_keys(_page_key(c) for c in evidence),
            latency_sec=time.perf_counter() - started,
            tokens=sum(u["total_tokens"] for u in usage.usage_metadata.values()) or None,
        )


def _page_key(chunk: ScoredChunk) -> str:
    """청크의 근거 키 "파일명#p페이지". 페이지가 없는 청크(CSV 등)는 파일명만 쓴다."""
    source = chunk.metadata.get("source") or chunk.chunk_id
    page = chunk.metadata.get("page")
    return source if page is None else f"{source}#p{page}"


def _page_keys(keys: Iterable[str]) -> list[str]:
    """같은 페이지 키를 하나로 합친다. 처음 나온 순서를 유지한다."""
    return list(dict.fromkeys(keys))


def _sections(answer: Answer) -> list[AnswerSection]:
    """답변의 네 영역(절차·사양·안전·기준 차이)을 화면 순서대로 반환한다."""
    return [answer.procedure, answer.spec, answer.safety, answer.diff]


def _answer_text(result: Answer | Clarify | NoAnswer) -> str:
    """채점에 쓸 답변 텍스트. 답변은 글이 있는 영역을 잇고, 되묻기는 질문과 선택지, 답변 불가는 안내문이다."""
    if isinstance(result, Answer):
        return "\n\n".join(s.text for s in _sections(result) if s.text.strip())
    if isinstance(result, Clarify):
        return f"{result.question}\n{', '.join(result.options)}"
    return result.message


def _cited_keys(result: Answer | Clarify | NoAnswer, evidence: list[ScoredChunk]) -> list[str]:
    """답변이 인용한 청크를 페이지 키로 바꾼다. 되묻기·답변 불가는 인용이 없어 빈 목록이다.

    근거에서 찾지 못한 청크 ID는 그대로 둔다(정답과 맞지 않아 과잉 첨부로 드러난다).
    """
    if not isinstance(result, Answer):
        return []
    by_id = {c.chunk_id: _page_key(c) for c in evidence}
    return _page_keys(by_id.get(i, i) for s in _sections(result) for i in s.source_ids)
