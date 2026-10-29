import unittest

from features.master.taxonomy import TaxonomyService
from features.processing.models import Chunk
from features.processing.tagger import Vocabulary, build_prompt, candidate_indexes, request_tags

PARTS = ("메인 로프", "승강기 칸", "완충기")
TASKS = ("메인 로프 점검", "승강기 칸 점검", "완충기 시험")
SYNONYMS = {"와이어로프": "메인 로프", "카": "승강기 칸"}


def vocabulary() -> Vocabulary:
    return Vocabulary(PARTS, TASKS, SYNONYMS)


def make_chunk(text: str, page: int = 1, index: int = 0) -> Chunk:
    meta = {"source": "a.pdf", "page": page, "chunk": index, "document_id": 1, "document_type": "secure"}
    return Chunk(text=text, metadata=meta)


class VocabularyTest(unittest.TestCase):
    def test_from_taxonomy_copies_the_service_values(self) -> None:
        service = TaxonomyService.from_directory()

        vocab = Vocabulary.from_taxonomy(service)

        self.assertEqual(list(vocab.parts), service.taxonomy.parts)
        self.assertEqual(list(vocab.tasks), service.taxonomy.tasks)
        self.assertEqual(vocab.synonyms, service.synonyms)
        self.assertIsNot(vocab.synonyms, service.synonyms)

    def test_forms_include_the_name_and_its_synonyms(self) -> None:
        self.assertEqual(vocabulary().forms("메인 로프"), ["메인 로프", "와이어로프"])
        self.assertEqual(vocabulary().forms("완충기"), ["완충기"])

    def test_standard_accepts_names_and_synonyms(self) -> None:
        vocab = vocabulary()

        self.assertEqual(vocab.standard("메인 로프", vocab.parts), "메인 로프")
        self.assertEqual(vocab.standard(" 와이어로프 ", vocab.parts), "메인 로프")
        self.assertEqual(vocab.standard("카", vocab.parts), "승강기 칸")

    def test_standard_rejects_unknown_values(self) -> None:
        vocab = vocabulary()

        self.assertIsNone(vocab.standard("엘리베이터", vocab.parts))
        self.assertIsNone(vocab.standard("", vocab.parts))

    def test_standard_converts_synonym_words_inside_a_task(self) -> None:
        vocab = vocabulary()

        self.assertEqual(vocab.standard("카 점검", vocab.tasks), "승강기 칸 점검")
        self.assertEqual(vocab.standard("와이어로프 점검", vocab.tasks), "메인 로프 점검")

    def test_standard_does_not_accept_a_part_as_a_task(self) -> None:
        vocab = vocabulary()

        self.assertIsNone(vocab.standard("완충기", vocab.tasks))


class MentionsTest(unittest.TestCase):
    def test_ignores_spaces_and_case(self) -> None:
        vocab = Vocabulary(("NEW YZER",), ())

        self.assertTrue(vocab.mentions("new  yzer 모델", ["NEW YZER"]))
        self.assertTrue(vocab.mentions("메인로프를 점검한다", ["메인 로프"]))

    def test_missing_form_is_not_mentioned(self) -> None:
        self.assertFalse(vocabulary().mentions("승강로 내부를 청소한다", ["메인 로프", "와이어로프"]))

    def test_one_character_synonym_needs_a_word_boundary(self) -> None:
        vocab = vocabulary()

        self.assertTrue(vocab.mentions("카 내부 조명", ["카"]))
        self.assertTrue(vocab.mentions("카의 벽은 견고해야 한다", ["카"]))
        self.assertTrue(vocab.mentions("카에서 점검한다", ["카"]))
        self.assertFalse(vocab.mentions("카문을 연다", ["카"]))
        self.assertFalse(vocab.mentions("카드를 사용한다", ["카"]))
        self.assertFalse(vocab.mentions("엘리베이터 카탈로그", ["카"]))

    def test_empty_form_is_ignored(self) -> None:
        self.assertFalse(vocabulary().mentions("본문", ["", "  "]))


