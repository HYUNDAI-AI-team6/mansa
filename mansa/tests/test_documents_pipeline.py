"""DocumentService가 파이프라인(IngestPipeline)이 기대하는 문서 저장소(get_document, set_status)로 쓰이는지 확인한다.

DB는 메모리 대역, ChromaDB는 tests/fake_chroma.py, 임베딩은 가짜 함수를 쓰므로 외부 서비스를 부르지 않는다.
"""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from features.documents.service import DocumentService
from features.documents.storage import PdfStorage
from features.processing.factory import build_ingest_pipeline, build_steps
from tests.fake_chroma import FakeChroma
from tests.test_documents_service import FakeDb

TEXT = [
    "ELVRO 3000 explosion-proof freight elevator for the chemical and petro-chemical industries.",
    "The car is designed for loads of 20 tons or more and for dusty or humid locations.",
    "A load detection monitoring device reports the loaded weight in real time to the control panel.",
    "Maintenance staff must check the hoistway and the machine room before the first operation.",
]


def make_pdf(path: Path, lines: list[str]) -> None:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((50, 80 + index * 30), line)
    document.save(path)
    document.close()


def fake_embed(texts: list[str]) -> list[list[float]]:
    return [[0.1, 0.2, 0.3] for _ in texts]


class PipelineWithDocumentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = FakeDb()
        self.service = DocumentService(self.db.fetch, self.db.run, PdfStorage(self.root / "documents"))
        self.chroma = FakeChroma()

    def pipeline(self):
        steps = build_steps(lambda: ["ELVRO 3000"], embed=fake_embed)
        return build_ingest_pipeline(self.service, self.chroma.indexer(), steps)

    def test_a_registered_pdf_is_processed_and_marked_completed(self) -> None:
        upload = self.root / "upload.pdf"
        make_pdf(upload, TEXT)
        document_id = self.service.register_document(upload, "엘트론.pdf", "tech", 3)
        self.assertEqual(self.service.get_status(document_id).status, "PROCESSING")

        self.pipeline().run(document_id)

        self.assertEqual(self.service.get_status(document_id).status, "COMPLETED")
        stored = self.chroma.chunks_of("tech", document_id)
        self.assertGreater(len(stored), 0)
        recorded = self.service.get_status(document_id)
        self.assertEqual(recorded.chunk_count, len(stored))  # 파이프라인이 넘긴 청크 수가 문서에 남는다
        self.assertIsNone(recorded.error_message)
        first = next(iter(stored.values()))["meta"]
        self.assertEqual((first["source"], first["doc_name"], first["model"]), ("엘트론.pdf", "엘트론", "ELVRO 3000"))

    def test_a_broken_pdf_is_recorded_as_failed_and_leaves_no_chunks(self) -> None:
        upload = self.root / "broken.pdf"
        upload.write_bytes(b"%PDF-1.7\nthis is not a real pdf\n")
        document_id = self.service.register_document(upload, "깨진문서.pdf", "tech", 3)

        with self.assertLogs("features.processing.pipeline", level="ERROR"):  # 실패 로그는 예상된 것이다
            self.pipeline().run(document_id)

        failed = self.service.get_status(document_id)
        self.assertEqual(failed.status, "FAILED")
        self.assertEqual(self.chroma.chunks_of("tech", document_id), {})
        self.assertEqual(failed.error_message, "PDF를 열 수 없어요")  # 사용자에게 보여도 되는 문구가 남는다
        self.assertIsNone(failed.chunk_count)

    def test_a_missing_pdf_file_is_recorded_as_failed(self) -> None:
        upload = self.root / "upload.pdf"
        make_pdf(upload, TEXT)
        document_id = self.service.register_document(upload, "엘트론.pdf", "tech", 3)
        self.service.delete_pdf(document_id)  # 다른 컴퓨터에서 올린 문서처럼 파일이 없다

        with self.assertLogs("features.processing.pipeline", level="ERROR"):
            self.pipeline().run(document_id)

        failed = self.service.get_status(document_id)
        self.assertEqual(failed.status, "FAILED")
        self.assertEqual(failed.error_message, "PDF를 열 수 없어요")

    def test_the_document_has_everything_the_pipeline_reads(self) -> None:
        upload = self.root / "upload.pdf"
        make_pdf(upload, TEXT)
        document_id = self.service.register_document(upload, "엘트론.pdf", "tech", 3)

        document = self.service.get_document(document_id)

        for name in ("id", "title", "filename", "doc_type", "file_path"):
            self.assertTrue(hasattr(document, name), name)
        self.assertIsInstance(document.file_path, str)
        self.assertTrue(Path(document.file_path).is_file())

    def test_a_finished_document_is_not_changed_by_a_second_run(self) -> None:
        upload = self.root / "upload.pdf"
        make_pdf(upload, TEXT)
        document_id = self.service.register_document(upload, "엘트론.pdf", "tech", 3)
        pipeline = self.pipeline()
        pipeline.run(document_id)

        pipeline.run(document_id)  # 이미 완료된 문서를 다시 처리해도 상태는 그대로 완료다

        self.assertEqual(self.service.get_status(document_id).status, "COMPLETED")


if __name__ == "__main__":
    unittest.main()
