import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from features.processing import factory
from features.processing.factory import build_ingest_pipeline, build_steps, keep_chunks, make_chunk_step
from features.processing.pipeline import STATUS_COMPLETED, STATUS_FAILED, IngestError, IngestSteps
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


class BuildStepsTest(unittest.TestCase):
    def test_keep_chunks_returns_the_same_chunks_as_a_list(self):
        chunks = ("a", "b")
        self.assertEqual(keep_chunks(chunks), ["a", "b"])

    def test_wires_the_given_embed_and_extract(self):
        steps = build_steps(lambda: [], embed=fake_embed)
        self.assertIsInstance(steps, IngestSteps)
        self.assertIs(steps.embed, fake_embed)
        self.assertIs(steps.extract, factory.extract_content)
        self.assertIs(steps.tag, keep_chunks)

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

    def run_pipeline(self, pages, doc_type="tech", model_names=lambda: ["LUXEN"]):
        doc = Doc(doc_type)
        doc.file_path = str(make_pdf(Path(self.tmp.name) / "sample.pdf", pages))
        store = Store(doc)
        steps = build_steps(model_names, embed=fake_embed)
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
