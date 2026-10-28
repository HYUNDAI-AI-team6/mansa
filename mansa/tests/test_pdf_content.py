import re
import tempfile
import unittest
from pathlib import Path

import pymupdf

from features.processing.pdf_content import extract_pdf_content
from features.processing.pdf_text import ScannedPdfError, extract_pdf_text
from test_pdf_tables import draw_table

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
LUXEN_PDF = PDF_DIR / "Passenger Elevator_LUXEN NEW YZER_2406.pdf"
ELTRON_PDF = PDF_DIR / "엘트론엘리베이터_기술사양서.pdf"
SAFETY_PDF = PDF_DIR / "안전기준.pdf"

BIG_GRID = [["Model", "Load", "Speed"], ["A100", "1000", "60"], ["B200", "1600", "105"]]
SMALL_GRID = [["Alpha", "Beta"], ["Gamma", "Delta"]]
INTRO = "Introduction paragraph about the elevator specification and its safety rules."


def make_pdf(path: Path, grid: list[list[str]]) -> Path:
    """소개 문장 한 줄과 표 하나가 있는 한 페이지짜리 임시 PDF를 만든다."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), INTRO, fontsize=9)
    draw_table(page, grid)
    doc.save(path)
    doc.close()
    return path


class ExtractPdfContentTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_reliable_table_text_is_removed_from_body(self) -> None:
        result = extract_pdf_content(make_pdf(self.tmp / "big.pdf", BIG_GRID))

        page = result.pages[0]
        self.assertEqual(page.tables[0].rows, BIG_GRID)
        self.assertTrue(page.tables[0].is_reliable)
        self.assertIn("Introduction paragraph", page.body_text)
        for cell in ("A100", "1600", "Speed"):
            self.assertNotIn(cell, page.body_text)

    def test_unreliable_table_text_stays_in_body(self) -> None:
        result = extract_pdf_content(make_pdf(self.tmp / "small.pdf", SMALL_GRID))

        page = result.pages[0]
        self.assertEqual(len(page.tables), 1)
        self.assertFalse(page.tables[0].is_reliable)
        for cell in ("Alpha", "Delta", "Introduction paragraph"):
            self.assertIn(cell, page.body_text)

    def test_page_without_table_keeps_raw_text(self) -> None:
        pdf = self.tmp / "plain.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 500, 300), INTRO * 2)
        doc.save(pdf)
        doc.close()

        result = extract_pdf_content(pdf)

        self.assertEqual(result.pages[0].body_text, extract_pdf_text(pdf).pages[0].text)
        self.assertEqual(result.pages[0].tables, [])

    def test_scanned_pdf_is_rejected(self) -> None:
        pdf = self.tmp / "scan.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
        page.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=pix)
        doc.save(pdf)
        doc.close()

        with self.assertRaises(ScannedPdfError):
            extract_pdf_content(pdf)


@unittest.skipUnless(
    SAFETY_PDF.is_file() and ELTRON_PDF.is_file() and LUXEN_PDF.is_file(), "data/pdfs/ pdfs not found"
)
class RealPdfContentTest(unittest.TestCase):
    """data/pdfs/ 의 실제 PDF 3개 확인. 원본은 Git에 없으므로 파일이 있을 때만 실행한다."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.eltron = extract_pdf_content(ELTRON_PDF)
        cls.luxen = extract_pdf_content(LUXEN_PDF)
        cls.safety = extract_pdf_content(SAFETY_PDF)

    def test_page_and_table_counts_match_extraction(self) -> None:
        self.assertEqual([c.page_count for c in (self.eltron, self.luxen, self.safety)], [10, 30, 211])
        counts = [sum(len(p.tables) for p in c.pages) for c in (self.eltron, self.luxen, self.safety)]
        self.assertEqual(counts, [7, 7, 47])
        for content in (self.eltron, self.luxen, self.safety):
            self.assertEqual(content.failed_table_pages, [])

    def test_eltron_table_values_move_out_of_body(self) -> None:
        page = self.eltron.pages[5]

        self.assertIn("GF207632US", [row[0] for row in page.tables[0].rows])
        self.assertNotIn("GF207632US", page.body_text)
        self.assertIn("ELVRO 3000", page.body_text)

    def test_unreliable_table_keeps_body_text(self) -> None:
        raw = extract_pdf_text(LUXEN_PDF).pages[26].text

        page = self.luxen.pages[26]

        self.assertFalse(page.tables[0].is_reliable)
        self.assertEqual(page.body_text, raw)

    def test_safety_table_numbers_are_restored(self) -> None:
        cells = [c for r in self.safety.pages[50].tables[0].rows for c in r]

        self.assertIn("0.37", cells)

    def test_body_text_has_no_split_numbers(self) -> None:
        split = re.compile(r"\d\n[.,]")
        for content in (self.eltron, self.luxen, self.safety):
            bad = [p.page_no for p in content.pages if split.search(p.body_text)]
            self.assertEqual(bad, [], content.file_name)


if __name__ == "__main__":
    unittest.main()
