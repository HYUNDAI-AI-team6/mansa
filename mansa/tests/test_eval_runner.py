import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from features.dashboard.evaluation import storage
from features.dashboard.evaluation.models import AnswerRecord, EvalProgress, EvalReport, Judgement
from features.dashboard.evaluation.runner import rescore, run_evaluation
from features.dashboard.evaluation.testset import TestSetError

CASES = [
    {"id": "T1", "question": "갭", "workflow": "L2",
     "expected_numbers": ["0.5 mm"], "expected_sources": ["d:1"]},
    {"id": "T2", "question": "하중", "workflow": "L3",
     "expected_numbers": ["1000 kg"], "expected_sources": []},
    {"id": "T3", "question": "속도", "workflow": "L3",
     "expected_numbers": ["105 m/min"], "expected_sources": []},
]


class FakeAnswerer:
    """T2는 실패하고 나머지는 정답을 내는 응답기."""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def answer(self, case):
        self.calls += 1
        if case.id == "T2":
            return AnswerRecord(case.id, error="timeout")
        text = {"T1": "0.5 mm", "T3": "105 m/min"}[case.id]
        return AnswerRecord(case.id, text, latency_sec=1.0, tokens=10)


class FakeJudge:
    name = "fake judge"

    def judge(self, case, record):
        return Judgement(True, "ok")


def fixed_clock():
    return datetime(2026, 10, 27, 10, 0, 0)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)
        self.testset = self.dir / "set.json"
        self.testset.write_text(json.dumps({"title": "t", "cases": CASES}), encoding="utf-8")

    def _run(self, answerer):
        return list(run_evaluation(answerer, FakeJudge(), self.testset, self.dir, fixed_clock))

    def test_full_run_continues_after_failure(self):
        events = self._run(FakeAnswerer())
        report = events[-1]
        self.assertIsInstance(report, EvalReport)
        answer_steps = [
            e.done for e in events if isinstance(e, EvalProgress) and e.stage == "answer"
        ]
        self.assertEqual(answer_steps, [0, 1, 2, 3])
        self.assertAlmostEqual(report.metrics["수치 정확도"], 200 / 3)
        self.assertIsNone(report.metrics["검색 적중률"])
        self.assertEqual(report.failures, [])
        self.assertEqual([(e.case_id, e.stage) for e in report.llm_errors], [("T2", "답변")])
        self.assertEqual(report.latency["기술 Q&A 평균 지연"], 1.0)
        self.assertEqual(report.finished_at, "2026-10-27T10:00:00")
        names = sorted(p.name for p in self.dir.glob("20261027-100000_*"))
        self.assertEqual(names, ["20261027-100000_answers.json", "20261027-100000_result.csv",
                                 "20261027-100000_result.json"])
        self.assertEqual(storage.load_latest(self.dir), report)

    def test_bad_testset_stops_before_answering(self):
        self.testset.write_text(json.dumps({"cases": [{"id": "x"}]}), encoding="utf-8")
        answerer = FakeAnswerer()
        with self.assertRaises(TestSetError):
            self._run(answerer)
        self.assertEqual(answerer.calls, 0)

    def test_rescore_does_not_call_answerer(self):
        first = self._run(FakeAnswerer())[-1]
        answers = self.dir / first.answers_file
        report = list(rescore(answers, FakeJudge(), self.testset, self.dir, fixed_clock))[-1]
        self.assertEqual(report.metrics, first.metrics)
        self.assertEqual(report.run_id, "20261027-100000-2")
        self.assertEqual(report.answers_file, answers.name)


if __name__ == "__main__":
    unittest.main()
