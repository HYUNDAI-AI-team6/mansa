import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import openai
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from core.exceptions import LlmError
from features.support import service
from features.support.service import (
    FALLBACK,
    GUIDES,
    GetGuide,
    answer,
    load_guides,
    to_history,
)


def _tool_reply(topic, name="GetGuide", **extra):
    """LLM이 도구 name(topic, **extra)를 고른 응답을 만든다."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"topic": topic, **extra}, "id": "call_1"}],
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

    def test_invalid_tool_call_returns_fallback_without_logging_args(self):
        cases = {
            "list topic": _tool_reply(["upload"]),
            "leaked topic": _tool_reply("개인정보가 담긴 질문"),
            "wrong tool": _tool_reply("upload", name="개인정보가 담긴 질문"),
        }
        for label, message in cases.items():
            with self.subTest(label):
                with self.assertLogs(service.logger, "INFO") as logs:
                    reply, _ = self.ask(message)
                self.assertEqual(reply, {"text": FALLBACK})
                output = "\n".join(logs.output)
                self.assertIn("support tool call rejected", output)
                self.assertNotIn("개인정보", output)

    def test_extra_args_are_not_logged(self):
        with self.assertLogs(service.logger, "INFO") as logs:
            reply, _ = self.ask(_tool_reply("upload", note="개인정보가 담긴 질문"))
        self.assertEqual(reply, {"steps": GUIDES["upload"]})
        self.assertNotIn("개인정보", "\n".join(logs.output))

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


class LoadGuidesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "guides.json"

    def load(self, data):
        """data를 JSON으로 임시 파일에 쓰고 load_guides로 읽는다."""
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return load_guides(self.path)

    def assert_rejected(self, data, *words):
        """load_guides가 ValueError를 내고 메시지에 words가 모두 들어 있는지 확인한다."""
        with self.assertRaises(ValueError) as ctx:
            self.load(data)
        for word in words:
            self.assertIn(word, str(ctx.exception))

    def test_valid_file_builds_guides_and_tool(self):
        guides, model = self.load([
            {"id": "b", "when": "둘째", "text": "문장"},
            {"id": "a", "when": "첫째", "steps": ["하나", "둘"]},
        ])
        self.assertEqual(guides, {"b": "문장", "a": ["하나", "둘"]})
        self.assertEqual(model.model_validate({"topic": "a"}).topic, "a")
        with self.assertRaises(ValidationError):
            model.model_validate({"topic": "c"})
        function = convert_to_openai_tool(model)["function"]
        self.assertEqual(function["name"], "GetGuide")
        topic = function["parameters"]["properties"]["topic"]
        self.assertEqual(topic["enum"], ["b", "a"])
        self.assertEqual(topic["description"], "b: 둘째. a: 첫째.")

    def test_duplicated_id_is_rejected(self):
        self.assert_rejected(
            [{"id": "a", "when": "x", "text": "y"}, {"id": "a", "when": "x", "text": "z"}],
            "'a'", "duplicated",
        )

    def test_steps_and_text_must_be_exactly_one(self):
        for item in ({"id": "a", "when": "x", "text": "y", "steps": ["z"]},
                     {"id": "a", "when": "x"}):
            with self.subTest(item=item):
                self.assert_rejected([item], "'a'", "exactly one")

    def test_empty_strings_are_rejected(self):
        cases = {
            "when": {"id": "a", "when": " ", "text": "y"},
            "text": {"id": "a", "when": "x", "text": ""},
            "steps": {"id": "a", "when": "x", "steps": ["ok", ""]},
            "no steps": {"id": "a", "when": "x", "steps": []},
        }
        for name, item in cases.items():
            with self.subTest(name):
                self.assert_rejected([item], "'a'")

    def test_missing_id_is_rejected(self):
        self.assert_rejected([{"when": "x", "text": "y"}], "guides.json", "id")

    def test_empty_list_is_rejected(self):
        self.assert_rejected([], "guides.json")

    def test_broken_json_is_rejected(self):
        self.path.write_text("[{", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_guides(self.path)
        self.assertIn("guides.json", str(ctx.exception))

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            load_guides(self.path)
        self.assertIn("guides.json", str(ctx.exception))

    def test_real_data_file_loads(self):
        guides, model = load_guides(service.GUIDES_PATH)
        self.assertEqual(len(guides), 19)
        self.assertEqual(guides, GUIDES)
        self.assertEqual(model.__name__, "GetGuide")


if __name__ == "__main__":
    unittest.main()
