import contextlib
import unittest
from unittest import mock

from core import llm
from core.exceptions import LlmError


class FakeEmbeddings:
    """OpenAIEmbeddings 대역. 받은 문장을 기록하고 문장마다 같은 길이의 벡터를 준다."""

    def __init__(self, dimension: int = 3, result=None) -> None:
        self.dimension = dimension
        self.result = result
        self.received: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.received.append(list(texts))
        if self.result is not None:
            return self.result
        return [[float(index)] * self.dimension for index, _ in enumerate(texts)]


@contextlib.contextmanager
def use(fake: FakeEmbeddings, model: str = "test-model"):
    """llm.embed가 진짜 OpenAI 대신 fake를 쓰게 한다. 기본 모델은 차원 표에 없는 이름이라 길이 일치만 확인한다."""
    with mock.patch.object(llm, "_get_embeddings", return_value=fake), mock.patch.object(llm, "EMBEDDING_MODEL", model):
        yield


class InputCheckTest(unittest.TestCase):
    def test_empty_list_returns_empty_list_without_calling_the_api(self) -> None:
        fake = FakeEmbeddings()

        with use(fake):
            self.assertEqual(llm.embed([]), [])

        self.assertEqual(fake.received, [])

    def test_texts_are_sent_in_order_and_the_input_is_not_changed(self) -> None:
        fake = FakeEmbeddings()
        texts = ["첫째", "둘째", "셋째"]

        with use(fake):
            vectors = llm.embed(texts)

        self.assertEqual(fake.received, [["첫째", "둘째", "셋째"]])
        self.assertEqual(texts, ["첫째", "둘째", "셋째"])
        self.assertEqual(len(vectors), 3)

    def test_a_tuple_is_accepted_and_sent_as_a_list(self) -> None:
        fake = FakeEmbeddings()

        with use(fake):
            llm.embed(("a", "b"))

        self.assertEqual(fake.received, [["a", "b"]])

    def test_blank_or_non_string_values_are_rejected_before_calling_the_api(self) -> None:
        for bad in ([""], ["a", ""], ["a", "   "], ["\n\t"], [None], ["a", 3], [b"bytes"], [["nested"]]):
            fake = FakeEmbeddings()
            with self.subTest(bad=bad), use(fake), self.assertRaises(ValueError):
                llm.embed(bad)
            self.assertEqual(fake.received, [])

    def test_a_plain_string_or_none_is_not_a_list_of_texts(self) -> None:
        for bad in ("안전기준", None, 5, {"a": 1}, {"a"}):
            fake = FakeEmbeddings()
            with self.subTest(bad=bad), use(fake), self.assertRaises(ValueError):
                llm.embed(bad)
            self.assertEqual(fake.received, [])

    def test_the_error_names_the_position_but_not_the_text(self) -> None:
        with self.assertRaises(ValueError) as caught:
            llm.embed(["비밀 본문 내용", "  "])

        self.assertIn("texts[1]", str(caught.exception))
        self.assertNotIn("비밀 본문", str(caught.exception))


class ResultCheckTest(unittest.TestCase):
    def embed_with(self, result, texts=("a", "b"), model="test-model"):
        with use(FakeEmbeddings(result=result), model):
            return llm.embed(list(texts))

    def test_matching_vectors_are_returned_unchanged(self) -> None:
        result = [[0.1, 0.2], [0.3, 0.4]]

        self.assertEqual(self.embed_with(result), result)

    def test_a_different_number_of_vectors_is_an_error(self) -> None:
        for result in ([[0.1]], [[0.1], [0.2], [0.3]], []):
            with self.subTest(count=len(result)), self.assertRaises(LlmError):
                self.embed_with(result)

    def test_a_result_that_is_not_a_list_is_an_error(self) -> None:
        for result in ("abc", {"a": [0.1]}, 5):
            with self.subTest(result=result), self.assertRaises(LlmError):
                self.embed_with(result)

    def test_empty_or_non_numeric_vectors_are_errors(self) -> None:
        for result in ([[0.1], []], [[0.1], ["x"]], [[0.1], [None]], [[0.1], [True]], [[0.1], "ab"], [[0.1], 7]):
            with self.subTest(result=result), self.assertRaises(LlmError):
                self.embed_with(result)

    def test_vectors_of_different_lengths_are_an_error(self) -> None:
        with self.assertRaises(LlmError):
            self.embed_with([[0.1, 0.2], [0.3]])

    def test_integer_values_count_as_numbers(self) -> None:
        self.assertEqual(self.embed_with([[1, 2], [3, 4]]), [[1, 2], [3, 4]])

    def test_the_default_large_model_must_return_3072_dimensions(self) -> None:
        good = [[0.0] * 3072, [0.0] * 3072]

        self.assertEqual(self.embed_with(good, model="text-embedding-3-large"), good)
        with self.assertRaises(LlmError):
            self.embed_with([[0.0] * 1536, [0.0] * 1536], model="text-embedding-3-large")

    def test_the_small_model_must_return_1536_dimensions(self) -> None:
        good = [[0.0] * 1536, [0.0] * 1536]

        self.assertEqual(self.embed_with(good, model="text-embedding-3-small"), good)
        with self.assertRaises(LlmError):
            self.embed_with([[0.0] * 3072, [0.0] * 3072], model="text-embedding-3-small")

    def test_an_unknown_model_only_needs_matching_lengths(self) -> None:
        good = [[0.0] * 7, [0.0] * 7]

        self.assertEqual(self.embed_with(good, model="some-new-model"), good)

    def test_error_messages_do_not_contain_the_texts_or_the_values(self) -> None:
        with self.assertRaises(LlmError) as caught:
            self.embed_with([[0.123456]], texts=("비밀 본문 내용", "다른 본문"))

        message = str(caught.exception)
        self.assertNotIn("비밀 본문", message)
        self.assertNotIn("0.123456", message)
        self.assertIn("1 vectors for 2 texts", message)

    def test_api_errors_are_passed_on_unchanged(self) -> None:
        class Failing(FakeEmbeddings):
            def embed_documents(self, texts):
                raise ConnectionError("network down")

        with use(Failing()), self.assertRaises(ConnectionError):
            llm.embed(["문장"])


class MissingKeyTest(unittest.TestCase):
    def test_a_missing_api_key_raises_runtime_error_without_the_key_in_the_message(self) -> None:
        with mock.patch.object(llm, "LLM_API_KEY", None), mock.patch.object(llm, "_embeddings", None):
            with self.assertRaises(RuntimeError) as caught:
                llm.embed(["문장"])

        self.assertIn("LLM_API_KEY", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
