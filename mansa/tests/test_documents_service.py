import tempfile
import unicodedata
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest import mock

from sqlalchemy.exc import IntegrityError

from features.documents.errors import (
    DocumentNotFoundError,
    DocumentStorageError,
    DuplicateDocumentError,
    InvalidStatusTransition,
)
from features.documents.models import Document, DocumentRow
from features.documents.service import DocumentService, check_pdf, normalize_filename
from features.documents.storage import PdfStorage

PDF = b"%PDF-1.7\n% test\n"
NOW = datetime(2026, 10, 29, 12, 0, 0)


class FakeDb:
    """documents_info를 메모리에 두고 서비스가 보내는 SQL에 답하는 대역. 실제 DB에는 접속하지 않는다."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.departments = {3: "안전관리팀", 5: "기술팀"}
        self.calls: list[tuple[str, dict | None]] = []
        self.next_id = 1
        self.blind_precheck = False  # True면 첫 중복 조회가 비어 있는 것처럼 답한다(동시에 올린 경우)
        self.insert_error: Exception | None = None
        self.before_update = None  # UPDATE 직전에 부르는 함수(다른 곳이 먼저 바꾼 경우를 흉내 낸다)

    def fetch(self, sql: str, params: dict | None = None) -> list[dict]:
        self.calls.append((sql, params))
        if sql.startswith("SELECT id FROM documents_info WHERE filename"):
            if self.blind_precheck:
                self.blind_precheck = False
                return []
            return [
                {"id": r["id"]}
                for r in self.rows
                if r["filename"] == params["filename"] and r["document_type"] == params["doc_type"]
            ]
        if "GROUP BY" in sql:
            counts = Counter((r["document_type"], r["status"]) for r in self.rows)
            return [{"document_type": t, "status": s, "n": n} for (t, s), n in counts.items()]
        rows = [{**r, "department_name": self.departments.get(r["department_id"])} for r in self.rows]
        if "WHERE d.id = :id" in sql:
            rows = [r for r in rows if r["id"] == params["id"]]
        return rows

    def run(self, sql: str, params: dict | None = None) -> int:
        self.calls.append((sql, params))
        if sql.startswith("INSERT INTO documents_info"):
            if self.insert_error:
                raise self.insert_error
            if any(r["filename"] == params["filename"] and r["document_type"] == params["doc_type"] for r in self.rows):
                raise IntegrityError("INSERT", params, Exception(1062, "Duplicate entry"))
            if params["department_id"] not in self.departments:
                raise IntegrityError("INSERT", params, Exception(1452, "foreign key fails"))
            self.rows.append({
                "id": self.next_id, "filename": params["filename"], "document_type": params["doc_type"],
                "department_id": params["department_id"], "status": params["status"],
                "upload_at": NOW, "updated_at": NOW,
            })
            self.next_id += 1
            return 1
        if sql.startswith("DELETE FROM documents_info WHERE id"):
            before = len(self.rows)
            self.rows = [r for r in self.rows if r["id"] != params["id"]]
            return before - len(self.rows)
        if sql.startswith("UPDATE documents_info SET status"):
            if self.before_update:
                self.before_update(self)
            changed = 0
            for row in self.rows:
                if row["id"] == params["id"] and row["status"] == params["current"]:
                    row["status"] = params["status"]
                    changed += 1
            return changed
        raise AssertionError(f"unexpected SQL: {sql}")

    def sql_with(self, text: str) -> list[tuple[str, dict | None]]:
        return [call for call in self.calls if text in call[0]]


class ServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = FakeDb()
        self.storage = PdfStorage(self.root / "documents")
        self.service = DocumentService(self.db.fetch, self.db.run, self.storage)
        self.upload = self.root / "upload.pdf"
        self.upload.write_bytes(PDF)

    def files(self) -> list[str]:
        folder = self.root / "documents"
        return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()) if folder.exists() else []

    def register(self, filename: str = "안전기준.pdf", doc_type: str = "secure", department_id: int = 3) -> int:
        return self.service.register_document(self.upload, filename, doc_type, department_id)


class RegisterTest(ServiceTestCase):
    def test_registers_the_document_and_stores_the_pdf_by_id(self) -> None:
        document_id = self.register()

        self.assertEqual(document_id, 1)
        self.assertEqual(self.db.rows[0]["filename"], "안전기준.pdf")
        self.assertEqual(self.db.rows[0]["status"], "PROCESSING")
        self.assertEqual(self.files(), ["secure/1.pdf"])
        self.assertEqual((self.root / "documents" / "secure" / "1.pdf").read_bytes(), PDF)

    def test_the_uploaded_source_file_is_left_alone(self) -> None:
        self.register()

        self.assertTrue(self.upload.exists())

    def test_filename_is_normalized_to_nfc_with_a_lowercase_extension(self) -> None:
        self.register(unicodedata.normalize("NFD", " 안전기준.PDF "))

        self.assertEqual(self.db.rows[0]["filename"], unicodedata.normalize("NFC", "안전기준.pdf"))

    def test_same_name_in_another_normalization_form_is_a_duplicate(self) -> None:
        first = self.register("안전기준.pdf")

        with self.assertRaises(DuplicateDocumentError) as caught:
            self.register(unicodedata.normalize("NFD", "안전기준.PDF"))

        self.assertEqual(caught.exception.document_id, first)

    def test_duplicate_is_rejected_before_anything_is_saved(self) -> None:
        self.register()

        with self.assertRaises(DuplicateDocumentError):
            self.register()

        self.assertEqual(len(self.db.rows), 1)
        self.assertEqual(self.files(), ["secure/1.pdf"])
        self.assertEqual(len(self.db.sql_with("INSERT")), 1)

    def test_duplicate_found_only_by_the_unique_key_is_still_reported_and_cleaned_up(self) -> None:
        first = self.register()
        self.db.blind_precheck = True

        with self.assertRaises(DuplicateDocumentError) as caught:
            self.register()

        self.assertEqual(caught.exception.document_id, first)
        self.assertEqual(self.files(), ["secure/1.pdf"])  # 임시 파일이 남지 않는다

    def test_same_name_is_allowed_for_a_different_document_type(self) -> None:
        self.register("매뉴얼.pdf", "tech")
        self.register("매뉴얼.pdf", "secure")

        self.assertEqual(self.files(), ["secure/2.pdf", "tech/1.pdf"])

    def test_unknown_department_is_a_value_error_and_nothing_is_left(self) -> None:
        with self.assertRaises(ValueError):
            self.register(department_id=99)

        self.assertEqual(self.db.rows, [])
        self.assertEqual(self.files(), [])

    def test_other_database_errors_are_passed_on_and_the_temp_file_is_removed(self) -> None:
        self.db.insert_error = IntegrityError("INSERT", {}, Exception(1048, "Column cannot be null"))

        with self.assertRaises(IntegrityError):
            self.register()

        self.assertEqual(self.files(), [])

    def test_a_failed_file_commit_removes_the_row_and_the_temp_file(self) -> None:
        with mock.patch.object(self.storage, "commit", side_effect=DocumentStorageError("disk full")):
            with self.assertRaises(DocumentStorageError):
                self.register()

        self.assertEqual(self.db.rows, [])
        self.assertEqual(self.files(), [])
        self.assertEqual(len(self.db.sql_with("DELETE FROM documents_info WHERE id")), 1)

    def test_a_failed_row_cleanup_does_not_hide_the_storage_error(self) -> None:
        original_run = self.db.run

        def run(sql, params=None):
            if sql.startswith("DELETE"):
                raise RuntimeError("db down")
            return original_run(sql, params)

        service = DocumentService(self.db.fetch, run, self.storage)
        with mock.patch.object(self.storage, "commit", side_effect=DocumentStorageError("disk full")):
            with self.assertLogs("features.documents.service", level="ERROR"):
                with self.assertRaises(DocumentStorageError):
                    service.register_document(self.upload, "a.pdf", "tech", 3)

    def test_a_source_that_vanishes_after_validation_is_a_storage_error_without_a_row(self) -> None:
        with mock.patch("features.documents.service.check_pdf"):
            with self.assertRaises(DocumentStorageError):
                self.service.register_document(self.root / "gone.pdf", "a.pdf", "tech", 3)

        self.assertEqual(self.db.rows, [])
        self.assertEqual(self.db.sql_with("INSERT"), [])


class RegisterValidationTest(ServiceTestCase):
    def assert_rejected(self, **kwargs) -> None:
        values = {"filename": "a.pdf", "doc_type": "tech", "department_id": 3, **kwargs}
        with self.assertRaises(ValueError):
            self.service.register_document(self.upload, **values)
        self.assertEqual(self.db.calls, [])  # DB를 부르기 전에 거절한다
        self.assertEqual(self.files(), [])

    def test_unknown_document_type(self) -> None:
        for bad in ("SPEC", "", None, "../tech"):
            with self.subTest(bad=bad):
                self.assert_rejected(doc_type=bad)

    def test_bad_file_names(self) -> None:
        for bad in ("a.txt", "a", ".pdf", "  .PDF", "dir/a.pdf", "dir\\a.pdf", "a\x00.pdf", "a\n.pdf", "x" * 252 + ".pdf", None, 3):
            with self.subTest(bad=bad):
                self.assert_rejected(filename=bad)

    def test_department_is_required(self) -> None:
        for bad in (None, 0, -1, True, "3", 3.0):
            with self.subTest(bad=bad):
                self.assert_rejected(department_id=bad)

    def test_file_must_be_a_real_pdf(self) -> None:
        fake = self.root / "fake.pdf"
        empty = self.root / "empty.pdf"
        fake.write_bytes(b"hello")
        empty.write_bytes(b"")
        for bad in (fake, empty, self.root / "missing.pdf", self.root):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.service.register_document(bad, "a.pdf", "tech", 3)
        self.assertEqual(self.db.calls, [])
        self.assertEqual(self.files(), [])

    def test_file_over_the_size_limit_is_rejected(self) -> None:
        with mock.patch("features.documents.service.MAX_PDF_BYTES", len(PDF) - 1):
            with self.assertRaises(ValueError):
                self.register()

        self.assertEqual(self.db.calls, [])

    def test_file_exactly_at_the_size_limit_is_accepted(self) -> None:
        with mock.patch("features.documents.service.MAX_PDF_BYTES", len(PDF)):
            self.assertEqual(self.register(), 1)


class HelperTest(unittest.TestCase):
    def test_normalize_filename_keeps_a_255_character_name(self) -> None:
        name = "가" * 251 + ".pdf"

        self.assertEqual(normalize_filename(name), name)

    def test_normalize_filename_strips_spaces_before_the_extension(self) -> None:
        self.assertEqual(normalize_filename("a .pdf"), "a.pdf")

    def test_check_pdf_accepts_a_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.pdf"
            path.write_bytes(PDF)

            check_pdf(path)


class QueryTest(ServiceTestCase):
    def test_get_document_returns_the_row_with_department_and_path(self) -> None:
        document_id = self.register()

        document = self.service.get_document(document_id)

        self.assertIsInstance(document, Document)
        self.assertEqual((document.id, document.title, document.filename), (1, "안전기준", "안전기준.pdf"))
        self.assertEqual((document.doc_type, document.department_id, document.department_name), ("secure", 3, "안전관리팀"))
        self.assertEqual(document.status, "PROCESSING")
        self.assertIsNone(document.chunk_count)
        self.assertEqual(document.file_path, str(self.root / "documents" / "secure" / "1.pdf"))
        self.assertIsInstance(document.file_path, str)

    def test_file_path_is_returned_even_when_the_file_is_missing(self) -> None:
        document_id = self.register()
        self.storage.delete(document_id)

        self.assertTrue(self.service.get_document(document_id).file_path.endswith("secure/1.pdf"))

    def test_get_document_without_a_department_shows_none(self) -> None:
        self.db.rows.append({
            "id": 7, "filename": "a.pdf", "document_type": "tech", "department_id": None,
            "status": "COMPLETED", "upload_at": NOW, "updated_at": NOW,
        })

        document = self.service.get_document(7)

        self.assertIsNone(document.department_id)
        self.assertIsNone(document.department_name)

    def test_missing_document_raises_not_found(self) -> None:
        with self.assertRaises(DocumentNotFoundError) as caught:
            self.service.get_document(42)

        self.assertEqual(caught.exception.document_id, 42)

    def test_bad_ids_raise_value_error_without_asking_the_database(self) -> None:
        for bad in (0, -3, True, "1", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.service.get_document(bad)
        self.assertEqual(self.db.calls, [])

    def test_get_status(self) -> None:
        document_id = self.register()

        status = self.service.get_status(document_id)

        self.assertEqual((status.status, status.chunk_count, status.updated_at), ("PROCESSING", None, NOW))

    def test_get_status_of_a_missing_document(self) -> None:
        with self.assertRaises(DocumentNotFoundError):
            self.service.get_status(5)


class ListTest(ServiceTestCase):
    def last_query(self) -> tuple[str, dict]:
        sql, params = self.db.calls[-1]
        return sql, params

    def test_without_conditions_lists_everything_newest_first(self) -> None:
        self.register("a.pdf", "tech")
        self.register("b.pdf", "secure")

        rows = self.service.list_documents()

        sql, params = self.last_query()
        self.assertNotIn("WHERE", sql)
        self.assertTrue(sql.endswith("ORDER BY d.upload_at DESC, d.id DESC"))
        self.assertEqual(params, {})
        self.assertEqual([type(r) for r in rows], [DocumentRow, DocumentRow])
        self.assertFalse(hasattr(rows[0], "file_path"))

    def test_conditions_are_joined_with_and_and_passed_as_parameters(self) -> None:
        self.service.list_documents(doc_type="tech", department_id=3, status="FAILED", keyword="로프")

        sql, params = self.last_query()
        for part in ("d.document_type = :doc_type", "d.department_id = :department_id", "d.status = :status", "LIKE :keyword"):
            self.assertIn(part, sql)
        self.assertEqual(sql.count(" AND "), 3)
        self.assertEqual(params, {"doc_type": "tech", "department_id": 3, "status": "FAILED", "keyword": "%로프%"})
        self.assertNotIn("로프", sql)  # 값은 SQL 문자열에 이어 붙이지 않는다

    def test_keyword_wildcards_are_searched_literally(self) -> None:
        self.service.list_documents(keyword=" 50%_a! ")

        self.assertEqual(self.last_query()[1]["keyword"], "%50!%!_a!!%")

    def test_blank_keyword_is_ignored(self) -> None:
        self.service.list_documents(keyword="   ")

        self.assertNotIn("WHERE", self.last_query()[0])

    def test_unknown_filters_are_rejected_before_querying(self) -> None:
        with self.assertRaises(ValueError):
            self.service.list_documents(doc_type="SPEC")
        with self.assertRaises(ValueError):
            self.service.list_documents(status="PENDING")
        self.assertEqual(self.db.calls, [])

    def test_an_injection_attempt_in_the_keyword_stays_a_parameter(self) -> None:
        self.service.list_documents(keyword="'; DROP TABLE documents_info; --")

        sql, params = self.last_query()
        self.assertNotIn("DROP", sql)
        self.assertIn("DROP TABLE", params["keyword"])


class SummaryTest(ServiceTestCase):
    def test_empty_summary_has_zero_for_every_key(self) -> None:
        summary = self.service.summary()

        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.by_status, {"PROCESSING": 0, "COMPLETED": 0, "FAILED": 0})
        self.assertEqual(summary.by_type, {"tech": 0, "secure": 0})

    def test_counts_by_status_and_type(self) -> None:
        for index, (doc_type, status) in enumerate([("tech", "COMPLETED"), ("tech", "COMPLETED"), ("secure", "FAILED"), ("secure", "PROCESSING")]):
            self.db.rows.append({
                "id": index + 1, "filename": f"{index}.pdf", "document_type": doc_type, "department_id": 3,
                "status": status, "upload_at": NOW, "updated_at": NOW,
            })

        summary = self.service.summary()

        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.by_status, {"PROCESSING": 1, "COMPLETED": 2, "FAILED": 1})
        self.assertEqual(summary.by_type, {"tech": 2, "secure": 2})


class SetStatusTest(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.document_id = self.register()

    def status(self) -> str:
        return self.db.rows[0]["status"]

    def test_processing_becomes_completed(self) -> None:
        self.service.set_status(self.document_id, "COMPLETED", chunk_count=349)

        self.assertEqual(self.status(), "COMPLETED")
        self.assertEqual(self.service.get_status(self.document_id).status, "COMPLETED")

    def test_processing_becomes_failed(self) -> None:
        self.service.set_status(self.document_id, "FAILED", error="스캔 PDF는 지원하지 않아요")

        self.assertEqual(self.status(), "FAILED")

    def test_chunk_count_and_error_are_only_logged_until_the_columns_exist(self) -> None:
        with self.assertLogs("features.documents.service", level="INFO") as logs:
            self.service.set_status(self.document_id, "COMPLETED", chunk_count=349)

        update = self.db.sql_with("UPDATE")[0][0]
        self.assertNotIn("chunk_count", update)
        self.assertNotIn("error_message", update)
        self.assertIn("chunk_count=349", logs.output[0])

    def test_a_long_error_is_cut_in_the_log(self) -> None:
        with self.assertLogs("features.documents.service", level="INFO") as logs:
            self.service.set_status(self.document_id, "FAILED", error="x" * 1500)

        self.assertIn("x" * 1000, logs.output[0])
        self.assertNotIn("x" * 1001, logs.output[0])

    def test_finished_documents_cannot_change_to_another_status(self) -> None:
        self.service.set_status(self.document_id, "COMPLETED")

        with self.assertRaises(InvalidStatusTransition) as caught:
            self.service.set_status(self.document_id, "FAILED")

        self.assertEqual((caught.exception.current, caught.exception.new), ("COMPLETED", "FAILED"))
        self.assertEqual(self.status(), "COMPLETED")

    def test_failed_documents_cannot_become_completed_or_processing(self) -> None:
        self.service.set_status(self.document_id, "FAILED")

        for new in ("COMPLETED", "PROCESSING"):
            with self.subTest(new=new), self.assertRaises(InvalidStatusTransition):
                self.service.set_status(self.document_id, new)

        self.assertEqual(self.status(), "FAILED")

    def test_repeating_the_same_status_changes_nothing(self) -> None:
        self.service.set_status(self.document_id, "COMPLETED")
        updates = len(self.db.sql_with("UPDATE"))

        self.service.set_status(self.document_id, "COMPLETED", chunk_count=1)

        self.assertEqual(len(self.db.sql_with("UPDATE")), updates)

    def test_setting_processing_while_processing_is_a_no_op(self) -> None:
        self.service.set_status(self.document_id, "PROCESSING")

        self.assertEqual(self.db.sql_with("UPDATE"), [])

    def test_the_update_is_conditioned_on_the_current_status(self) -> None:
        self.service.set_status(self.document_id, "COMPLETED")

        sql, params = self.db.sql_with("UPDATE")[0]
        self.assertIn("AND status = :current", sql)
        self.assertEqual(params, {"status": "COMPLETED", "id": self.document_id, "current": "PROCESSING"})

    def test_another_worker_finishing_first_with_a_different_status_is_reported(self) -> None:
        def other_worker(db: FakeDb) -> None:
            db.rows[0]["status"] = "FAILED"

        self.db.before_update = other_worker

        with self.assertRaises(InvalidStatusTransition) as caught:
            self.service.set_status(self.document_id, "COMPLETED")

        self.assertEqual((caught.exception.current, caught.exception.new), ("FAILED", "COMPLETED"))
        self.assertEqual(self.status(), "FAILED")

    def test_another_worker_finishing_first_with_the_same_status_is_fine(self) -> None:
        def other_worker(db: FakeDb) -> None:
            db.rows[0]["status"] = "COMPLETED"

        self.db.before_update = other_worker

        self.service.set_status(self.document_id, "COMPLETED")

        self.assertEqual(self.status(), "COMPLETED")

    def test_a_document_deleted_during_the_update_raises_not_found(self) -> None:
        self.db.before_update = lambda db: db.rows.clear()

        with self.assertRaises(DocumentNotFoundError):
            self.service.set_status(self.document_id, "COMPLETED")

    def test_missing_document(self) -> None:
        with self.assertRaises(DocumentNotFoundError):
            self.service.set_status(99, "COMPLETED")

    def test_bad_arguments_are_rejected_before_any_change(self) -> None:
        calls_before = len(self.db.calls)
        for args in (
            (0, "COMPLETED", None, None),
            (True, "COMPLETED", None, None),
            (self.document_id, "DONE", None, None),
            (self.document_id, "PENDING", None, None),
            (self.document_id, "COMPLETED", None, -1),
            (self.document_id, "COMPLETED", None, True),
            (self.document_id, "COMPLETED", None, "3"),
            (self.document_id, "FAILED", 123, None),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.service.set_status(*args)

        self.assertEqual(len(self.db.calls), calls_before)
        self.assertEqual(self.status(), "PROCESSING")

    def test_zero_chunks_is_a_valid_count(self) -> None:
        self.service.set_status(self.document_id, "COMPLETED", chunk_count=0)

        self.assertEqual(self.status(), "COMPLETED")


class DeleteTest(ServiceTestCase):
    def test_delete_document_record_removes_only_that_row(self) -> None:
        first, second = self.register("a.pdf"), self.register("b.pdf")

        self.assertTrue(self.service.delete_document_record(first))

        self.assertEqual([r["id"] for r in self.db.rows], [second])

    def test_delete_document_record_is_safe_to_repeat(self) -> None:
        document_id = self.register()

        self.assertTrue(self.service.delete_document_record(document_id))
        self.assertFalse(self.service.delete_document_record(document_id))

    def test_delete_document_record_always_filters_by_id(self) -> None:
        self.service.delete_document_record(5)

        sql, params = self.db.sql_with("DELETE")[0]
        self.assertIn("WHERE id = :id", sql)
        self.assertEqual(params, {"id": 5})

    def test_delete_pdf_removes_the_file_and_is_safe_to_repeat(self) -> None:
        document_id = self.register()

        self.assertTrue(self.service.delete_pdf(document_id))
        self.assertFalse(self.service.delete_pdf(document_id))
        self.assertEqual(self.files(), [])
        self.assertEqual(len(self.db.rows), 1)  # DB 행은 건드리지 않는다

    def test_delete_pdf_works_after_the_row_is_gone(self) -> None:
        document_id = self.register()
        self.service.delete_document_record(document_id)

        self.assertTrue(self.service.delete_pdf(document_id))

    def test_delete_pdf_passes_storage_errors_on(self) -> None:
        document_id = self.register()

        with mock.patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(DocumentStorageError):
                self.service.delete_pdf(document_id)

    def test_bad_ids_are_rejected(self) -> None:
        for bad in (0, -1, True, None, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.service.delete_document_record(bad)
                with self.assertRaises(ValueError):
                    self.service.delete_pdf(bad)

    def test_the_whole_life_of_a_document(self) -> None:
        document_id = self.register()
        self.service.set_status(document_id, "COMPLETED", chunk_count=3)
        self.assertEqual(self.service.get_status(document_id).status, "COMPLETED")

        self.assertTrue(self.service.delete_pdf(document_id))  # 삭제 순서: ChromaDB(정환) → PDF → 행
        self.assertTrue(self.service.delete_document_record(document_id))

        with self.assertRaises(DocumentNotFoundError):
            self.service.get_document(document_id)
        self.assertEqual(self.files(), [])


if __name__ == "__main__":
    unittest.main()
