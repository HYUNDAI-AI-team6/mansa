import unittest
from unittest import mock

import httpx
import openai
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai.chat_models.base import OpenAIRefusalError
from pydantic import BaseModel

from core import llm
from core.exceptions import LlmError


class Reply(BaseModel):
    text: str


class FakeModel:
    """with_structured_output만 흉내 내는 가짜 LLM. outcomes를 순서대로 돌려주거나 던진다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []  # 호출마다 LLM에 간 메시지 (종류, 내용) 목록

    def with_structured_output(self, schema):
        def run(prompt_value):
            self.calls.append([(m.type, m.content) for m in prompt_value.to_messages()])
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return schema(text=outcome)

        return RunnableLambda(run)


class CompleteTest(unittest.TestCase):
    def use(self, *outcomes):
        """가짜 모델을 끼우고 재시도 횟수를 2로 고정한다. 테스트가 끝나면 원래대로 돌아간다."""
        fake = FakeModel(*outcomes)
        for patcher in (mock.patch.object(llm, "_get_model", return_value=fake),
                        mock.patch.object(llm, "LLM_MAX_RETRIES", 2)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return fake

    def test_returns_dict_without_history(self):
        fake = self.use("답변")
        self.assertEqual(llm.complete("L2", "질문", Reply), {"text": "답변"})
        self.assertEqual(fake.calls, [[("human", "질문")]])

    def test_sends_history_before_question(self):
        fake = self.use("이어서 답변")
        history = [{"role": "user", "content": "앞 질문"}, {"role": "assistant", "content": "앞 답변"}]
        llm.complete("L2", "다음 질문", Reply, history)
        self.assertEqual(fake.calls[0], [("human", "앞 질문"), ("ai", "앞 답변"), ("human", "다음 질문")])
        self.assertEqual(len(history), 2)  # history는 바꾸지 않는다

    def test_braces_in_prompt_are_sent_as_is(self):
        fake = self.use("답변")
        llm.complete("L2", '형식: {"text": "..."}', Reply)
        self.assertEqual(fake.calls[0], [("human", '형식: {"text": "..."}')])

    def test_retries_then_succeeds(self):
        fake = self.use(ValueError("bad format"), "답변")
        self.assertEqual(llm.complete("L2", "질문", Reply), {"text": "답변"})
        self.assertEqual(len(fake.calls), 2)

    def test_raises_llm_error_after_all_retries(self):
        fake = self.use(ValueError("1"), ValueError("2"), ValueError("3"))
        with self.assertRaises(LlmError) as caught:
            llm.complete("L2", "질문", Reply)
        self.assertEqual(len(fake.calls), 3)  # 처음 1번 + 재시도 2번
        self.assertIsInstance(caught.exception.__cause__, ValueError)

    def test_refusal_is_not_retried(self):
        fake = self.use(OpenAIRefusalError("refused"), "답변")
        with self.assertRaises(LlmError):
            llm.complete("L2", "질문", Reply)
        self.assertEqual(len(fake.calls), 1)

    def test_other_errors_pass_through_without_retry(self):
        fake = self.use(RuntimeError("auth failed"), "답변")
        with self.assertRaises(RuntimeError):
            llm.complete("L2", "질문", Reply)
        self.assertEqual(len(fake.calls), 1)

    def test_missing_key_raises_before_api_call(self):
        with mock.patch.multiple(llm, LLM_API_KEY="", _model=None):
            with self.assertRaises(RuntimeError):
                llm.complete("L2", "질문", Reply)


class FakeToolModel:
    """bind_tools만 흉내 내는 가짜 LLM. outcomes를 순서대로 돌려주거나 던진다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.tools = None
        self.calls = []  # 호출마다 LLM에 간 메시지 목록

    def bind_tools(self, tools):
        self.tools = tools

        def run(messages):
            self.calls.append(messages)
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return RunnableLambda(run)


class ChooseToolTest(unittest.TestCase):
    def use(self, *outcomes):
        """가짜 모델을 끼우고 재시도 횟수를 2로 고정한다. 테스트가 끝나면 원래대로 돌아간다."""
        fake = FakeToolModel(*outcomes)
        for patcher in (mock.patch.object(llm, "_get_model", return_value=fake),
                        mock.patch.object(llm, "LLM_MAX_RETRIES", 2)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return fake

    def test_returns_message_and_binds_tools(self):
        reply = AIMessage(content="", tool_calls=[{"name": "Reply", "args": {"text": "x"}, "id": "c1"}])
        fake = self.use(reply)
        self.assertIs(llm.choose_tool("L3", "지시", "질문", [Reply]), reply)
        self.assertEqual(fake.tools, [Reply])

    def test_sends_system_history_then_question(self):
        fake = self.use(AIMessage(content="답변"))
        history = [{"role": "user", "content": "앞 질문"}, {"role": "assistant", "content": "앞 답변"}]
        llm.choose_tool("L3", "지시", "다음 질문", [Reply], history)
        self.assertEqual(fake.calls[0], [
            {"role": "system", "content": "지시"},
            {"role": "user", "content": "앞 질문"},
            {"role": "assistant", "content": "앞 답변"},
            {"role": "user", "content": "다음 질문"},
        ])
        self.assertEqual(len(history), 2)  # history는 바꾸지 않는다

    def test_timeout_retries_then_raises_llm_error(self):
        timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        fake = self.use(timeout, timeout, timeout)
        with self.assertRaises(LlmError) as caught:
            llm.choose_tool("L3", "지시", "질문", [Reply])
        self.assertEqual(len(fake.calls), 3)  # 처음 1번 + 재시도 2번
        self.assertIsInstance(caught.exception.__cause__, openai.APITimeoutError)

    def test_other_openai_errors_pass_through_without_retry(self):
        error = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
        fake = self.use(error, AIMessage(content="답변"))
        with self.assertRaises(openai.APIConnectionError):
            llm.choose_tool("L3", "지시", "질문", [Reply])
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()