import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from features.processing.pdf_tables import extract_pdf_tables
from features.processing.pdf_text import PdfExtractionError

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
LUXEN_PDF = PDF_DIR / "Passenger Elevator_LUXEN NEW YZER_2406.pdf"
ELTRON_PDF = PDF_DIR / "엘트론엘리베이터_기술사양서.pdf"
SAFETY_PDF = PDF_DIR / "안전기준.pdf"

GRID = [["Model", "Load", "Speed"], ["A100", "1000", "60"], ["B200", "1600", "105"]]


def draw_table(page: pymupdf.Page, grid: list[list[str]]) -> None:
    """선으로 그린 격자 표를 페이지에 넣는다."""
    x0, y0, w, h = 50, 100, 120, 30
    rows, cols = len(grid), len(grid[0])
    # draw_line으로 그린 선은 find_tables()가 선으로 인식하지 못해 열이 어긋나므로,
    # 선을 1pt 두께의 채운 사각형으로 그린다.
    for r in range(rows + 1):
        page.draw_rect(
            pymupdf.Rect(x0, y0 + r * h - 0.5, x0 + cols * w, y0 + r * h + 0.5), color=None, fill=(0, 0, 0)
        )
    for c in range(cols + 1):
        page.draw_rect(
            pymupdf.Rect(x0 + c * w - 0.5, y0, x0 + c * w + 0.5, y0 + rows * h), color=None, fill=(0, 0, 0)
        )
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            page.insert_text((x0 + c * w + 5, y0 + r * h + 20), value, fontsize=11)


def make_pdf(path: Path, with_table: list[bool]) -> Path:
    """페이지마다 표 유무를 지정해 임시 PDF를 만든다."""
    doc = pymupdf.open()
    for has_table in with_table:
        page = doc.new_page()
        page.insert_text((50, 60), "plain text line", fontsize=11)
        if has_table:
            draw_table(page, GRID)
    doc.save(path)
    doc.close()
    return path


class ExtractPdfTablesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_extracts_table_rows_and_page_numbers(self) -> None:
        pdf = make_pdf(self.tmp / "t.pdf", [False, True])

        result = extract_pdf_tables(pdf)

        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.table_pages, [2])
        table = result.tables_on_page(2)[0]
        self.assertEqual(table.rows, GRID)
        self.assertEqual((table.row_count, table.col_count), (3, 3))
        self.assertEqual(table.empty_ratio, 0.0)
        self.assertEqual(result.tables_on_page(1), [])

    def test_pdf_without_tables_returns_empty_list(self) -> None:
        result = extract_pdf_tables(make_pdf(self.tmp / "n.pdf", [False, False]))

        self.assertEqual(result.tables, [])
        self.assertEqual(result.failed_pages, [])

    def test_records_page_when_find_tables_fails(self) -> None:
        pdf = make_pdf(self.tmp / "f.pdf", [True, True])
        real = pymupdf.Page.find_tables

        def flaky(page, *args, **kwargs):
            if page.number == 0:
                raise RuntimeError("boom")
            return real(page, *args, **kwargs)

        with mock.patch.object(pymupdf.Page, "find_tables", flaky):
            result = extract_pdf_tables(pdf)

        self.assertEqual(result.failed_pages, [1])
        self.assertEqual(result.table_pages, [2])

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(PdfExtractionError):
            extract_pdf_tables(self.tmp / "missing.pdf")

    def test_rejects_non_pdf_file(self) -> None:
        fake = self.tmp / "fake.pdf"
        fake.write_text("this is not a pdf", encoding="utf-8")

        with self.assertRaises(PdfExtractionError):
            extract_pdf_tables(fake)

    def test_rejects_encrypted_pdf(self) -> None:
        pdf = make_pdf(self.tmp / "src.pdf", [True])
        enc = self.tmp / "enc.pdf"
        doc = pymupdf.open(pdf)
        doc.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
        doc.close()

        with self.assertRaises(PdfExtractionError):
            extract_pdf_tables(enc)


@unittest.skipUnless(PDF_DIR.is_dir(), "data/pdfs/ not found")
class RealPdfTablesTest(unittest.TestCase):
    """data/pdfs/ 의 실제 PDF 3개 확인. 원본은 Git에 없으므로 파일이 있을 때만 실행한다."""

    @unittest.skipUnless(ELTRON_PDF.is_file(), "Eltron pdf not found")
    def test_eltron_spec_tables(self) -> None:
        result = extract_pdf_tables(ELTRON_PDF)

        self.assertEqual(result.page_count, 10)
        self.assertEqual(result.table_pages, [6, 7, 8, 9, 10])
        self.assertEqual(len(result.tables), 7)
        self.assertEqual(result.failed_pages, [])
        first = result.tables_on_page(6)[0]
        self.assertEqual(first.rows[0][0], "Model No")
        self.assertIn("GF207632US", [row[0] for row in first.rows])

    @unittest.skipUnless(LUXEN_PDF.is_file(), "LUXEN pdf not found")
    def test_luxen_spec_tables(self) -> None:
        result = extract_pdf_tables(LUXEN_PDF)

        self.assertEqual(result.page_count, 30)
        self.assertEqual(result.table_pages, [22, 23, 24, 25, 26, 27])
        self.assertEqual(len(result.tables), 7)
        self.assertEqual(result.failed_pages, [])

    @unittest.skipUnless(SAFETY_PDF.is_file(), "safety pdf not found")
    def test_safety_standard_tables(self) -> None:
        result = extract_pdf_tables(SAFETY_PDF)

        self.assertEqual(result.page_count, 211)
        self.assertEqual(len(result.tables), 47)
        self.assertEqual(len(result.table_pages), 39)
        self.assertEqual(result.failed_pages, [])
        self.assertEqual(result.tables_on_page(148)[0].rows[0][0], "기준항목")


if __name__ == "__main__":
    unittest.main()
