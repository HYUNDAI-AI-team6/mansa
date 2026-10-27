import unittest

from core.schemas import AnswerDraft, AnswerSection, Evidence, Intent, ScoredChunk
from features.qa.answer_generator import SAFETY_NOTICE, attach_notice
from features.qa.answer_guard import build_no_answer, is_sufficient
from features.qa.retriever import merge_evidence


def chunk(chunk_id: str, score: float, doc_type: str = "tech") -> ScoredChunk:
    return ScoredChunk(chunk_id=chunk_id, text=f"text {chunk_id}", score=score, doc_type=doc_type)


class MergeEvidenceTest(unittest.TestCase):
    def test_sorts_by_score_and_keeps_top_n(self):
        manual = [chunk(f"m{i}", i / 10) for i in range(6)]
        safety = [chunk(f"s{i}", i / 10 + 0.05, "secure") for i in range(6)]

        ids = [c.chunk_id for c in merge_evidence(manual, safety).chunks]

        self.assertEqual(ids, ["s5", "m5", "s4", "m4", "s3", "m3", "s2", "m2"])

    def test_duplicate_chunk_keeps_highest_score(self):
        merged = merge_evidence([chunk("a", 0.4)], [chunk("a", 0.9), chunk("b", 0.5)])

        self.assertEqual([(c.chunk_id, c.score) for c in merged.chunks], [("a", 0.9), ("b", 0.5)])

    def test_tie_keeps_manual_first_and_inputs_unchanged(self):
        manual, safety = [chunk("m", 0.5)], [chunk("s", 0.5)]

        merged = merge_evidence(manual, safety)

        self.assertEqual([c.chunk_id for c in merged.chunks], ["m", "s"])
        self.assertEqual(manual, [chunk("m", 0.5)])

    def test_empty_inputs(self):
        self.assertEqual(merge_evidence([], []).chunks, [])


class IsSufficientTest(unittest.TestCase):
    def test_threshold_boundary(self):
        intent = Intent(intent="spec")

        self.assertTrue(is_sufficient(intent, Evidence([chunk("a", 0.3)]), min_score=0.3))
        self.assertFalse(is_sufficient(intent, Evidence([chunk("a", 0.29)]), min_score=0.3))

    def test_empty_evidence_is_insufficient(self):
        self.assertFalse(is_sufficient(Intent(intent="spec"), Evidence()))

    def test_out_of_scope_is_insufficient_even_with_good_evidence(self):
        self.assertFalse(is_sufficient(Intent(intent="out_of_scope"), Evidence([chunk("a", 1.0)])))


class BuildNoAnswerTest(unittest.TestCase):
    def test_each_reason_has_distinct_message_with_contact(self):
        reasons = ["insufficient_evidence", "out_of_scope", "llm_failure"]

        results = [build_no_answer(None, r) for r in reasons]

        self.assertEqual([r.reason for r in results], reasons)
        self.assertEqual(len({r.message for r in results}), 3)
        self.assertTrue(all("안전관리팀" in r.message for r in results))
        self.assertIn("문서에서 찾을 수 없습니다", results[0].message)

    def test_unknown_reason_raises(self):
        with self.assertRaises(KeyError):
            build_no_answer(None, "weather")


class AttachNoticeTest(unittest.TestCase):
    def test_notice_goes_first_in_safety_section(self):
        draft = AnswerDraft(safety=AnswerSection("붐 아래 접근 금지", ["c1"]))

        answer = attach_notice(draft)

        self.assertTrue(answer.safety.text.startswith(SAFETY_NOTICE))
        self.assertTrue(answer.safety.text.endswith("붐 아래 접근 금지"))
        self.assertEqual(answer.safety.source_ids, ["c1"])
        self.assertEqual(draft.safety.text, "붐 아래 접근 금지")

    def test_notice_added_even_when_safety_empty(self):
        self.assertEqual(attach_notice(AnswerDraft()).safety.text, SAFETY_NOTICE)


if __name__ == "__main__":
    unittest.main()