class SupportTest(unittest.TestCase):
    def test_part_is_supported_by_its_name_or_synonym(self) -> None:
        vocab = vocabulary()

        self.assertTrue(vocab.supports_part("완충기를 설치한다", "완충기"))
        self.assertTrue(vocab.supports_part("와이어로프 상태 확인", "메인 로프"))
        self.assertTrue(vocab.supports_part("카 내부 조명", "승강기 칸"))
        self.assertFalse(vocab.supports_part("완충기를 설치한다", "메인 로프"))

    def test_task_needs_both_the_part_and_the_verb(self) -> None:
        vocab = vocabulary()

        self.assertTrue(vocab.supports_task("메인 로프를 매월 점검한다", "메인 로프 점검"))
        self.assertTrue(vocab.supports_task("와이어로프 점검 방법", "메인 로프 점검"))
        self.assertFalse(vocab.supports_task("메인 로프의 재질", "메인 로프 점검"))
        self.assertFalse(vocab.supports_task("완충기를 점검한다", "메인 로프 점검"))

    def test_task_with_synonym_part_is_supported(self) -> None:
        self.assertTrue(vocabulary().supports_task("카 상부를 점검한다", "승강기 칸 점검"))

    def test_single_word_task_needs_its_own_name(self) -> None:
        vocab = Vocabulary((), ("점검",))

        self.assertTrue(vocab.supports_task("정기 점검", "점검"))
        self.assertFalse(vocab.supports_task("정기 시험", "점검"))


class CandidateTest(unittest.TestCase):
    def test_only_chunks_that_mention_a_part_are_candidates(self) -> None:
        chunks = [
            make_chunk("메인 로프를 점검한다", index=0),
            make_chunk("표 4. 시험 방법", index=1),
            make_chunk("카 내부 조명", index=2),
            make_chunk("와이어로프 마모", index=3),
        ]

        self.assertEqual(candidate_indexes(chunks, vocabulary()), [0, 2, 3])

    def test_chunk_without_any_part_is_skipped(self) -> None:
        self.assertEqual(candidate_indexes([make_chunk("부속서 Ⅰ 전기안전장치 목록")], vocabulary()), [])

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(candidate_indexes([], vocabulary()), [])

    def test_empty_vocabulary_has_no_candidates(self) -> None:
        self.assertEqual(candidate_indexes([make_chunk("메인 로프")], Vocabulary((), ())), [])

    def test_one_character_synonym_does_not_make_unrelated_chunks_candidates(self) -> None:
        chunks = [make_chunk("카탈로그 안내", index=0), make_chunk("카드 결제", index=1)]

        self.assertEqual(candidate_indexes(chunks, vocabulary()), [])


class PromptTest(unittest.TestCase):
    def test_prompt_lists_vocabulary_synonyms_and_chunks(self) -> None:
        chunks = [make_chunk("메인 로프를 점검한다", index=0), make_chunk("완충기 시험", index=1)]

        prompt = build_prompt(vocabulary(), chunks)

        for expected in ("메인 로프", "승강기 칸", "완충기 시험", "와이어로프 → 메인 로프", "카 → 승강기 칸"):
            self.assertIn(expected, prompt)
        self.assertIn("[청크 id=1:p1:0]\n메인 로프를 점검한다\n[/청크]", prompt)
        self.assertIn("[청크 id=1:p1:1]\n완충기 시험\n[/청크]", prompt)

    def test_braces_in_chunk_text_are_kept_as_data(self) -> None:
        prompt = build_prompt(vocabulary(), [make_chunk("식 {x} 와 {parts} 가 있다")])

        self.assertIn("식 {x} 와 {parts} 가 있다", prompt)

    def test_empty_vocabulary_is_shown_as_none(self) -> None:
        prompt = build_prompt(Vocabulary((), ()), [make_chunk("본문")])

        self.assertIn("[부위 목록]\n없음", prompt)
        self.assertIn("[동의어]\n없음", prompt)


class RequestTagsTest(unittest.TestCase):
    def test_sends_the_prompt_and_returns_items(self) -> None:
        calls = []

        def complete(workflow, prompt, schema):
            calls.append((workflow, prompt, schema))
            return {"chunks": [{"id": "1:p1:0", "part": ["메인 로프"], "task": []}]}

        items = request_tags(vocabulary(), [make_chunk("메인 로프")], complete)

        self.assertEqual(items, [{"id": "1:p1:0", "part": ["메인 로프"], "task": []}])
        self.assertEqual(calls[0][0], "TAG")
        self.assertIn("[청크 id=1:p1:0]", calls[0][1])
        self.assertEqual(calls[0][2].__name__, "_BatchOutput")

    def test_llm_errors_are_passed_through(self) -> None:
        def complete(workflow, prompt, schema):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            request_tags(vocabulary(), [make_chunk("메인 로프")], complete)


if __name__ == "__main__":
    unittest.main()
