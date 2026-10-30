import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from features.processing import factory
from features.processing.factory import (
    build_ingest_pipeline,
    build_steps,
    build_vocabulary,
    make_chunk_step,
    make_tag_step,
)
from features.processing.pipeline import STATUS_COMPLETED, STATUS_FAILED, IngestError, IngestSteps
from features.processing.tagger import Vocabulary, tag
from tests.fake_chroma import FakeChroma


class Doc:
    def __init__(self, doc_type="tech", id=7):
        self.id = id
        self.title = "sample"
        self.filename = "sample.pdf"
        self.doc_type = doc_type
        self.file_path = "sample.pdf"


class Store:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def get_document(self, document_id):
        return self.document

    def set_status(self, document_id, status, error=None, chunk_count=None):
        self.calls.append((status, error, chunk_count))


def fake_embed(texts):
    return [[float(len(text)), 1.0] for text in texts]


def make_pdf(path: Path, page_texts: list[str]) -> Path:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            y = 72
            for line in text.split("\n"):
                page.insert_text((72, y), line)
                y += 16
    doc.save(path)
    doc.close()
    return path


VOCABULARY = Vocabulary(parts=("machine room",), tasks=("machine room maintenance",))


def fake_complete(workflow, prompt, schema, history=None):
    """프롬프트의 청크 id마다 같은 부위·작업을 돌려주는 가짜 LLM."""
    ids = re.findall(r"\[청크 id=(.*?)\]", prompt)
    return {"chunks": [{"id": i, "part": ["machine room"], "task": ["machine room maintenance"]} for i in ids]}


TECH_PAGE = "\n".join(
    [
        "LUXEN passenger elevator specification",
        "The LUXEN uses a machine room less drive and a permanent magnet motor.",
        "Rated speed is 105 meters per minute and rated load is 1000 kilograms.",
        "Maintenance should be carried out every month by a qualified technician.",
    ]
)


