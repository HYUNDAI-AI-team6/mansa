import unittest

import httpx
import openai
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from core.exceptions import LlmError
from core.schemas import AnswerDraft, AnswerSection, Clarify, Intent, ScoredChunk
from features.evaluation.answerer import QaAnswerer
from features.evaluation.models import TestCase
from features.qa.service import QAService

CASE = TestCase(id="T01", question="피트 조도 기준은?", workflow="L2")


def _api_error(cls, status):
    """openai 상태 오류 예외를 만든다. 실제 응답 없이 테스트에서만 쓴다."""
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"))
    return cls("error", response=response, body=None)


def _chunk(chunk_id, page, doc_type="secure", source="안전기준.pdf", score=0.9):
    return ScoredChunk(chunk_id, f"본문 {chunk_id}", score, doc_type, {"source": source, "page": page})


MANUAL = [_chunk("24:p6:0", 6, "tech", "사양서.pdf"), _chunk("24:p6:1", 6, "tech", "사양서.pdf")]
SAFETY = [_chunk("17:p9:0", 9), _chunk("17:p9:1", 9), _chunk("17:p12:0", 12)]


class FakeRetriever:
    def __init__(self, manual=MANUAL, safety=SAFETY):
        self.manual, self.safety = manual, safety

    def search_manual(self, question, intent):
        return list(self.manual)

    def search_safety(self, question, intent):
        return list(self.safety)


class FakeAnalyzer:
    def __init__(self, intent="safety"):
        self.intent = intent

    def analyze(self, question, conversation_id, is_first):
        return Intent(self.intent, task="피트 점검")

    def validate_ids(self, intent):
        return intent


class FakeClarify:
    def __init__(self, ask=False):
        self.ask = ask

    def needs_clarification(self, intent):
        return self.ask

    def build_options(self, intent):
        return Clarify("어떤 설비 모델인가요?", ["ELVRO 3000", "HYDRO 501"])


class FakeGenerator:
    """정해 둔 초안을 돌려준다. model이 있으면 생성마다 한 번 호출해 토큰 사용량을 남긴다."""

    def __init__(self, draft=None, error=None, model=None, rejects=0):
        self.draft, self.error, self.model, self.rejects = draft, error, model, rejects

    def generate(self, question, evidence):
        if self.model is not None:
            self.model.invoke("q")
        if self.error is not None:
            raise self.error
        return self.draft

    def verify_sources(self, draft, evidence):
        """처음 rejects번은 근거 검사 실패로 보고 재생성을 일으킨다."""
        if self.rejects:
            self.rejects -= 1
            return None
        return draft


class FakeHistory:
    def save(self, member_id, conversation_id, question, title, answer):
        return 1


DRAFT = AnswerDraft(
    spec=AnswerSection("하중 750 kg", ["24:p6:1"]),
    safety=AnswerSection("50 lx 이상", ["17:p9:0", "17:p9:1", "17:p12:0"]),
)


def _answerer(analyzer=None, clarify=None, retriever=None, generator=None):
    """가짜 단계로 만든 QAService를 쓰는 QaAnswerer."""

    def build(retriever):
        return QAService(
            analyzer or FakeAnalyzer(),
            clarify or FakeClarify(),
            retriever,
            generator or FakeGenerator(DRAFT),
            FakeHistory(),
        )

    return QaAnswerer(retriever=retriever or FakeRetriever(), build=build)


def _usage_model(*totals):
    """호출마다 정해 둔 토큰 사용량을 남기는 가짜 채팅 모델."""
    messages = [
        AIMessage(
            "ok",
            usage_metadata={"input_tokens": t - 1, "output_tokens": 1, "total_tokens": t},
            response_metadata={"model_name": "fake"},
        )
        for t in totals
    ]
    return GenericFakeChatModel(messages=iter(messages))


