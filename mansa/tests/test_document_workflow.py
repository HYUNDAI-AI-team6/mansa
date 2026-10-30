"""업로드 → 백그라운드 처리 → 삭제 흐름을 DocumentService·파이프라인·삭제 흐름을 실제로 이어 확인한다.

DB는 메모리 대역(FakeDb), ChromaDB는 tests/fake_chroma.py, 임베딩·태그는 가짜 함수라 외부 서비스를 부르지 않는다.
"""

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from features.documents.errors import DocumentNotFoundError, DuplicateDocumentError
from features.documents.service import DocumentService
from features.documents.storage import PdfStorage
from features.processing.deletion import DeletionSteps, DocumentBusyError, DocumentDeleter
from features.processing.factory import build_ingest_pipeline, build_steps
from features.processing.pipeline import IngestPipeline
from features.processing.workflow import MAX_CONCURRENT_INGEST, DocumentWorkflow, PendingDocuments, spawn_thread
from tests.fake_chroma import FakeChroma
from tests.test_documents_pipeline import TEXT, fake_embed, make_pdf
from tests.test_documents_service import FakeDb


class WorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = FakeDb()
        self.service = DocumentService(self.db.fetch, self.db.run, PdfStorage(self.root / "documents"))
        self.chroma = FakeChroma()
        self.pdf = self.root / "upload.pdf"
        make_pdf(self.pdf, TEXT)

    def workflow(self, spawn=lambda task: task(), embed=fake_embed, max_concurrent=MAX_CONCURRENT_INGEST):
        # 태그 단계는 LLM을 부르므로 청크를 그대로 두는 함수로 바꿔 끼운다.
        steps = replace(build_steps(lambda: ["ELVRO 3000"], embed=embed), tag=lambda chunks: list(chunks))
        indexer = self.chroma.indexer()
        pending = PendingDocuments()
        deleter = DocumentDeleter(
            self.service,
            DeletionSteps(indexer.remove_document, self.service.delete_pdf, self.service.delete_document_record),
            is_processing=lambda document_id: document_id in pending or IngestPipeline.is_active(document_id),
        )
        return DocumentWorkflow(
            self.service,
            build_ingest_pipeline(self.service, indexer, steps),
            deleter,
            spawn,
            pending=pending,
            max_concurrent=max_concurrent,
        )

    def status(self, document_id: int) -> str:
        return self.service.get_status(document_id).status

    # ---- 업로드
    def test_upload_registers_then_processes_in_the_background(self) -> None:
        tasks = []
        flow = self.workflow(spawn=tasks.append)

        document_id = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)

        self.assertEqual(self.status(document_id), "PROCESSING")  # 아직 처리 전이다
        self.assertEqual(self.chroma.chunks_of("tech", document_id), {})
        self.assertEqual(len(tasks), 1)

        tasks[0]()  # 백그라운드 스레드가 하는 일

        self.assertEqual(self.status(document_id), "COMPLETED")
        self.assertGreater(len(self.chroma.chunks_of("tech", document_id)), 0)

    def test_duplicate_upload_is_rejected_without_starting_a_second_process(self) -> None:
        tasks = []
        flow = self.workflow(spawn=tasks.append)
        first = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)

        with self.assertRaises(DuplicateDocumentError) as caught:
            flow.upload(self.pdf, "엘트론.pdf", "tech", 3)

        self.assertEqual(caught.exception.document_id, first)
        self.assertEqual(len(tasks), 1)

    def test_invalid_upload_does_not_start_processing(self) -> None:
        tasks = []
        not_pdf = self.root / "note.txt"
        not_pdf.write_text("hello")

        with self.assertRaises(ValueError):
            self.workflow(spawn=tasks.append).upload(not_pdf, "note.txt", "tech", 3)

        self.assertEqual(tasks, [])

    def test_an_unexpected_error_in_the_background_task_is_logged_not_raised(self) -> None:
        flow = self.workflow()
        flow.pipeline = mock.Mock(run=mock.Mock(side_effect=RuntimeError("boom")))

        with self.assertLogs("features.processing.workflow", level="ERROR"):
            flow.upload(self.pdf, "엘트론.pdf", "tech", 3)

    def test_default_spawn_runs_the_task_on_another_thread(self) -> None:
        seen = []
        done = threading.Event()

        def task():
            seen.append(threading.current_thread())
            done.set()

        spawn_thread(task)

        self.assertTrue(done.wait(2))
        self.assertIsNot(seen[0], threading.current_thread())
        self.assertTrue(seen[0].daemon)

    # ---- 처리 대기와 동시 처리 수
    def test_a_document_waiting_to_start_cannot_be_deleted(self) -> None:
        """업로드 직후 스레드가 파이프라인을 시작하기 전에도 삭제할 수 없다."""
        tasks = []
        flow = self.workflow(spawn=tasks.append)
        document_id = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)
        self.assertFalse(IngestPipeline.is_active(document_id))  # 파이프라인은 아직 시작하지 않았다

        with self.assertRaises(DocumentBusyError):
            flow.delete(document_id)

        tasks[0]()  # 처리가 끝나면 지울 수 있다
        flow.delete(document_id)
        with self.assertRaises(DocumentNotFoundError):
            self.service.get_document(document_id)

    def test_the_waiting_record_is_cleared_even_when_processing_fails(self) -> None:
        broken = self.root / "broken.pdf"
        broken.write_bytes(b"%PDF-1.7\nthis is not a real pdf\n")
        flow = self.workflow()
        with self.assertLogs("features.processing.pipeline", level="ERROR"):
            document_id = flow.upload(broken, "엘트론.pdf", "tech", 3)

        flow.delete(document_id)  # 실패한 문서는 바로 지울 수 있다

    def test_the_waiting_record_is_cleared_when_the_thread_cannot_start(self) -> None:
        def spawn(task):
            raise RuntimeError("can't start new thread")

        flow = self.workflow(spawn=spawn)
        with self.assertRaises(RuntimeError):
            flow.upload(self.pdf, "엘트론.pdf", "tech", 3)
        document_id = self.service.list_documents()[0].id

        flow.delete(document_id)  # 처리를 시작하지 못했으니 지울 수 있다

    def test_at_most_the_limit_of_documents_are_processed_at_once(self) -> None:
        running = 0
        peak = 0
        lock = threading.Lock()
        release = threading.Event()
        two_running = threading.Event()

        def embed(texts):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
                if running == 2:
                    two_running.set()
            release.wait(5)
            with lock:
                running -= 1
            return fake_embed(texts)

        flow = self.workflow(spawn=spawn_thread, embed=embed, max_concurrent=2)
        ids = [flow.upload(self.pdf, f"문서{i}.pdf", "tech", 3) for i in range(4)]
        self.assertTrue(two_running.wait(5))
        threading.Event().wait(0.3)  # 나머지 둘이 끼어들 시간을 준다

        self.assertEqual(peak, 2)
        release.set()
        for document_id in ids:
            for _ in range(100):
                if self.status(document_id) != "PROCESSING":
                    break
                threading.Event().wait(0.05)
        self.assertEqual({self.status(i) for i in ids}, {"COMPLETED"})
        self.assertEqual(peak, 2)

    def test_the_limit_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            self.workflow(max_concurrent=0)

    # ---- 삭제
    def test_delete_removes_chunks_pdf_and_record(self) -> None:
        flow = self.workflow()
        document_id = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)
        pdf_path = Path(self.service.get_document(document_id).file_path)
        self.assertTrue(pdf_path.is_file())

        result = flow.delete(document_id)

        self.assertEqual(self.chroma.chunks_of("tech", document_id), {})
        self.assertFalse(pdf_path.exists())
        with self.assertRaises(DocumentNotFoundError):
            self.service.get_document(document_id)
        self.assertEqual((result.document_id, result.pdf_existed, result.record_existed), (document_id, True, True))

    def test_a_document_being_processed_right_now_cannot_be_deleted(self) -> None:
        errors = []
        flow = None

        def embed(texts):
            try:
                flow.delete(self.service.list_documents()[0].id)  # 처리 도중 삭제를 시도한다
            except Exception as exc:
                errors.append(exc)
            return fake_embed(texts)

        flow = self.workflow(embed=embed)
        document_id = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DocumentBusyError)
        self.assertEqual(self.status(document_id), "COMPLETED")  # 처리는 그대로 끝났다
        self.assertGreater(len(self.chroma.chunks_of("tech", document_id)), 0)

    def test_a_stale_processing_document_can_be_deleted(self) -> None:
        """앱이 처리 도중 꺼져 PROCESSING으로 남은 문서는 지금 실행 중이 아니므로 지울 수 있다."""
        flow = self.workflow()
        # 이전 실행에서 등록만 되고 처리되지 못한 문서처럼, 이 프로세스의 처리 기록에는 없다.
        document_id = self.service.register_document(self.pdf, "엘트론.pdf", "tech", 3)
        self.assertEqual(self.status(document_id), "PROCESSING")

        flow.delete(document_id)

        with self.assertRaises(DocumentNotFoundError):
            self.service.get_document(document_id)

    def test_a_failed_document_can_be_deleted_and_uploaded_again(self) -> None:
        broken = self.root / "broken.pdf"
        broken.write_bytes(b"%PDF-1.7\nthis is not a real pdf\n")
        flow = self.workflow()
        with self.assertLogs("features.processing.pipeline", level="ERROR"):
            document_id = flow.upload(broken, "엘트론.pdf", "tech", 3)
        self.assertEqual(self.status(document_id), "FAILED")
        with self.assertRaises(DuplicateDocumentError):
            flow.upload(self.pdf, "엘트론.pdf", "tech", 3)  # 삭제하기 전에는 같은 이름으로 못 올린다

        flow.delete(document_id)
        new_id = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)

        self.assertEqual(self.status(new_id), "COMPLETED")

    def test_deleting_a_document_whose_pdf_is_on_another_computer_still_works(self) -> None:
        flow = self.workflow()
        document_id = flow.upload(self.pdf, "엘트론.pdf", "tech", 3)
        self.service.delete_pdf(document_id)  # 다른 컴퓨터에서 올린 문서처럼 파일이 없다

        result = flow.delete(document_id)

        self.assertFalse(result.pdf_existed)
        self.assertEqual(self.chroma.chunks_of("tech", document_id), {})
        with self.assertRaises(DocumentNotFoundError):
            self.service.get_document(document_id)


class IsActiveTest(unittest.TestCase):
    def test_true_only_while_the_pipeline_runs_the_document(self) -> None:
        seen = []

        class Store:
            def get_document(self, document_id):
                seen.append(IngestPipeline.is_active(document_id))
                raise RuntimeError("stop here")  # 처리 도중의 상태만 보면 된다

            def set_status(self, *args, **kwargs):
                pass

        steps = replace(build_steps(lambda: [], embed=fake_embed), tag=lambda chunks: chunks)
        pipeline = build_ingest_pipeline(Store(), FakeChroma().indexer(), steps)

        self.assertFalse(IngestPipeline.is_active(41))
        with self.assertLogs("features.processing.pipeline", level="ERROR"):
            pipeline.run(41)

        self.assertEqual(seen, [True])
        self.assertFalse(IngestPipeline.is_active(41))


if __name__ == "__main__":
    unittest.main()
