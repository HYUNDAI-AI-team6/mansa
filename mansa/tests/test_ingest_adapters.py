import tempfile
import unittest
from pathlib import Path

import pymupdf

from features.processing.adapters import extract_content
from features.processing.pdf_content import PdfContent
from features.processing.pdf_text import PdfExtractionError, ScannedPdfError
from features.processing.pipeline import IngestError


def make_pdf(path: Path, page_texts: list[str]) -> Path:
    """페이지마다 주어진 글자를 넣은 PDF를 만든다. 빈 문자열이면 글자 없는 페이지다."""
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


class ExtractContentWithStubTest(unittest.TestCase):
    def test_returns_the_extractor_result(self):
        sentinel = object()
        self.assertIs(extract_content("a.pdf", extractor=lambda path: sentinel), sentinel)

    def test_passes_the_path_to_the_extractor(self):
        seen = []
        extract_content("a.pdf", extractor=lambda path: seen.append(path))
        self.assertEqual(seen, ["a.pdf"])

    def test_scanned_pdf_becomes_a_user_facing_message(self):
        def extractor(path):
            raise ScannedPdfError("scanned pdf is not supported: a.pdf")

        with self.assertRaises(IngestError) as caught:
            extract_content("a.pdf", extractor=extractor)
        self.assertEqual(str(caught.exception), "스캔 PDF는 지원하지 않아요")
        self.assertIsInstance(caught.exception.__cause__, ScannedPdfError)

    def test_unreadable_pdf_becomes_a_user_facing_message(self):
        def extractor(path):
            raise PdfExtractionError("cannot open pdf: a.pdf")

        with self.assertRaises(IngestError) as caught:
            extract_content("a.pdf", extractor=extractor)
        self.assertEqual(str(caught.exception), "PDF를 열 수 없어요")

    def test_other_errors_are_not_converted(self):
        def extractor(path):
            raise KeyError("bug")

        with self.assertRaises(KeyError):
            extract_content("a.pdf", extractor=extractor)


class ExtractContentWithRealPdfTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def test_text_pdf_is_extracted(self):
        text = "Brake inspection is done monthly and logged. " * 3
        path = make_pdf(self.root / "text.pdf", [text, text])
        content = extract_content(str(path))
        self.assertIsInstance(content, PdfContent)
        self.assertEqual(content.page_count, 2)

    def test_pdf_without_text_is_reported_as_scanned(self):
        path = make_pdf(self.root / "blank.pdf", ["", ""])
        with self.assertRaises(IngestError) as caught:
            extract_content(str(path))
        self.assertEqual(str(caught.exception), "스캔 PDF는 지원하지 않아요")

    def test_missing_file_is_reported_as_unreadable(self):
        with self.assertRaises(IngestError) as caught:
            extract_content(str(self.root / "missing.pdf"))
        self.assertEqual(str(caught.exception), "PDF를 열 수 없어요")

    def test_non_pdf_file_is_reported_as_unreadable(self):
        path = self.root / "fake.pdf"
        path.write_bytes(b"not a pdf at all")
        with self.assertRaises(IngestError) as caught:
            extract_content(str(path))
        self.assertEqual(str(caught.exception), "PDF를 열 수 없어요")


if __name__ == "__main__":
    unittest.main()
