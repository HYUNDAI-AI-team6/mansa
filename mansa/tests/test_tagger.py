import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from features.master.taxonomy import TaxonomyService
from features.processing.chunker import chunk
from features.processing.indexer import Indexer
from features.processing.pdf_content import extract_pdf_content
from features.processing.models import Chunk
from features.processing.tagger import (
    BATCH_SIZE,
    MAX_PART_TAGS,
    MAX_TASK_TAGS,
    Vocabulary,
    apply_tags,
    build_prompt,
    candidate_indexes,
    match_items,
    request_tags,
    tag,
)

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
SAFETY_PDF = PDF_DIR / "안전기준.pdf"
LUXEN_PDF = PDF_DIR / "Passenger Elevator_LUXEN NEW YZER_2406.pdf"

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


def item(chunk_id: str, part=(), task=()) -> dict:
    return {"id": chunk_id, "part": list(part), "task": list(task)}


class ApplyTagsTest(unittest.TestCase):
    TEXT = "메인 로프와 완충기를 점검한다. 와이어로프 상태를 확인한다."

    def apply(self, part=(), task=(), text: str = TEXT, vocab: Vocabulary | None = None) -> Chunk:
        return apply_tags(make_chunk(text), item("1:p1:0", part, task), vocab or vocabulary())

    def test_valid_tags_are_joined_with_comma_and_space(self) -> None:
        chunk = self.apply(["메인 로프", "완충기"], ["메인 로프 점검"])

        self.assertEqual(chunk.metadata["part"], "메인 로프, 완충기")
        self.assertEqual(chunk.metadata["task"], "메인 로프 점검")

    def test_original_metadata_and_text_are_kept(self) -> None:
        original = make_chunk(self.TEXT)

        chunk = apply_tags(original, item("1:p1:0", ["완충기"]), vocabulary())

        self.assertEqual(chunk.text, original.text)
        self.assertEqual({k: v for k, v in chunk.metadata.items() if k != "part"}, original.metadata)
        self.assertNotIn("part", original.metadata)

    def test_synonym_is_converted_to_the_standard_name(self) -> None:
        self.assertEqual(self.apply(["와이어로프"]).metadata["part"], "메인 로프")

    def test_values_outside_the_vocabulary_are_dropped(self) -> None:
        chunk = self.apply(["엘리베이터", "완충기"], ["완충기", "청소"])

        self.assertEqual(chunk.metadata["part"], "완충기")
        self.assertNotIn("task", chunk.metadata)

    def test_part_without_evidence_in_the_text_is_dropped(self) -> None:
        chunk = self.apply(["메인 로프", "승강기 칸"], text="메인 로프를 점검한다")

        self.assertEqual(chunk.metadata["part"], "메인 로프")

    def test_task_without_evidence_in_the_text_is_dropped(self) -> None:
        chunk = self.apply(["메인 로프"], ["메인 로프 점검", "완충기 시험"], text="메인 로프의 재질과 완충기 설명")

        self.assertNotIn("task", chunk.metadata)

    def test_duplicates_are_removed(self) -> None:
        chunk = self.apply(["메인 로프", "와이어로프", "메인 로프"])

        self.assertEqual(chunk.metadata["part"], "메인 로프")

    def test_tag_counts_are_capped_in_the_order_given(self) -> None:
        vocab = Vocabulary(tuple(f"부위{i}" for i in range(6)), tuple(f"부위{i} 점검" for i in range(6)))
        text = " ".join(f"부위{i}" for i in range(6)) + " 점검"

        chunk = self.apply([f"부위{i}" for i in range(6)], [f"부위{i} 점검" for i in range(6)], text, vocab)

        self.assertEqual(chunk.metadata["part"], ", ".join(f"부위{i}" for i in range(MAX_PART_TAGS)))
        self.assertEqual(chunk.metadata["task"], ", ".join(f"부위{i} 점검" for i in range(MAX_TASK_TAGS)))

    def test_value_with_a_comma_is_dropped(self) -> None:
        vocab = Vocabulary(("로프, 케이블",), ())

        self.assertNotIn("part", self.apply(["로프, 케이블"], text="로프, 케이블", vocab=vocab).metadata)

    def test_non_string_values_and_bad_shapes_are_ignored(self) -> None:
        chunk = apply_tags(make_chunk(self.TEXT), {"id": "1:p1:0", "part": [None, 3, "완충기"], "task": "점검"}, vocabulary())

        self.assertEqual(chunk.metadata["part"], "완충기")
        self.assertNotIn("task", chunk.metadata)

    def test_empty_result_returns_the_same_chunk_without_keys(self) -> None:
        original = make_chunk(self.TEXT)

        self.assertIs(apply_tags(original, item("1:p1:0"), vocabulary()), original)
        self.assertIs(apply_tags(original, {"id": "1:p1:0"}, vocabulary()), original)


