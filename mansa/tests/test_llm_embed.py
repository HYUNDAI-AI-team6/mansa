import unittest
from unittest import mock

from core import llm


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


def use(fake: FakeEmbeddings):
    """llm.embed가 진짜 OpenAI 대신 fake를 쓰게 한다."""
    return mock.patch.object(llm, "_get_embeddings", return_value=fake)


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


class MissingKeyTest(unittest.TestCase):
    def test_a_missing_api_key_raises_runtime_error_without_the_key_in_the_message(self) -> None:
        with mock.patch.object(llm, "LLM_API_KEY", None), mock.patch.object(llm, "_embeddings", None):
            with self.assertRaises(RuntimeError) as caught:
                llm.embed(["문장"])

        self.assertIn("LLM_API_KEY", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