class QaAnswererTest(unittest.TestCase):
    def test_answer_records_page_keys(self):
        record = _answerer().answer(CASE)
        self.assertIsNone(record.error)
        self.assertEqual(record.answer_text.split("\n\n")[0], "하중 750 kg")
        self.assertIn("50 lx 이상", record.answer_text)
        self.assertEqual(record.cited_ids, ["사양서.pdf#p6", "안전기준.pdf#p9", "안전기준.pdf#p12"])
        # merge_evidence가 매뉴얼·안전 순위를 번갈아 합친 순서
        self.assertEqual(record.retrieved_ids, ["사양서.pdf#p6", "안전기준.pdf#p9", "안전기준.pdf#p12"])
        self.assertGreaterEqual(record.latency_sec, 0)
        self.assertIsNone(record.tokens)

    def test_tokens_sum_regenerations_per_case(self):
        model = _usage_model(120, 80, 50)
        answerer = _answerer(generator=FakeGenerator(DRAFT, model=model, rejects=1))
        self.assertEqual(answerer.answer(CASE).tokens, 200)  # 생성 + 재생성
        self.assertEqual(answerer.answer(CASE).tokens, 50)

    def test_chunk_without_page_uses_source(self):
        retriever = FakeRetriever(manual=[ScoredChunk("c1", "행", 0.9, "tech", {"source": "a.csv"})], safety=[])
        draft = AnswerDraft(spec=AnswerSection("값", ["c1"]))
        record = _answerer(retriever=retriever, generator=FakeGenerator(draft)).answer(CASE)
        self.assertEqual(record.cited_ids, ["a.csv"])

    def test_clarify_has_no_sources(self):
        retriever = FakeRetriever()
        record = _answerer(clarify=FakeClarify(ask=True), retriever=retriever).answer(CASE)
        self.assertIsNone(record.error)
        self.assertIn("어떤 설비 모델인가요?", record.answer_text)
        self.assertEqual((record.cited_ids, record.retrieved_ids), ([], []))

    def test_insufficient_evidence_keeps_retrieved(self):
        weak = FakeRetriever(manual=[], safety=[_chunk("17:p9:0", 9, score=0.0)])
        record = _answerer(retriever=weak).answer(CASE)
        self.assertIsNone(record.error)
        self.assertEqual(record.cited_ids, [])
        self.assertEqual(record.retrieved_ids, ["안전기준.pdf#p9"])

    def test_out_of_scope_has_no_sources(self):
        record = _answerer(analyzer=FakeAnalyzer("out_of_scope")).answer(CASE)
        self.assertEqual((record.cited_ids, record.retrieved_ids), ([], []))

    def test_retrieval_record_resets_per_case(self):
        analyzer = FakeAnalyzer()
        answerer = _answerer(analyzer=analyzer)
        self.assertNotEqual(answerer.answer(CASE).retrieved_ids, [])
        analyzer.intent = "out_of_scope"  # 다음 문항은 검색 전에 끝난다
        self.assertEqual(answerer.answer(CASE).retrieved_ids, [])

    def test_pipeline_llm_failure_is_error(self):
        record = _answerer(generator=FakeGenerator(error=LlmError("L2 LLM failed"))).answer(CASE)
        self.assertIn("llm_failure", record.error)
        self.assertIsNone(record.cited_ids)
        self.assertIsNone(record.retrieved_ids)

    def test_api_failure_becomes_error_record(self):
        for exc in (_api_error(openai.RateLimitError, 429), openai.ContentFilterFinishReasonError()):
            retriever = FakeRetriever()
            retriever.search_manual = lambda question, intent, exc=exc: (_ for _ in ()).throw(exc)
            record = _answerer(retriever=retriever).answer(CASE)
            self.assertEqual(record.error, str(exc))
            self.assertIsNone(record.latency_sec)

    def test_config_error_propagates(self):
        retriever = FakeRetriever()

        def fail(question, intent):
            raise _api_error(openai.AuthenticationError, 401)

        retriever.search_manual = fail
        with self.assertRaises(openai.AuthenticationError):
            _answerer(retriever=retriever).answer(CASE)


if __name__ == "__main__":
    unittest.main()
