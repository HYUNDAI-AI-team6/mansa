import unittest
from unittest import mock

import httpx
import openai
from langchain_core.messages import AIMessage

from core.exceptions import LlmError
from features.support import service
from features.support.service import FALLBACK, GUIDES, GetGuide, answer, to_history


def _tool_reply(topic):
    """LLM이 GetGuide(topic)를 고른 응답을 만든다."""
    return AIMessage(
        content="", tool_calls=[{"name": "GetGuide", "args": {"topic": topic}, "id": "call_1"}]
    )


class FakeCall:
    """choose_tool 대신 쓰는 가짜 호출. 받은 인자를 기록하고 outcome을 돌려주거나 던진다."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def __call__(self, workflow, system, question, tools, history):
        self.calls.append((workflow, system, question, tools, history))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class AnswerTest(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(service, "LLM_API_KEY", "test-key"),
                        mock.patch.object(service, "LLM_MODEL", "test-model")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ask(self, outcome, question="질문", msgs=()):
        """가짜 호출로 answer를 실행하고 (결과, 가짜 호출)을 돌려준다."""
        fake = FakeCall(outcome)
        return answer(question, list(msgs), call=fake), fake

    def test_step_topic_returns_guide_steps_as_is(self):
        reply, fake = self.ask(_tool_reply("upload"))
        self.assertEqual(reply, {"steps": GUIDES["upload"]})
        self.assertEqual(len(fake.calls), 1)  # 도구 결과를 LLM에 다시 보내지 않는다
        workflow, _, question, tools, _ = fake.calls[0]
        self.assertEqual((workflow, question, tools), ("L3", "질문", [GetGuide]))

    def test_sentence_topic_returns_guide_text_as_is(self):
        reply, _ = self.ask(_tool_reply("history"))
        self.assertEqual(reply, {"text": GUIDES["history"]})

    def test_unknown_topic_returns_fallback(self):
        reply, _ = self.ask(_tool_reply("password"))
        self.assertEqual(reply, {"text": FALLBACK})

    def test_direct_answer_uses_text_of_content_blocks(self):
        message = AIMessage(content=[{"type": "text", "text": " 기술 Q&A에서 물어봐 주세요. ", "id": "m1"}])
        reply, _ = self.ask(message)
        self.assertEqual(reply, {"text": "기술 Q&A에서 물어봐 주세요."})

    def test_empty_answer_returns_fallback(self):
        reply, _ = self.ask(AIMessage(content=""))
        self.assertEqual(reply, {"text": FALLBACK})

    def test_llm_errors_return_fallback(self):
        request = httpx.Request("POST", "https://example.invalid")
        errors = [
            LlmError("timeout"),
            openai.APIConnectionError(request=request),
            openai.AuthenticationError(
                "auth", response=httpx.Response(401, request=request), body=None
            ),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with self.assertLogs(service.logger, "ERROR"):
                    reply, _ = self.ask(error)
                self.assertEqual(reply, {"text": FALLBACK})

    def test_missing_llm_settings_skips_call(self):
        with mock.patch.object(service, "LLM_API_KEY", ""):
            reply, fake = self.ask(_tool_reply("upload"))
        self.assertEqual(reply, {"text": FALLBACK})
        self.assertEqual(fake.calls, [])

    def test_sends_history_from_msgs(self):
        msgs = [{"who": "user", "text": "문서는 어떻게 올려요?"}, {"who": "bot", "steps": ["1단계", "2단계"]}]
        _, fake = self.ask(_tool_reply("upload"), "그건 관리자만 돼요?", msgs)
        self.assertEqual(fake.calls[0][4], to_history(msgs))

    def test_log_has_tool_but_not_question(self):
        with self.assertLogs(service.logger, "INFO") as logs:
            self.ask(_tool_reply("upload"), question="개인정보가 담긴 질문")
        output = "\n".join(logs.output)
        self.assertIn("GetGuide", output)
        self.assertIn("upload", output)
        self.assertNotIn("개인정보가 담긴 질문", output)


class ToHistoryTest(unittest.TestCase):
    def test_keeps_only_user_bot_pairs(self):
        msgs = [
            {"who": "bot", "text": "인사말", "chips": True},
            {"who": "user", "text": "질문1"},
            {"who": "bot", "steps": ["가", "나"]},
            {"who": "bot", "text": "관리자에게 연결해 드릴게요."},
            {"who": "system", "text": "관리자가 대화에 들어왔어요"},
            {"who": "admin", "text": "무엇을 도와드릴까요?"},
            {"who": "user", "text": "관리자에게 보낸 말"},
            {"who": "admin", "text": "확인해 볼게요."},
            {"who": "system", "text": "관리자와 연결이 끝났어요"},
            {"who": "user", "text": "질문2"},
            {"who": "bot", "text": "답변2"},
        ]
        self.assertEqual(to_history(msgs), [
            {"role": "user", "content": "질문1"},
            {"role": "assistant", "content": "가\n나"},
            {"role": "user", "content": "질문2"},
            {"role": "assistant", "content": "답변2"},
        ])

    def test_keeps_latest_five_pairs(self):
        msgs = []
        for i in range(6):
            msgs += [{"who": "user", "text": f"q{i}"}, {"who": "bot", "text": f"a{i}"}]
        history = to_history(msgs)
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0], {"role": "user", "content": "q1"})
        self.assertEqual(history[-1], {"role": "assistant", "content": "a5"})

    def test_empty_msgs(self):
        self.assertEqual(to_history([]), [])


if __name__ == "__main__":
    unittest.main()
