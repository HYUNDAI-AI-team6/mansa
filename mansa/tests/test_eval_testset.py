import json
import tempfile
import unittest
from pathlib import Path

from features.evaluation.storage import EVAL_ROOT
from features.evaluation.testset import TestSetError, load_testset

VALID_CASE = {
    "id": "T01",
    "question": "q",
    "workflow": "L2",
    "expected_numbers": ["5.6절"],
    "expected_sources": ["doc:1"],
}


class LoadTestsetTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "set.json"

    def _write(self, cases):
        self.path.write_text(json.dumps({"title": "t", "cases": cases}), encoding="utf-8")

    def test_valid_keeps_order(self):
        self._write([VALID_CASE, {**VALID_CASE, "id": "T02", "workflow": "L3"}])
        testset = load_testset(self.path)
        self.assertEqual([c.id for c in testset.cases], ["T01", "T02"])
        self.assertEqual(testset.cases[1].workflow, "L3")

    def test_missing_field(self):
        case = dict(VALID_CASE)
        del case["expected_sources"]
        self._write([case])
        with self.assertRaisesRegex(TestSetError, "'T01'.*expected_sources"):
            load_testset(self.path)

    def test_bad_workflow(self):
        self._write([{**VALID_CASE, "workflow": "L9"}])
        with self.assertRaisesRegex(TestSetError, "workflow"):
            load_testset(self.path)

    def test_duplicate_id(self):
        self._write([VALID_CASE, VALID_CASE])
        with self.assertRaisesRegex(TestSetError, "duplicate"):
            load_testset(self.path)

    def test_missing_file_and_bad_json(self):
        with self.assertRaises(TestSetError):
            load_testset(self.path)
        self.path.write_text("{bad", encoding="utf-8")
        with self.assertRaises(TestSetError):
            load_testset(self.path)

    def test_bundled_testset_is_valid(self):
        testset = load_testset(EVAL_ROOT / "testsets" / "tech_qa.json")
        self.assertGreaterEqual(len(testset.cases), 5)
        self.assertEqual({c.workflow for c in testset.cases}, {"L2", "L3"})


if __name__ == "__main__":
    unittest.main()
