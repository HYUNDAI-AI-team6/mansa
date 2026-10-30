from dataclasses import replace
from typing import Protocol

from core.exceptions import LlmError
from core.schemas import (
    Answer,
    AnswerDraft,
    Clarify,
    Evidence,
    Intent,
    NoAnswer,
    ScoredChunk,
)
from features.qa.answer_generator import attach_notice
from features.qa.answer_guard import build_no_answer, is_sufficient
from features.retrieval.retriever import merge_evidence

# 첫 생성이 근거 검사에 실패하면 MAX_REGENERATIONS(기본 2)번 다시 생성한다. 환경변수로 바꿀 수 있다.
from config import MAX_REGENERATIONS


class Analyzer(Protocol):
    """질문을 읽어 Intent로 정리하는 단계(QuestionAnalyzer)."""

    def analyze(self, question: str, conversation_id: int | None, is_first: bool) -> Intent:
        """질문을 분석한다. LLM 호출 실패는 LlmError로 알린다."""
        ...

    def validate_ids(self, intent: Intent) -> Intent:
        """실제 등록되지 않은 모델·부위 값을 지운 Intent를 반환한다."""
        ...


class ClarifyPolicy(Protocol):
    """모델·부위가 하나로 정해졌는지 확인하고 되묻는 단계."""

    def needs_clarification(self, intent: Intent) -> bool:
        """모델·부위가 비었거나 후보가 둘 이상이면 True다."""
        ...

    def build_options(self, intent: Intent) -> Clarify:
        """실제 후보로 되묻기 선택지를 만든다."""
        ...


class Retriever(Protocol):
    """매뉴얼·안전 문서에서 근거 청크를 찾는 단계."""

    def search_manual(self, question: str, intent: Intent) -> list[ScoredChunk]:
        """매뉴얼·사양서 청크를 검색한다."""
        ...

    def search_safety(self, question: str, intent: Intent) -> list[ScoredChunk]:
        """안전 문서 청크를 검색한다."""
        ...


class Generator(Protocol):
    """근거로 답변을 쓰고 근거·수치를 검사하는 단계(AnswerGenerator)."""

    def generate(self, question: str, evidence: Evidence) -> AnswerDraft:
        """근거만 사용해 4개 영역 답변을 만든다. LLM 호출 실패는 LlmError로 알린다."""
        ...

    def verify_sources(self, draft: AnswerDraft, evidence: Evidence, question: str = "") -> AnswerDraft | None:
        """근거 ID와 수치가 원문과 맞으면 답변을, 맞지 않으면 None을 반환한다."""
        ...


class History(Protocol):
    """대화와 질문·답변을 저장하는 단계(HistoryService)."""

    def save(
        self,
        member_id: int,
        conversation_id: int | None,
        question: str,
        title: str | None,
        answer: Answer,
    ) -> int:
        """답변을 저장하고 대화 ID를 반환한다. 대화 ID가 없으면 새 대화를 만든다."""
        ...


class QAService:
    """기술 질문 하나를 처리하는 순서를 조율한다. 각 단계는 생성자로 받은 객체가 맡는다."""

    def __init__(
        self,
        analyzer: Analyzer,
        clarify_policy: ClarifyPolicy,
        retriever: Retriever,
        generator: Generator,
        history: History,
    ) -> None:
        """질문 처리에 쓸 단계 객체를 받아 둔다. 테스트에서는 가짜 객체로 바꿔 넣는다."""
        self._analyzer = analyzer
        self._clarify_policy = clarify_policy
        self._retriever = retriever
        self._generator = generator
        self._history = history

    def answer(
        self, question: str, conversation_id: int | None, member_id: int
    ) -> Answer | Clarify | NoAnswer:
        """질문을 분석·검색·생성·검사해 답변, 되묻기, 답변 불가 중 하나를 반환한다.

        범위 밖이거나 근거가 부족하면 LLM 답변 생성 없이 NoAnswer를 반환한다.
        LLM 호출이 LlmError로 실패하거나 재생성 후에도 근거 검사를 통과하지 못하면
        reason이 "llm_failure"인 NoAnswer를 반환한다.
        Answer일 때만 대화 기록에 저장하며(외부 DB 쓰기) 저장된 대화 ID를 담아 반환한다.
        LlmError 외의 예외(검색·DB 실패 등)는 호출자에게 그대로 전달한다.
        """
        try:
            intent = self._analyzer.analyze(question, conversation_id, conversation_id is None)
        except LlmError:
            return build_no_answer(None, "llm_failure")
        intent = self._analyzer.validate_ids(intent)

        if intent.intent == "out_of_scope":
            return build_no_answer(intent, "out_of_scope")
        if self._clarify_policy.needs_clarification(intent):
            return self._clarify_policy.build_options(intent)

        evidence = merge_evidence(
            self._retriever.search_manual(question, intent),
            self._retriever.search_safety(question, intent),
        )
        if not is_sufficient(intent, evidence):
            return build_no_answer(intent, "insufficient_evidence")

        draft = self._generate_verified(question, evidence)
        if draft is None:
            return build_no_answer(intent, "llm_failure")

        answer = attach_notice(draft)
        saved_id = self._history.save(member_id, conversation_id, question, intent.title, answer)
        return replace(answer, conversation_id=saved_id)

    def _generate_verified(self, question: str, evidence: Evidence) -> AnswerDraft | None:
        """근거 검사를 통과한 답변 초안을 반환한다.

        검사에 실패하면 MAX_REGENERATIONS번까지 다시 생성하고, 끝내 실패하거나 LLM 호출이
        LlmError로 실패하면 None을 반환한다.
        """
        for _ in range(1 + MAX_REGENERATIONS):
            try:
                draft = self._generator.generate(question, evidence)
            except LlmError:
                return None
            verified = self._generator.verify_sources(draft, evidence, question)
            if verified is not None:
                return verified
        return None
