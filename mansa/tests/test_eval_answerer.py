import unittest

import httpx
import openai

from core.exceptions import LlmError
from features.evaluation.answerer import AnswerOutput, LlmAnswerer
from features.evaluation.models import TestCase

CASE = TestCase(id="T01", question="브레이크 갭은?", workflow="L2")


def _api_error(cls, status):
    """openai 상태 오류 예외를 만든다. 실제 응답 없이 테스트에서만 쓴다."""
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"))
    return cls("error", response=response, body=None)


class LlmAnswererTest(unittest.TestCase):
    def test_success_record(self):
        calls = []

        def call(workflow, prompt, schema):
            calls.append((workflow, prompt, schema))
            return {"answer": "0.5 mm"}

        record = LlmAnswerer(call=call).answer(CASE)
        workflow, prompt, schema = calls[0]
        self.assertEqual((workflow, schema), ("L2", AnswerOutput))
        self.assertIn("브레이크 갭은?", prompt)
        self.assertEqual(record.answer_text, "0.5 mm")
        self.assertGreaterEqual(record.latency_sec, 0)
        self.assertIsNone(record.tokens)
        self.assertIsNone(record.cited_ids)
        self.assertIsNone(record.retrieved_ids)
        self.assertIsNone(record.error)

    def test_failure_becomes_error_record(self):
        for exc in (LlmError("L2 LLM failed after 3 attempts"),
                    _api_error(openai.RateLimitError, 429),
                    openai.ContentFilterFinishReasonError()):
            def call(workflow, prompt, schema):
                raise exc

            record = LlmAnswerer(call=call).answer(CASE)
            self.assertEqual(record.error, str(exc))
            self.assertIsNone(record.latency_sec)

    def test_config_error_propagates(self):
        def call(workflow, prompt, schema):
            raise _api_error(openai.AuthenticationError, 401)

        with self.assertRaises(openai.AuthenticationError):
            LlmAnswerer(call=call).answer(CASE)


if __name__ == "__main__":
    unittest.main()