class MatchItemsTest(unittest.TestCase):
    def test_results_are_matched_by_chunk_id(self) -> None:
        batch = [make_chunk("a", index=0), make_chunk("b", index=1)]

        matched = match_items(batch, [item("1:p1:1", ["완충기"]), item("1:p1:0", ["메인 로프"])])

        self.assertEqual(set(matched), {"1:p1:0", "1:p1:1"})
        self.assertEqual(matched["1:p1:1"]["part"], ["완충기"])

    def test_unknown_ids_are_dropped(self) -> None:
        matched = match_items([make_chunk("a", index=0)], [item("1:p9:9", ["완충기"]), item("1:p1:0")])

        self.assertEqual(set(matched), {"1:p1:0"})

    def test_duplicated_result_ids_are_all_dropped(self) -> None:
        batch = [make_chunk("a", index=0), make_chunk("b", index=1)]

        matched = match_items(batch, [item("1:p1:0", ["완충기"]), item("1:p1:0", ["메인 로프"]), item("1:p1:1")])

        self.assertEqual(set(matched), {"1:p1:1"})

    def test_missing_ids_are_simply_absent(self) -> None:
        batch = [make_chunk("a", index=0), make_chunk("b", index=1)]

        self.assertEqual(set(match_items(batch, [item("1:p1:0")])), {"1:p1:0"})

    def test_duplicated_ids_inside_the_batch_are_not_matched(self) -> None:
        batch = [make_chunk("a", index=0), make_chunk("b", index=0)]

        self.assertEqual(match_items(batch, [item("1:p1:0", ["완충기"])]), {})

    def test_malformed_items_are_ignored(self) -> None:
        matched = match_items([make_chunk("a", index=0)], ["x", None, {"part": []}, item("1:p1:0")])

        self.assertEqual(set(matched), {"1:p1:0"})


class TagTest(unittest.TestCase):
    def test_tags_are_added_and_order_and_length_are_kept(self) -> None:
        chunks = [
            make_chunk("메인 로프를 점검한다", index=0),
            make_chunk("표 4. 시험 방법", index=1),
            make_chunk("완충기 시험 절차", index=2),
        ]
        sent = []

        def complete(workflow, prompt, schema):
            sent.append(prompt)
            return {"chunks": [item("1:p1:0", ["메인 로프"], ["메인 로프 점검"]), item("1:p1:2", ["완충기"], ["완충기 시험"])]}

        result = tag(chunks, vocabulary(), complete)

        self.assertEqual([c.chunk_id for c in result], [c.chunk_id for c in chunks])
        self.assertEqual(result[0].metadata["task"], "메인 로프 점검")
        self.assertEqual(result[2].metadata["part"], "완충기")
        self.assertIs(result[1], chunks[1])
        self.assertNotIn("[청크 id=1:p1:1]", sent[0])  # 부위가 없는 청크는 LLM에 보내지 않는다

    def test_input_chunks_are_not_modified(self) -> None:
        chunk = make_chunk("메인 로프 점검")
        before = dict(chunk.metadata)

        tag([chunk], vocabulary(), lambda *a: {"chunks": [item("1:p1:0", ["메인 로프"])]})

        self.assertEqual(chunk.metadata, before)

    def test_no_candidates_means_no_llm_call(self) -> None:
        def complete(*args):
            raise AssertionError("must not be called")

        chunks = [make_chunk("표 4. 시험 방법")]

        self.assertEqual(tag(chunks, vocabulary(), complete), chunks)
        self.assertEqual(tag([], vocabulary(), complete), [])

    def test_candidates_are_sent_in_batches(self) -> None:
        chunks = [make_chunk("완충기 점검", index=i) for i in range(BATCH_SIZE + 1)]
        sizes = []

        def complete(workflow, prompt, schema):
            sizes.append(prompt.count("[청크 id="))
            return {"chunks": []}

        tag(chunks, vocabulary(), complete)

        self.assertEqual(sizes, [BATCH_SIZE, 1])

    def test_results_from_another_batch_are_not_applied(self) -> None:
        chunks = [make_chunk("완충기 점검", index=i) for i in range(BATCH_SIZE + 1)]
        last_id = chunks[-1].chunk_id

        def complete(workflow, prompt, schema):
            return {"chunks": [item(last_id, ["완충기"])]}  # 첫 배치에는 없는 id다

        result = tag(chunks, vocabulary(), complete)

        self.assertTrue(all("part" not in c.metadata for c in result[:BATCH_SIZE]))
        self.assertEqual(result[-1].metadata["part"], "완충기")


