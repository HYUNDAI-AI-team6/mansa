import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from features.dashboard.evaluation import storage
from features.dashboard.evaluation.models import AnswerRecord, EvalReport, Failure, LlmError


def make_report(run_id="20261027-100000"):
    """저장 테스트용 결과 하나."""
    return EvalReport(
        run_id=run_id,
        testset_title="기술 Q&A 테스트셋",
        answerer="fake",
        total=2,
        finished_at="2026-10-27T10:05:00",
        metrics={"수치 정확도": 50.0, "검색 적중률": None},
        failures=[Failure("T01", "브레이크 갭", "L2", "생성", "0.5 mm → 없음")],
        latency={"기술 Q&A 평균 지연": 2.25, "기술 Q&A 평균 토큰": 1234.0},
        llm_errors=[LlmError("T2", "정격하중", "채점", "codex timed out after 180s")],
    )


class StorageTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)

    def test_eval_root_is_repo_root(self):
        self.assertEqual(storage.EVAL_ROOT.parent, Path(__file__).resolve().parents[2])

    def test_answers_roundtrip(self):
        records = [
            AnswerRecord("T01", "답", latency_sec=1.0, tokens=10),
            AnswerRecord("T02", error="boom", cited_ids=[]),
        ]
        path = storage.save_answers("r1", "set", "fake", "t0", records, save_dir=self.dir)
        meta, loaded = storage.load_answers(path)
        self.assertEqual(loaded, records)
        self.assertEqual(meta["answerer"], "fake")
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_load_answers_rejects_bad_file(self):
        path = self.dir / "bad_answers.json"
        path.write_text('{"run_id": "x"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            storage.load_answers(path)

    def test_new_run_id_avoids_collision(self):
        now = datetime(2026, 10, 27, 10, 0, 0)
        first = storage.new_run_id(self.dir, now)
        (self.dir / f"{first}_answers.json").write_text("{}", encoding="utf-8")
        self.assertEqual(storage.new_run_id(self.dir, now), f"{first}-2")

    def test_no_result(self):
        self.assertIsNone(storage.load_latest(self.dir))
        self.assertIsNone(storage.latest_csv(self.dir))

    def test_latest_of_many_and_csv(self):
        storage.save_report(make_report("20261027-090000"), self.dir)
        storage.save_report(make_report("20261027-100000"), self.dir)
        (self.dir / "20261027-110000_result.json").write_text("{bad", encoding="utf-8")
        latest = storage.load_latest(self.dir)
        self.assertEqual(latest, make_report("20261027-100000"))
        csv_path = storage.latest_csv(self.dir)
        raw = csv_path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8-sig")
        self.assertIn("지표,수치 정확도,50.0%", text)
        self.assertIn("지표,검색 적중률,값 없음", text)
        self.assertIn("지연·토큰,기술 Q&A 평균 지연,2.2초", text)
        self.assertNotIn("고객센터", text)
        self.assertIn("실패 사례,브레이크 갭,L2 · 생성 · 0.5 mm → 없음", text)
        self.assertIn("LLM 오류,정격하중,채점 · codex timed out after 180s", text)

    def test_latest_picks_later_run_in_same_second(self):
        storage.save_report(make_report("20261027-100000"), self.dir)
        storage.save_report(make_report("20261027-100000-2"), self.dir)
        self.assertEqual(storage.load_latest(self.dir).run_id, "20261027-100000-2")
        self.assertEqual(storage.latest_csv(self.dir).name, "20261027-100000-2_result.csv")
        storage.save_report(make_report("20261027-100001"), self.dir)
        self.assertEqual(storage.load_latest(self.dir).run_id, "20261027-100001")

    def test_reads_old_result_without_llm_errors(self):
        path = self.dir / "20261027-090000_result.json"
        storage.save_report(make_report("20261027-090000"), self.dir)
        raw = json.loads(path.read_text(encoding="utf-8"))
        del raw["llm_errors"]
        path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(storage.load_latest(self.dir).llm_errors, [])


if __name__ == "__main__":
    unittest.main()
