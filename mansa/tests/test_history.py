import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.schemas import Answer, AnswerDraft, AnswerSection, Intent, ScoredChunk
from features.history.service import HistoryService
from features.history.store import MemoryHistoryStore
from features.qa.service import QAService


def answer(text="답변"):
    """절차 칸에 text만 들어 있는 답변."""
    return Answer(AnswerSection(text), AnswerSection(), AnswerSection(), AnswerSection())


def ticking_clock():
    """부를 때마다 1분씩 늘어나는 가짜 시각 함수."""
    start = datetime(2026, 10, 28, 9, 0)
    count = iter(range(10_000))
    return lambda: start + timedelta(minutes=next(count))


class HistoryServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = HistoryService(MemoryHistoryStore(), now=ticking_clock())

    def test_new_conversation_uses_given_title(self):
        cid = self.service.save(1, None, "메인 로프 교체 기준은?", "메인 로프 교체", answer())
        conversation = self.service.get_conversation(1, cid)
        self.assertEqual(conversation.title, "메인 로프 교체")
        self.assertEqual([t.question for t in conversation.turns], ["메인 로프 교체 기준은?"])

    def test_title_falls_back_to_question(self):
        cid = self.service.save(1, None, "  권상기   브레이크 갭 " + "가" * 40, None, answer())
        title = self.service.get_conversation(1, cid).title
        self.assertTrue(title.startswith("권상기 브레이크 갭"))
        self.assertEqual(len(title), 31)  # 30자 + 말줄임표

    def test_continue_same_conversation(self):
        cid = self.service.save(1, None, "첫 질문", "제목", answer("A1"))
        self.assertEqual(self.service.save(1, cid, "둘째 질문", None, answer("A2")), cid)
        turns = self.service.get_conversation(1, cid).turns
        self.assertEqual([t.question for t in turns], ["첫 질문", "둘째 질문"])
        self.assertEqual(turns[1].answer.procedure.text, "A2")  # 저장한 답변 그대로

    def test_other_member_cannot_read_or_write(self):
        cid = self.service.save(1, None, "질문", "제목", answer())
        with self.assertRaises(LookupError):
            self.service.get_conversation(2, cid)
        with self.assertRaises(LookupError):
            self.service.save(2, cid, "끼어들기", None, answer())
        self.assertEqual(len(self.service.get_conversation(1, cid).turns), 1)  # 남의 질문은 안 들어감

    def test_missing_conversation(self):
        with self.assertRaises(LookupError):
            self.service.get_conversation(1, 999)
        with self.assertRaises(LookupError):
            self.service.save(1, 999, "질문", None, answer())

    def test_list_recent_first_with_limit_and_counts(self):
        a = self.service.save(1, None, "a1", "A", answer())
        self.service.save(1, None, "b1", "B", answer())
        c = self.service.save(1, None, "c1", "C", answer())
        self.service.save(1, a, "a2", None, answer())  # a에 이어 물어서 a가 가장 최근이 된다
        self.service.save(2, None, "x", "남의 대화", answer())
        summaries = self.service.list_conversations(1, 2)
        self.assertEqual([s.id for s in summaries], [a, c])
        self.assertEqual(summaries[0].question_count, 2)
        self.assertEqual(summaries[0].tags, [])

    def test_list_empty_or_zero_limit(self):
        self.assertEqual(self.service.list_conversations(1, 3), [])
        self.service.save(1, None, "질문", "제목", answer())
        self.assertEqual(self.service.list_conversations(1, 0), [])

    def test_returned_conversation_is_a_copy(self):
        cid = self.service.save(1, None, "질문", "제목", answer())
        self.service.get_conversation(1, cid).turns.clear()
        self.assertEqual(len(self.service.get_conversation(1, cid).turns), 1)


class QAServiceHistoryTest(unittest.TestCase):
    """QAService의 History 자리에 진짜 HistoryService를 넣고 나머지는 가짜로 채운다 (LLM·DB 없음)."""

    def setUp(self):
        intent = Intent(intent="procedure", title="메인 로프 점검")
        chunk = ScoredChunk(chunk_id="c1", text="본문", score=0.9, doc_type="tech")
        self.history = HistoryService(MemoryHistoryStore(), now=ticking_clock())
        self.qa = QAService(
            analyzer=SimpleNamespace(analyze=lambda q, cid, first: intent, validate_ids=lambda i: i),
            clarify_policy=SimpleNamespace(needs_clarification=lambda i: False),
            retriever=SimpleNamespace(search_manual=lambda q, i: [chunk], search_safety=lambda q, i: []),
            generator=SimpleNamespace(generate=lambda q, e: AnswerDraft(), verify_sources=lambda d, e, q: d),
            history=self.history,
        )

    def test_answer_is_saved_and_conversation_continues(self):
        first = self.qa.answer("메인 로프 점검 방법", None, 7)
        second = self.qa.answer("점검 주기는?", first.conversation_id, 7)
        self.assertEqual(first.conversation_id, second.conversation_id)
        conversation = self.history.get_conversation(7, first.conversation_id)
        self.assertEqual(conversation.title, "메인 로프 점검")
        self.assertEqual([t.question for t in conversation.turns], ["메인 로프 점검 방법", "점검 주기는?"])


if __name__ == "__main__":
    unittest.main()