class TagFailureTest(unittest.TestCase):
    def chunks(self, count: int) -> list[Chunk]:
        return [make_chunk("완충기 점검", index=i) for i in range(count)]

    def test_failed_batch_is_left_untagged_and_others_continue(self) -> None:
        chunks = self.chunks(BATCH_SIZE + 1)
        calls = []

        def complete(workflow, prompt, schema):
            calls.append(prompt)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return {"chunks": [item(chunks[-1].chunk_id, ["완충기"])]}

        with self.assertLogs("features.processing.tagger", level="WARNING") as logs:
            result = tag(chunks, vocabulary(), complete)

        self.assertEqual(len(result), len(chunks))
        self.assertTrue(all("part" not in c.metadata for c in result[:BATCH_SIZE]))
        self.assertEqual(result[-1].metadata["part"], "완충기")
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("boom", logs.output[0])

    def test_malformed_response_leaves_the_batch_untagged(self) -> None:
        chunks = self.chunks(2)

        for bad in ({}, {"chunks": None}, {"chunks": "x"}):
            with self.subTest(bad=bad), self.assertLogs("features.processing.tagger", level="WARNING"):
                result = tag(chunks, vocabulary(), lambda *a, bad=bad: bad)

            self.assertEqual(result, chunks)

    def test_garbage_items_do_not_raise(self) -> None:
        chunks = self.chunks(1)

        result = tag(chunks, vocabulary(), lambda *a: {"chunks": ["x", None, {"id": chunks[0].chunk_id, "part": 5}]})

        self.assertEqual(result, chunks)

    def test_all_batches_failing_returns_the_input_unchanged(self) -> None:
        chunks = self.chunks(BATCH_SIZE * 2)

        def complete(*args):
            raise ConnectionError

        with self.assertLogs("features.processing.tagger", level="WARNING") as logs:
            result = tag(chunks, vocabulary(), complete)

        self.assertEqual(result, chunks)
        self.assertEqual(len(logs.output), 2)

    def test_keyboard_interrupt_is_not_swallowed(self) -> None:
        def complete(*args):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            tag(self.chunks(1), vocabulary(), complete)


@dataclass
class RealDocument:
    doc_type: str
    id: int
    title: str
    filename: str


class RealPdfTaggingTest(unittest.TestCase):
    """실제 PDF 청크를 가짜 LLM으로 태깅해 검증·형식·Indexer 호환을 확인한다. 실제 LLM은 부르지 않는다."""

    @staticmethod
    def fake_llm(vocab: Vocabulary, chunks: list[Chunk]):
        """청크에 표준 이름이 그대로 있는 부위와 모든 작업을 후보로 낸다. 작업은 검증이 걸러야 한다."""
        by_id = {c.chunk_id: c for c in chunks}

        def complete(workflow, prompt, schema):
            ids = re.findall(r"\[청크 id=(.+?)\]", prompt)
            return {
                "chunks": [
                    {"id": i, "part": [p for p in vocab.parts if p in by_id[i].text], "task": list(vocab.tasks)}
                    for i in ids
                ]
            }

        return complete

    def check(self, document: RealDocument, pdf: Path, models: list[str] | None) -> list[Chunk]:
        vocab = Vocabulary.from_taxonomy(TaxonomyService.from_directory())
        chunks = chunk(document, extract_pdf_content(pdf), models)

        result = tag(chunks, vocab, self.fake_llm(vocab, chunks))

        self.assertEqual([c.chunk_id for c in result], [c.chunk_id for c in chunks])
        for before, after in zip(chunks, result):
            self.assertEqual(after.text, before.text)
            parts = after.metadata["part"].split(", ") if "part" in after.metadata else []
            tasks = after.metadata["task"].split(", ") if "task" in after.metadata else []
            self.assertLessEqual(len(parts), MAX_PART_TAGS)
            self.assertLessEqual(len(tasks), MAX_TASK_TAGS)
            self.assertTrue(set(parts) <= set(vocab.parts), after.chunk_id)
            self.assertTrue(set(tasks) <= set(vocab.tasks), after.chunk_id)
            self.assertTrue(all(p == p.strip() and p for p in parts + tasks), after.chunk_id)
            if parts or tasks:  # 부위가 본문에 없는 청크에는 태그가 붙지 않는다
                self.assertTrue(any(vocab.supports_part(before.text, p) for p in vocab.parts), after.chunk_id)
        Indexer().prepare(document.id, document.doc_type, result)
        return result

    @unittest.skipUnless(SAFETY_PDF.is_file(), "safety pdf not found")
    def test_safety_pdf_tags_pass_indexer_prepare(self) -> None:
        result = self.check(RealDocument("secure", 12, "안전기준", "안전기준.pdf"), SAFETY_PDF, None)

        tagged = [c for c in result if "part" in c.metadata]
        self.assertGreater(len(tagged), len(result) // 2)

    @unittest.skipUnless(LUXEN_PDF.is_file(), "LUXEN pdf not found")
    def test_catalog_pdf_tags_pass_indexer_prepare(self) -> None:
        document = RealDocument("tech", 8, "LUXEN", "LUXEN.pdf")

        result = self.check(document, LUXEN_PDF, ["LUXEN", "NEW YZER"])

        self.assertTrue(any("part" in c.metadata for c in result))


if __name__ == "__main__":
    unittest.main()
