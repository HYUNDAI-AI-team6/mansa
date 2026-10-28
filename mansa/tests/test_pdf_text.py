import tempfile
import unittest
from pathlib import Path

import pymupdf

from features.processing.pdf_text import (
    MIN_TEXT_CHARS,
    PdfExtractionError,
    ScannedPdfError,
    extract_pdf_text,
)

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
LUXEN_PDF = PDF_DIR / "Passenger Elevator_LUXEN NEW YZER_2406.pdf"
ELTRON_PDF = PDF_DIR / "엘트론엘리베이터_기술사양서.pdf"
SAFETY_PDF = PDF_DIR / "안전기준.pdf"

LONG_TEXT = "Model LUXEN rated load 1000 kg speed 105 m/min " * 3


def make_pdf(path: Path, pages: list[str | None], **save_kwargs) -> Path:
    """페이지마다 텍스트(str) 또는 이미지만(None) 넣은 임시 PDF를 만든다."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text is None:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
            page.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=pix)
        else:
            page.insert_textbox(pymupdf.Rect(50, 50, 500, 300), text)
    doc.save(path, **save_kwargs)
    doc.close()
    return path


class ExtractPdfTextTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_extracts_each_page_in_order(self) -> None:
        pdf = make_pdf(self.tmp / "a.pdf", [LONG_TEXT + "FIRST", LONG_TEXT + "SECOND"])

        result = extract_pdf_text(pdf)

        self.assertEqual(result.file_name, "a.pdf")
        self.assertEqual(result.page_count, 2)
        self.assertEqual([p.page_no for p in result.pages], [1, 2])
        self.assertIn("FIRST", result.pages[0].text)
        self.assertIn("SECOND", result.pages[1].text)
        self.assertEqual(result.low_text_pages, [])

    def test_marks_image_only_page_as_low_text(self) -> None:
        pdf = make_pdf(self.tmp / "b.pdf", [LONG_TEXT, LONG_TEXT, None])

        result = extract_pdf_text(pdf)

        self.assertEqual(result.low_text_pages, [3])
        self.assertTrue(result.pages[2].is_low_text)
        self.assertEqual(result.pages[2].image_count, 1)
        self.assertGreaterEqual(result.pages[0].char_count, MIN_TEXT_CHARS)

    def test_rejects_scanned_pdf(self) -> None:
        pdf = make_pdf(self.tmp / "scan.pdf", [None, None, None])

        with self.assertRaises(ScannedPdfError):
            extract_pdf_text(pdf)

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(PdfExtractionError):
            extract_pdf_text(self.tmp / "missing.pdf")

    def test_rejects_non_pdf_file(self) -> None:
        fake = self.tmp / "fake.pdf"
        fake.write_text("this is not a pdf", encoding="utf-8")

        with self.assertRaises(PdfExtractionError):
            extract_pdf_text(fake)

    def test_rejects_encrypted_pdf(self) -> None:
        pdf = make_pdf(
            self.tmp / "enc.pdf",
            [LONG_TEXT],
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="user",
            owner_pw="owner",
        )

        with self.assertRaises(PdfExtractionError):
            extract_pdf_text(pdf)


@unittest.skipUnless(PDF_DIR.is_dir(), "data/pdfs/ not found")
class RealPdfTest(unittest.TestCase):
    """data/pdfs/ 의 실제 PDF 3개 확인. 원본은 Git에 없으므로 파일이 있을 때만 실행한다."""

    @unittest.skipUnless(LUXEN_PDF.is_file(), "LUXEN pdf not found")
    def test_luxen_catalog(self) -> None:
        result = extract_pdf_text(LUXEN_PDF)

        self.assertEqual(result.page_count, 30)
        self.assertEqual(result.low_text_pages, [1])
        joined = "".join(p.text for p in result.pages)
        self.assertIn("LUXEN", joined)
        self.assertIn("NEW YZER", joined)
        self.assertIn("현대엘리베이터", joined)

    @unittest.skipUnless(ELTRON_PDF.is_file(), "Eltron pdf not found")
    def test_eltron_spec(self) -> None:
        result = extract_pdf_text(ELTRON_PDF)

        self.assertEqual(result.page_count, 10)
        self.assertEqual(result.low_text_pages, [5])
        joined = "".join(p.text for p in result.pages)
        self.assertIn("HYDRO 501", joined)
        self.assertIn("Model No", joined)

    @unittest.skipUnless(SAFETY_PDF.is_file(), "safety pdf not found")
    def test_safety_standard(self) -> None:
        result = extract_pdf_text(SAFETY_PDF)

        self.assertEqual(result.page_count, 211)
        self.assertEqual(result.low_text_pages, [])
        joined = "".join(p.text for p in result.pages)
        self.assertIn("KC 2050-51", joined)
        self.assertIn("6.6.4.1.2", joined)
        self.assertNotIn("�", joined)


if __name__ == "__main__":
    unittest.main()
