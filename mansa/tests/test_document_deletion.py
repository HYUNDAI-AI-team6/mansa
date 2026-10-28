import logging
import unittest
from dataclasses import dataclass

from features.processing.deletion import (
    DeletionError,
    DeletionSteps,
    DocumentBusyError,
    DocumentDeleter,
)


def setUpModule():
    """실패 시나리오가 남기는 오류 로그로 테스트 출력이 어지러워지지 않게 로그를 끈다."""
    logging.disable(logging.CRITICAL)


def tearDownModule():
    """다른 테스트에 영향이 없도록 로그를 다시 켠다."""
    logging.disable(logging.NOTSET)


class DocumentNotFound(Exception):
    """DocumentService의 DocumentNotFoundError 대역."""


@dataclass
class FakeDocument:
    id: int = 1
    doc_type: str = "tech"
    filename: str = "a.pdf"


class FakeSystem:
    """세 저장소(ChromaDB·PDF·MySQL)와 호출 순서를 기록하는 대역. 각 단계를 실패시킬 수 있다."""

    def __init__(self, document=None):
        self.document = document or FakeDocument()
        self.calls = []
        self.chunks, self.pdf, self.record = {1: 5}, {1}, {1}
        self.fail_at = None

    def get_document(self, document_id):
        if document_id not in self.record:
            raise DocumentNotFound(document_id)
        return self.document

    def _maybe_fail(self, step):
        if self.fail_at == step:
            raise RuntimeError(f"secret-token at {step}")

    def remove_chunks(self, doc_type, document_id):
        self.calls.append(("chunks", doc_type, document_id))
        self._maybe_fail("chunks")
        self.chunks.pop(document_id, None)

    def delete_pdf(self, document_id):
        self.calls.append(("pdf", document_id))
        self._maybe_fail("pdf")
        existed = document_id in self.pdf
        self.pdf.discard(document_id)
        return existed

    def delete_record(self, document_id):
        self.calls.append(("record", document_id))
        self._maybe_fail("record")
        existed = document_id in self.record
        self.record.discard(document_id)
        return existed

    def steps(self):
        return DeletionSteps(self.remove_chunks, self.delete_pdf, self.delete_record)

    def deleter(self, is_processing=None):
        return DocumentDeleter(self, self.steps(), is_processing)


class DocumentDeleterTest(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem()

    def test_deletes_chunks_then_pdf_then_record(self):
        result = self.system.deleter().delete(1)
        self.assertEqual([c[0] for c in self.system.calls], ["chunks", "pdf", "record"])
        self.assertEqual(self.system.calls[0], ("chunks", "tech", 1))
        system = self.system
        self.assertEqual((system.chunks, system.pdf, system.record), ({}, set(), set()))
        self.assertEqual((result.document_id, result.filename), (1, "a.pdf"))
        self.assertTrue(result.pdf_existed and result.record_existed)

    def test_uses_the_documents_own_type_for_the_chunk_store(self):
        self.system.document = FakeDocument(doc_type="secure")
        self.system.deleter().delete(1)
        self.assertEqual(self.system.calls[0], ("chunks", "secure", 1))

    def test_failure_stops_later_steps_and_keeps_the_record(self):
        for step, later in (("chunks", ["chunks"]), ("pdf", ["chunks", "pdf"]),
                            ("record", ["chunks", "pdf", "record"])):
            system = FakeSystem()
            system.fail_at = step
            with self.assertRaises(DeletionError):
                system.deleter().delete(1)
            self.assertEqual([c[0] for c in system.calls], later)
            if step != "record":
                self.assertEqual(system.record, {1}, "기록은 마지막 단계 전에는 남아 있어야 한다")

    def test_error_message_is_safe_and_cause_is_kept(self):
        self.system.fail_at = "chunks"
        with self.assertRaises(DeletionError) as caught:
            self.system.deleter().delete(1)
        self.assertNotIn("secret-token", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)

    def test_retry_after_each_failure_finishes_the_job(self):
        for step in ("chunks", "pdf", "record"):
            system = FakeSystem()
            system.fail_at = step
            with self.assertRaises(DeletionError):
                system.deleter().delete(1)
            system.fail_at = None
            system.deleter().delete(1)
            self.assertEqual((system.chunks, system.pdf, system.record), ({}, set(), set()), step)

    def test_retry_reports_that_the_pdf_was_already_gone(self):
        self.system.fail_at = "record"
        with self.assertRaises(DeletionError):
            self.system.deleter().delete(1)
        self.system.fail_at = None
        result = self.system.deleter().delete(1)
        self.assertFalse(result.pdf_existed)
        self.assertTrue(result.record_existed)

    def test_missing_pdf_does_not_stop_the_deletion(self):
        self.system.pdf.clear()
        result = self.system.deleter().delete(1)
        self.assertFalse(result.pdf_existed)
        self.assertEqual(self.system.record, set())

    def test_unknown_document_raises_the_lookup_error_without_deleting(self):
        with self.assertRaises(DocumentNotFound):
            self.system.deleter().delete(99)
        self.assertEqual(self.system.calls, [])

    def test_document_being_processed_is_not_deleted(self):
        with self.assertRaises(DocumentBusyError):
            self.system.deleter(is_processing=lambda document_id: document_id == 1).delete(1)
        self.assertEqual(self.system.calls, [])
        self.assertEqual(self.system.record, {1})

    def test_stale_processing_status_does_not_block_deletion(self):
        # 처리 중 상태가 남았어도 이 프로세스에서 실제로 돌고 있지 않으면 지울 수 있다.
        self.system.document.status = "PROCESSING"
        self.system.deleter(is_processing=lambda document_id: False).delete(1)
        self.assertEqual(self.system.record, set())

    def test_rejects_concurrent_delete_of_the_same_document(self):
        outcome = []

        def remove_chunks(doc_type, document_id):
            try:
                self.system.deleter().delete(1)
            except DocumentBusyError as exc:
                outcome.append(exc)

        steps = DeletionSteps(remove_chunks, self.system.delete_pdf, self.system.delete_record)
        DocumentDeleter(self.system, steps).delete(1)
        self.assertEqual(len(outcome), 1)
        self.assertEqual(self.system.record, set())

    def test_guard_is_released_after_failure(self):
        self.system.fail_at = "pdf"
        with self.assertRaises(DeletionError):
            self.system.deleter().delete(1)
        self.system.fail_at = None
        self.system.deleter().delete(1)  # 이미 삭제 중이라는 오류가 나면 안 된다
        self.assertEqual(self.system.record, set())


if __name__ == "__main__":
    unittest.main()
