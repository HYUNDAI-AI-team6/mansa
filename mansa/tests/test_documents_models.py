import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime

from features.documents.errors import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    InvalidStatusTransition,
)
from features.documents.models import (
    DOC_TYPES,
    STATUSES,
    Document,
    DocumentRow,
    DocumentSummary,
    title_of,
)

NOW = datetime(2026, 10, 29, 12, 0, 0)


def row_values() -> dict:
    return dict(
        id=1, title="안전기준", filename="안전기준.pdf", doc_type="secure", department_id=3,
        department_name="안전관리팀", status="PROCESSING", chunk_count=None, upload_at=NOW, updated_at=NOW,
    )


class TitleOfTest(unittest.TestCase):
    def test_removes_the_pdf_extension(self) -> None:
        self.assertEqual(title_of("안전기준.pdf"), "안전기준")
        self.assertEqual(title_of("Manual v2.PDF"), "Manual v2")

    def test_keeps_names_without_the_extension(self) -> None:
        self.assertEqual(title_of("안전기준"), "안전기준")
        self.assertEqual(title_of("a.pdf.txt"), "a.pdf.txt")

    def test_removes_only_the_last_extension(self) -> None:
        self.assertEqual(title_of("a.pdf.pdf"), "a.pdf")


class DocumentTest(unittest.TestCase):
    def test_document_has_the_row_fields_and_a_file_path(self) -> None:
        document = Document(**row_values(), file_path="/data/secure/1.pdf")

        self.assertEqual(document.title, "안전기준")
        self.assertEqual(document.file_path, "/data/secure/1.pdf")
        self.assertIsInstance(document, DocumentRow)

    def test_row_does_not_have_a_file_path(self) -> None:
        self.assertFalse(hasattr(DocumentRow(**row_values()), "file_path"))

    def test_values_cannot_be_changed(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            DocumentRow(**row_values()).status = "COMPLETED"


class SummaryTest(unittest.TestCase):
    def test_empty_summary_has_every_key_at_zero(self) -> None:
        summary = DocumentSummary(total=0)

        self.assertEqual(summary.by_status, {"PROCESSING": 0, "COMPLETED": 0, "FAILED": 0})
        self.assertEqual(summary.by_type, {"tech": 0, "secure": 0})

    def test_default_dicts_are_not_shared(self) -> None:
        first, second = DocumentSummary(total=0), DocumentSummary(total=0)
        first.by_status["COMPLETED"] = 5

        self.assertEqual(second.by_status["COMPLETED"], 0)

    def test_constants(self) -> None:
        self.assertEqual(DOC_TYPES, ("tech", "secure"))
        self.assertEqual(STATUSES, ("PROCESSING", "COMPLETED", "FAILED"))


class ErrorsTest(unittest.TestCase):
    def test_duplicate_error_carries_the_existing_id(self) -> None:
        self.assertEqual(DuplicateDocumentError(7).document_id, 7)
        self.assertIsNone(DuplicateDocumentError().document_id)

    def test_not_found_error_carries_the_id(self) -> None:
        self.assertEqual(DocumentNotFoundError(9).document_id, 9)
        self.assertIn("9", str(DocumentNotFoundError(9)))

    def test_invalid_transition_carries_both_statuses(self) -> None:
        error = InvalidStatusTransition("COMPLETED", "FAILED")

        self.assertEqual((error.current, error.new), ("COMPLETED", "FAILED"))
        self.assertIn("COMPLETED", str(error))


if __name__ == "__main__":
    unittest.main()
