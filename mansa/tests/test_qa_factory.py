import unittest
from types import SimpleNamespace

from core.schemas import Answer, Clarify, NoAnswer, ScoredChunk
from features.qa.answer_generator import SAFETY_NOTICE
from features.qa.clarify_policy import PART_QUESTION
from features.qa.factory import build_qa_service
from features.retrieval.retriever import MANUAL_COLLECTION, SAFETY_COLLECTION

CORPUS = {
    MANUAL_COLLECTION: [
        {"id": "m1", "text": "메인 로프 점검 시 소선 단선율이 10% 를 넘으면 교체한다.", "metadata": {}},
    ],
    SAFETY_COLLECTION: [
        {"id": "s1", "text": "카 상부 작업 시 추락 방지 조치를 한다.", "metadata": {}},
    ],
}


class FakeChroma:
    """search_chunks·get_chunks 대신 쓰는 가짜. 컬렉션마다 정해 둔 청크를 돌려주고 호출을 기록한다."""

    def __init__(self):
        self.searches = []
        self.reads = []

    def search(self, query, doc_type, collection, top_k=5, where=None):
        self.searches.append((query, collection))
        return [{**chunk, "distance": 0.4} for chunk in CORPUS[collection]]

    def get(self, doc_type, collection, limit=10, offset=0, where=None):
        self.reads.append(collection)
        return CORPUS[collection][offset:offset + limit]


def fake_complete(intent):
    """질문 분석에는 intent를, 답변 생성에는 정해 둔 4개 영역을 돌려주는 가짜 LLM."""

    def complete(workflow, prompt, schema, history=None):
        if "intent" in schema.model_fields:
            return {"model_ids": [], "parts": [], "task": None, "values": [], "title": "메인 로프 점검", **intent}
        return {
            "procedure": {"text": "소선 단선율을 확인한다.", "source_ids": ["m1"]},
            "spec": {"text": "단선율 10% 초과 시 교체", "source_ids": ["m1"]},
            "safety": {"text": "추락 방지 조치를 한다.", "source_ids": ["s1"]},
            "diff": {"text": "", "source_ids": []},
        }

    return complete


class BuildQaServiceTest(unittest.TestCase):
    def build(self, **intent):
        self.chroma = FakeChroma()
        return build_qa_service(self.chroma.search, self.chroma.get, fake_complete(intent))

    def test_question_flows_to_answer(self):
        result = self.build(intent="procedure", task="메인 로프 점검").answer("메인 로프 점검 방법", None, 1)
        self.assertIsInstance(result, Answer)
        self.assertEqual(result.spec.text, "단선율 10% 초과 시 교체")
        self.assertTrue(result.safety.text.startswith(SAFETY_NOTICE))
        self.assertEqual(result.conversation_id, 1)

    def test_corpus_is_read_once_when_built(self):
        qa = self.build(intent="procedure", task="메인 로프 점검")
        qa.answer("메인 로프 점검 방법", None, 1)
        qa.answer("다시 묻기", None, 1)
        self.assertEqual(self.chroma.reads, [MANUAL_COLLECTION, SAFETY_COLLECTION])

    def test_safety_query_has_relation_terms(self):
        self.build(intent="procedure", task="메인 로프 점검").answer("메인 로프 점검 방법", None, 1)
        safety_query = next(q for q, c in self.chroma.searches if c == SAFETY_COLLECTION)
        for term in ("카 상부", "기계실", "추락", "끼임"):  # task_relations.json의 메인 로프 점검
            self.assertIn(term, safety_query)

    def test_vague_question_is_clarified(self):
        result = self.build(intent="procedure").answer("점검 방법 알려줘", None, 1)
        self.assertIsInstance(result, Clarify)
        self.assertEqual(result.question, PART_QUESTION)
        self.assertEqual(self.chroma.searches, [])

    def test_out_of_scope_is_no_answer(self):
        result = self.build(intent="out_of_scope").answer("오늘 날씨 어때?", None, 1)
        self.assertIsInstance(result, NoAnswer)
        self.assertEqual(result.reason, "out_of_scope")


class InjectedRetrieverTest(unittest.TestCase):
    def test_given_retriever_is_used_instead_of_search(self):
        def chunks(chunk_id, doc_type):
            return lambda question, intent: [ScoredChunk(chunk_id, "본문 10%", 0.9, doc_type)]

        def no_search(*args, **kwargs):
            raise AssertionError("search must not be called")

        retriever = SimpleNamespace(search_manual=chunks("m1", "tech"), search_safety=chunks("s1", "secure"))
        qa = build_qa_service(
            search=no_search,
            complete=fake_complete({"intent": "procedure", "task": "메인 로프 점검"}),
            retriever=retriever,
        )
        result = qa.answer("메인 로프 점검 방법", None, 1)
        self.assertIsInstance(result, Answer)
        self.assertEqual(result.spec.source_ids, ["m1"])


if __name__ == "__main__":
    unittest.main()
