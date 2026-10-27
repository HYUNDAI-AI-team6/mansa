import unittest

from features.dashboard.evaluation.answerer import CodexAnswerer
from features.dashboard.evaluation.codex_cli import CodexError, CodexResult
from features.dashboard.evaluation.models import TestCase

CASE = TestCase(id="T01", question="브레이크 갭은?", workflow="L2")


class CodexAnswererTest(unittest.TestCase):
    def test_success_record(self):
        prompts = []

        def call(prompt, model=None):
            prompts.append(prompt)
            return CodexResult(text="0.5 mm", tokens=120, latency_sec=1.5)

        record = CodexAnswerer(call=call).answer(CASE)
        self.assertIn("브레이크 갭은?", prompts[0])
        self.assertEqual(record.answer_text, "0.5 mm")
        self.assertEqual((record.latency_sec, record.tokens), (1.5, 120))
        self.assertIsNone(record.cited_ids)
        self.assertIsNone(record.retrieved_ids)
        self.assertIsNone(record.error)

    def test_failure_becomes_error_record(self):
        def call(prompt, model=None):
            raise CodexError("codex timed out after 180s")

        record = CodexAnswerer(call=call).answer(CASE)
        self.assertEqual(record.error, "codex timed out after 180s")
        self.assertIsNone(record.latency_sec)


if __name__ == "__main__":
    unittest.main()
