import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from features.processing.pdf_tables import (
    extract_pdf_tables,
    is_reliable_table,
    restore_split_number,
)
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


class RestoreSplitNumberTest(unittest.TestCase):
    BOX = (0, 0, 50, 20)
    WORDS = [(5, 5, 40, 15, "0.37", 0, 0, 0), (200, 5, 240, 15, "9.99", 1, 0, 0)]

    def test_restores_number_from_words_in_cell(self) -> None:
        self.assertEqual(restore_split_number("0 37\n.", self.BOX, self.WORDS), "0.37")

    def test_restores_number_with_trailing_comma(self) -> None:
        words = [(5, 5, 40, 15, "1,000", 0, 0, 0)]
        self.assertEqual(restore_split_number("1 000\n,", self.BOX, words), "1,000")

    def test_leaves_text_cell_unchanged(self) -> None:
        self.assertEqual(restore_split_number("문장입니다\n.", self.BOX, self.WORDS), "문장입니다\n.")

    def test_leaves_normal_number_unchanged(self) -> None:
        self.assertEqual(restore_split_number("0 37", self.BOX, self.WORDS), "0 37")

    def test_keeps_original_when_no_word_in_cell(self) -> None:
        self.assertEqual(restore_split_number("0 37\n.", (100, 100, 150, 120), self.WORDS), "0 37\n.")

    def test_keeps_original_when_cell_box_missing(self) -> None:
        self.assertEqual(restore_split_number("0 37\n.", None, self.WORDS), "0 37\n.")


class IsReliableTableTest(unittest.TestCase):
    def test_normal_table_is_reliable(self) -> None:
        self.assertTrue(is_reliable_table(10, 5, 0.2))

    def test_too_many_empty_cells_is_unreliable(self) -> None:
        self.assertFalse(is_reliable_table(10, 5, 0.51))

    def test_half_empty_is_still_reliable(self) -> None:
        self.assertTrue(is_reliable_table(10, 5, 0.5))

    def test_tiny_table_is_unreliable(self) -> None:
        self.assertFalse(is_reliable_table(2, 2, 0.0))
        self.assertFalse(is_reliable_table(1, 2, 0.0))

    def test_two_rows_with_many_columns_is_reliable(self) -> None:
        self.assertTrue(is_reliable_table(2, 6, 0.0))


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

    @unittest.skipUnless(SAFETY_PDF.is_file(), "safety pdf not found")
    def test_safety_split_numbers_are_restored(self) -> None:
        result = extract_pdf_tables(SAFETY_PDF)

        cells = [c for c in (x for r in result.tables_on_page(51)[0].rows for x in r)]
        self.assertIn("0.37", cells)
        self.assertIn("2.20", cells)
        split = re.compile(r"\n[.,]( [.,])*\s*$")
        leftover = [
            c
            for t in result.tables
            for row in t.rows
            for c in row
            if split.search(c) and not re.search(r"[A-Za-z가-힣]", c)
        ]
        self.assertEqual(leftover, [])

    @unittest.skipUnless(
        SAFETY_PDF.is_file() and ELTRON_PDF.is_file() and LUXEN_PDF.is_file(), "pdfs not found"
    )
    def test_unreliable_tables_on_real_pdfs(self) -> None:
        bad = {
            ELTRON_PDF: [(9, 0)],
            LUXEN_PDF: [(26, 0), (27, 0)],
            SAFETY_PDF: [(193, 0), (197, 0), (199, 0)],
        }
        for pdf, expected in bad.items():
            result = extract_pdf_tables(pdf)
            found = [(t.page_no, t.table_index) for t in result.tables if not t.is_reliable]
            self.assertEqual(found, expected, pdf.name)


if __name__ == "__main__":
    unittest.main()
