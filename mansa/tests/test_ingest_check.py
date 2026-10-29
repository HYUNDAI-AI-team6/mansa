import tempfile
import unittest
from pathlib import Path

from scripts import ingest_check
from scripts.ingest_check import DEFAULT_DOCUMENT_ID, make_document, run
from tests.fake_chroma import FakeChroma
from tests.test_ingest_factory import TECH_PAGE, fake_embed, make_pdf


class IngestCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chroma = FakeChroma()
        self.pdf = make_pdf(Path(self.tmp.name) / "LUXEN 사양서.pdf", [TECH_PAGE])

    def check(self, **kwargs):
        options = {"model_names": lambda: ["LUXEN"], "embed": fake_embed, "indexer": self.chroma.indexer()}
        options.update(kwargs)
        return run(self.pdf, "tech", **options)

    def test_make_document_uses_the_stem_as_title(self):
        document = make_document(self.pdf, "tech", 5)
        self.assertEqual((document.id, document.title, document.filename), (5, "LUXEN 사양서", "LUXEN 사양서.pdf"))

    def test_dry_run_reports_chunks_and_touches_nothing(self):
        def embed(texts):
            raise AssertionError("dry-run must not embed")

        lines = self.check(embed=embed)
        text = "\n".join(lines)
        self.assertIn("pages: 1", text)
        self.assertIn("models: {'LUXEN':", text)
        self.assertIn("records ready for ChromaDB:", text)
        self.assertIn("dry-run", lines[-1])
        self.assertEqual(self.chroma.uploads, 0)

    def test_apply_stores_counts_and_removes(self):
        lines = self.check(apply=True)
        text = "\n".join(lines)
        self.assertIn("pipeline status: COMPLETED", text)
        self.assertIn("stored in ChromaDB and counted:", text)
        self.assertEqual(lines[-1], "removed test chunks")
        self.assertEqual(self.chroma.uploads, 1)
        self.assertEqual(self.chroma.stored, {})

    def test_apply_with_keep_leaves_the_chunks(self):
        lines = self.check(apply=True, keep=True)
        self.assertIn("kept in ChromaDB", lines[-1])
        self.assertGreaterEqual(self.chroma.count_stored("tech", DEFAULT_DOCUMENT_ID), 1)

    def test_apply_stops_when_the_temporary_id_already_has_chunks(self):
        self.check(apply=True, keep=True)
        before = dict(self.chroma.stored)
        lines = self.check(apply=True)
        self.assertTrue(lines[-1].startswith("stopped:"))
        self.assertEqual(self.chroma.stored, before)
        self.assertEqual(self.chroma.uploads, 1)

    def test_scanned_pdf_reports_the_failure(self):
        self.pdf = make_pdf(Path(self.tmp.name) / "scan.pdf", ["", ""])
        self.assertEqual(self.check(), ["failed: 스캔 PDF는 지원하지 않아요"])

    def test_unreadable_model_list_reports_the_failure(self):
        def model_names():
            raise OSError("csv is locked")

        with self.assertLogs("features.processing.factory", level="ERROR"):
            lines = self.check(model_names=model_names)
        self.assertEqual(len(lines), 1)
        self.assertIn("설비 모델 목록", lines[0])

    def test_failed_pipeline_run_is_reported_and_leaves_nothing(self):
        def embed(texts):
            raise RuntimeError("embedding api is down")

        with self.assertLogs("features.processing.pipeline", level="ERROR"):
            lines = self.check(apply=True, embed=embed)
        self.assertTrue(lines[-1].startswith("pipeline status: FAILED"))
        self.assertEqual(self.chroma.stored, {})

    def test_module_exposes_main(self):
        self.assertTrue(callable(ingest_check.main))


if __name__ == "__main__":
    unittest.main()