class ChunkStepTest(unittest.TestCase):
    def test_tech_documents_get_the_registered_model_names(self):
        with mock.patch.object(factory, "chunk", return_value=["c"]) as chunk:
            result = make_chunk_step(lambda: ["LUXEN", "NEW YZER"])(Doc("tech"), "content")
        self.assertEqual(result, ["c"])
        chunk.assert_called_once()
        self.assertEqual(chunk.call_args.args[2], ["LUXEN", "NEW YZER"])

    def test_secure_documents_do_not_read_the_model_list(self):
        def model_names():
            raise AssertionError("must not be called for secure documents")

        with mock.patch.object(factory, "chunk", return_value=["c"]) as chunk:
            make_chunk_step(model_names)(Doc("secure"), "content")
        self.assertEqual(chunk.call_args.args, (mock.ANY, "content"))

    def test_model_list_is_read_on_every_call(self):
        names = [["A"]]
        step = make_chunk_step(lambda: names[0])
        with mock.patch.object(factory, "chunk", return_value=[]) as chunk:
            step(Doc(), "content")
            names[0] = ["A", "B"]
            step(Doc(), "content")
        self.assertEqual([call.args[2] for call in chunk.call_args_list], [["A"], ["A", "B"]])

    def test_unreadable_model_list_becomes_a_user_facing_error(self):
        def model_names():
            raise OSError("csv is locked")

        with self.assertRaises(IngestError) as caught:
            make_chunk_step(model_names)(Doc(), "content")
        self.assertIn("설비 모델 목록", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_empty_model_list_warns_and_continues(self):
        with mock.patch.object(factory, "chunk", return_value=["c"]) as chunk:
            with self.assertLogs(factory.logger, level="WARNING"):
                result = make_chunk_step(lambda: [])(Doc(), "content")
        self.assertEqual(result, ["c"])
        self.assertEqual(chunk.call_args.args[2], [])


class TagStepTest(unittest.TestCase):
    def test_passes_the_chunks_and_the_vocabulary_to_the_tagger(self):
        seen = []

        def tagger(chunks, vocabulary):
            seen.append((chunks, vocabulary))
            return ["tagged"]

        result = make_tag_step(lambda: "vocab", tagger)(["c"])
        self.assertEqual(result, ["tagged"])
        self.assertEqual(seen, [(["c"], "vocab")])

    def test_vocabulary_is_read_on_every_call(self):
        reads = []

        def vocabulary():
            reads.append(1)
            return len(reads)

        used = []
        step = make_tag_step(vocabulary, lambda chunks, vocab: used.append(vocab) or chunks)
        step(["a"])
        step(["b"])
        self.assertEqual(used, [1, 2])

    def test_unreadable_vocabulary_is_passed_on_to_the_pipeline(self):
        def vocabulary():
            raise OSError("taxonomy is locked")

        with self.assertRaises(OSError):
            make_tag_step(vocabulary, lambda chunks, vocab: chunks)(["c"])

    def test_default_tagger_is_the_real_tag_function(self):
        with mock.patch("features.processing.tagger.tag", return_value=["real"]) as real:
            result = make_tag_step(lambda: "vocab")(["c"])
        self.assertEqual(result, ["real"])
        real.assert_called_once_with(["c"], "vocab")

    def test_build_vocabulary_reads_the_taxonomy_files(self):
        vocabulary = build_vocabulary()
        self.assertIsInstance(vocabulary, Vocabulary)
        self.assertTrue(vocabulary.parts)
        self.assertTrue(vocabulary.tasks)


class BuildStepsTest(unittest.TestCase):
    def test_wires_the_given_embed_and_extract(self):
        steps = build_steps(lambda: [], embed=fake_embed)
        self.assertIsInstance(steps, IngestSteps)
        self.assertIs(steps.embed, fake_embed)
        self.assertIs(steps.extract, factory.extract_content)

    def test_wires_the_given_vocabulary_and_tagger_into_the_tag_step(self):
        steps = build_steps(lambda: [], embed=fake_embed, vocabulary=lambda: "vocab",
                            tagger=lambda chunks, vocab: [vocab])
        self.assertEqual(steps.tag(["c"]), ["vocab"])

    def test_pipeline_uses_the_given_steps_and_indexer(self):
        steps = build_steps(lambda: [], embed=fake_embed)
        indexer = FakeChroma().indexer()
        pipeline = build_ingest_pipeline(Store(Doc()), indexer, steps)
        self.assertIs(pipeline.steps, steps)
        self.assertIs(pipeline.indexer, indexer)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chroma = FakeChroma()

    def run_pipeline(self, pages, doc_type="tech", model_names=lambda: ["LUXEN"], tagger=None):
        doc = Doc(doc_type)
        doc.file_path = str(make_pdf(Path(self.tmp.name) / "sample.pdf", pages))
        store = Store(doc)
        steps = build_steps(model_names, embed=fake_embed, vocabulary=lambda: VOCABULARY,
                            tagger=tagger or (lambda chunks, vocabulary: list(chunks)))
        build_ingest_pipeline(store, self.chroma.indexer(), steps).run(doc.id)
        return store.calls

    def test_tech_pdf_is_stored_with_the_registry_model_spelling(self):
        calls = self.run_pipeline([TECH_PAGE])
        status, error, chunk_count = calls[-1]
        self.assertEqual((status, error), (STATUS_COMPLETED, None))
        stored = self.chroma.chunks_of("tech", 7)
        self.assertEqual(len(stored), chunk_count)
        self.assertGreaterEqual(chunk_count, 1)
        self.assertEqual({item["meta"]["model"] for item in stored.values()}, {"LUXEN"})
        self.assertEqual({item["collection"] for item in stored.values()}, {"tech_docs"})

    def test_tags_are_stored_as_lists(self):
        """실제 tag 함수(가짜 LLM)가 붙인 태그가 문자열 목록으로 저장된다. Indexer가 목록을 거절하면 문서가 실패한다."""
        calls = self.run_pipeline([TECH_PAGE], tagger=lambda chunks, vocabulary: tag(chunks, vocabulary, fake_complete))
        status, error, chunk_count = calls[-1]
        self.assertEqual((status, error), (STATUS_COMPLETED, None))
        stored = self.chroma.chunks_of("tech", 7)
        self.assertEqual(len(stored), chunk_count)
        for item in stored.values():
            self.assertEqual(item["meta"]["part"], ["machine room"])
            self.assertEqual(item["meta"]["task"], ["machine room maintenance"])

    def test_tag_failure_still_completes_without_tags(self):
        def tagger(chunks, vocabulary):
            raise RuntimeError("llm is down")

        with self.assertLogs("features.processing.pipeline", level="WARNING"):
            calls = self.run_pipeline([TECH_PAGE], tagger=tagger)
        self.assertEqual(calls[-1][0], STATUS_COMPLETED)
        stored = self.chroma.chunks_of("tech", 7)
        self.assertTrue(stored)
        for item in stored.values():
            self.assertNotIn("part", item["meta"])
            self.assertNotIn("task", item["meta"])

    def test_scanned_pdf_fails_with_the_extraction_message_and_stores_nothing(self):
        status, error, chunk_count = self.run_pipeline(["", ""])[-1]
        self.assertEqual(status, STATUS_FAILED)
        self.assertEqual(error, "스캔 PDF는 지원하지 않아요")
        self.assertIsNone(chunk_count)
        self.assertEqual(self.chroma.stored, {})

    def test_unreadable_model_list_fails_with_its_message(self):
        def model_names():
            raise OSError("csv is locked")

        status, error, _ = self.run_pipeline([TECH_PAGE], model_names=model_names)[-1]
        self.assertEqual(status, STATUS_FAILED)
        self.assertIn("설비 모델 목록", error)
        self.assertEqual(self.chroma.stored, {})


if __name__ == "__main__":
    unittest.main()
