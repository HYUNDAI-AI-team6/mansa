import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from features.processing.chunk_utils import (
    HARD_MAX_CHARS,
    MAX_CHUNK_CHARS,
    MIN_CHUNK_CHARS,
    pack_lines,
    pack_rows,
    split_text,
)
from features.processing.chunker_tech import chunk_tech
from features.processing.pdf_content import PageContent, PdfContent
from features.processing.pdf_tables import TableBlock

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
ELTRON_PDF = PDF_DIR / "엘트론엘리베이터_기술사양서.pdf"
LUXEN_PDF = PDF_DIR / "Passenger Elevator_LUXEN NEW YZER_2406.pdf"


@dataclass
class FakeDocument:
    id: int = 7
    title: str = "엘트론엘리베이터_기술사양서"
    filename: str = "엘트론엘리베이터_기술사양서.pdf"
    doc_type: str = "tech"


def make_page(page_no: int, body: str, tables: list[TableBlock] | None = None) -> PageContent:
    """본문과 표만 지정해 PageContent를 만든다."""
    return PageContent(page_no=page_no, body_text=body, tables=tables or [], is_low_text=False, image_count=0)


def make_content(*pages: PageContent) -> PdfContent:
    """페이지 목록으로 PdfContent를 만든다."""
    return PdfContent(file_name="a.pdf", page_count=len(pages), pages=list(pages), failed_table_pages=[])


def make_table(rows: list[list[str]], merged: list[list[bool]] | None = None, reliable: bool = True) -> TableBlock:
    """행 목록과 병합 표시로 TableBlock을 만든다. 병합 표시가 없으면 모든 칸이 실제 칸이다."""
    return TableBlock(
        page_no=1,
        table_index=0,
        bbox=(0, 0, 100, 100),
        rows=rows,
        row_count=len(rows),
        col_count=len(rows[0]),
        empty_ratio=0.0,
        is_reliable=reliable,
        merged=merged if merged is not None else [[False] * len(row) for row in rows],
    )


# 엘트론 사양표처럼 머리글이 두 줄이고(Car Inside + W/D), 두 번째 모델의 Speed가 위 칸과 병합된 표
SPEC_ROWS = [
    ["Model No", "Speed", "Car Inside", ""],
    ["", "", "W", "D"],
    ["A100", "30 (60)", "1600", "1800"],
    ["A200", "", "1700", "2000"],
    ["A300", "", "1800", ""],
]
SPEC_MERGED = [
    [False, False, False, True],
    [True, True, False, False],
    [False, False, False, False],
    [False, True, False, False],
    [False, True, False, False],
]


class ModelDetectionTest(unittest.TestCase):
    def test_single_model_adds_prefix_and_metadata(self) -> None:
        page = make_page(3, "ELVRO 3000\n방폭형 화물용 엘리베이터에 관한 설명이다. " * 3)

        chunks = chunk_tech(FakeDocument(), make_content(page), ["ELVRO 3000", "HYDRO 501"])

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["model"], "ELVRO 3000")
        self.assertTrue(chunks[0].text.startswith("[ELVRO 3000]\n"))

    def test_no_models_means_no_model_key(self) -> None:
        chunks = chunk_tech(FakeDocument(), make_content(make_page(3, "ELVRO 3000 소개 문장이 길게 이어진다. " * 3)))

        self.assertNotIn("model", chunks[0].metadata)
        self.assertFalse(chunks[0].text.startswith("["))

    def test_page_without_model_mention_has_no_model(self) -> None:
        chunks = chunk_tech(FakeDocument(), make_content(make_page(3, "공통 안내 문장이 길게 이어진다. " * 5)), ["LUXEN"])

        self.assertNotIn("model", chunks[0].metadata)

    def test_name_match_ignores_case_and_spacing(self) -> None:
        chunks = chunk_tech(
            FakeDocument(), make_content(make_page(3, "new   yzer 모델의\n사양을 설명하는 긴 문장이다. " * 3)), ["NEW YZER"]
        )

        self.assertEqual(chunks[0].metadata["model"], "NEW YZER")

    def test_page_with_two_models_is_duplicated_per_model(self) -> None:
        body = "LUXEN 과 NEW YZER 는 공통 사양을 쓴다. " * 4

        chunks = chunk_tech(FakeDocument(), make_content(make_page(27, body)), ["LUXEN", "NEW YZER"])

        self.assertEqual([c.metadata["model"] for c in chunks], ["LUXEN", "NEW YZER"])
        self.assertEqual([c.metadata["chunk"] for c in chunks], [0, 1])
        self.assertEqual(chunks[0].text.split("\n", 1)[1], chunks[1].text.split("\n", 1)[1])
        self.assertEqual(len({c.chunk_id for c in chunks}), 2)


class BodyChunkTest(unittest.TestCase):
    def test_page_number_lines_are_dropped(self) -> None:
        chunks = chunk_tech(FakeDocument(), make_content(make_page(6, "30\n31\nELVRO 3000 본문 설명이 이어지는 문장이다. 사양은 아래 표와 같다.")))

        self.assertNotIn("\n30\n", "\n" + chunks[0].text + "\n")

    def test_unreadable_glyphs_are_removed_from_body_and_cells(self) -> None:
        body = "ELVRO 3000 본문 설명이 이어지는 문장이다. 사양은 아래와 같다.\n\ue005\ue047\ue037"
        rows = [["Model", "Capacity"], ["A1", "750\ue005"]]

        chunks = chunk_tech(FakeDocument(), make_content(make_page(6, body, [make_table(rows)])), ["ELVRO 3000"])

        self.assertEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertNotRegex(chunk.text, "[\ue000-\uf8ff]")
        self.assertEqual(chunks[1].text, "[ELVRO 3000]\nModel: A1 | Capacity: 750")

    def test_tiny_page_makes_no_chunk(self) -> None:
        self.assertEqual(chunk_tech(FakeDocument(), make_content(make_page(5, "인천국제공항"))), [])

    def test_long_body_is_split_within_limit(self) -> None:
        body = "\n".join(f"제품 설명 문장 {i}번은 엘리베이터의 사양을 길게 설명한다." for i in range(80))

        chunks = chunk_tech(FakeDocument(), make_content(make_page(2, body)))

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks))
        self.assertEqual(sum(c.text.count("번은") for c in chunks), 80)


class TableChunkTest(unittest.TestCase):
    def test_two_row_header_and_merged_speed(self) -> None:
        page = make_page(6, "ELVRO 3000 로프식 화물용 엘리베이터 설명이다.", [make_table(SPEC_ROWS, SPEC_MERGED)])

        chunks = chunk_tech(FakeDocument(), make_content(page), ["ELVRO 3000"])

        table = chunks[-1]
        lines = table.text.splitlines()
        self.assertEqual(lines[0], "[ELVRO 3000]")
        self.assertEqual(
            lines[1], "Model No: A100 | Speed: 30 (60) | Car Inside W: 1600 | Car Inside D: 1800"
        )
        self.assertEqual(
            lines[2], "Model No: A200 | Speed: 30 (60) | Car Inside W: 1700 | Car Inside D: 2000"
        )
        self.assertEqual(table.metadata["model"], "ELVRO 3000")

    def test_truly_empty_cell_is_not_filled(self) -> None:
        page = make_page(6, "ELVRO 3000 설명 문장이다. " * 3, [make_table(SPEC_ROWS, SPEC_MERGED)])

        table = chunk_tech(FakeDocument(), make_content(page), ["ELVRO 3000"])[-1]

        a300 = [line for line in table.text.splitlines() if "A300" in line][0]
        self.assertEqual(a300, "Model No: A300 | Speed: 30 (60) | Car Inside W: 1800")

    def test_empty_cell_without_merge_mark_stays_empty(self) -> None:
        rows = [["Model", "Speed"], ["A1", "30"], ["A2", ""]]

        chunks = chunk_tech(FakeDocument(), make_content(make_page(1, "", [make_table(rows)])))

        self.assertEqual(chunks[0].text, "Model: A1 | Speed: 30\nA2")

    def test_table_without_header_joins_values(self) -> None:
        rows = [["550", "8", "7"], ["600", "9", "8"]]

        chunks = chunk_tech(FakeDocument(), make_content(make_page(1, "", [make_table(rows)])))

        self.assertEqual(chunks[0].text, "550 | 8 | 7\n600 | 9 | 8")

    def test_header_x_letter_is_not_mistaken_for_number(self) -> None:
        rows = [["Model", "Hoistway", ""], ["", "X", "Y"], ["A1", "2500", "2350"]]
        merged = [[False, False, True], [True, False, False], [False, False, False]]

        chunks = chunk_tech(FakeDocument(), make_content(make_page(1, "", [make_table(rows, merged)])))

        self.assertEqual(chunks[0].text, "Model: A1 | Hoistway X: 2500 | Hoistway Y: 2350")

    def test_unreliable_table_is_skipped(self) -> None:
        page = make_page(1, "", [make_table(SPEC_ROWS, SPEC_MERGED, reliable=False)])

        self.assertEqual(chunk_tech(FakeDocument(), make_content(page)), [])

    def test_long_table_is_split_and_model_prefix_repeats(self) -> None:
        rows = [["Model", "Capacity", "Note"]] + [[f"M{i}", "750", "설명" * 50] for i in range(40)]
        page = make_page(6, "ELVRO 3000 제품 설명 문장이다. " * 3, [make_table(rows)])

        chunks = chunk_tech(FakeDocument(), make_content(page), ["ELVRO 3000"])

        tables = [c for c in chunks if "Model: M" in c.text]
        self.assertGreater(len(tables), 1)
        self.assertTrue(all(c.text.startswith("[ELVRO 3000]\n") for c in tables))
        self.assertTrue(all(len(c.text) <= MAX_CHUNK_CHARS + 20 for c in tables))
        self.assertEqual(sum(c.text.count("Model: M") for c in tables), 40)

    def test_body_chunks_come_before_table_chunks(self) -> None:
        page = make_page(6, "ELVRO 3000 본문 설명이 이어진다. " * 3, [make_table(SPEC_ROWS, SPEC_MERGED)])

        chunks = chunk_tech(FakeDocument(), make_content(page), ["ELVRO 3000"])

        self.assertEqual([c.metadata["chunk"] for c in chunks], [0, 1])
        self.assertIn("Model No: A100", chunks[1].text)


class ChunkUtilsTest(unittest.TestCase):
    def test_pack_lines_merges_short_last_chunk(self) -> None:
        lines = ["가" * 400, "나" * 400, "다" * 400, "라" * 50]

        texts = pack_lines(lines)

        self.assertEqual(len(texts), 2)
        self.assertTrue(texts[-1].endswith("라" * 50))
        self.assertTrue(all(len(t) <= HARD_MAX_CHARS for t in texts))

    def test_pack_lines_keeps_short_last_chunk_when_merge_would_exceed(self) -> None:
        texts = pack_lines(["가" * 1190, "나" * 250])

        self.assertEqual(len(texts), 2)

    def test_pack_rows_repeats_title_and_reports_first_clause(self) -> None:
        rows = [(f"행{i} " + "값" * 90, f"5.{i}") for i in range(30)]

        items = pack_rows(rows, "[ 표 1 ]")

        self.assertGreater(len(items), 1)
        self.assertTrue(all(text.startswith("[ 표 1 ]\n") for text, _ in items))
        self.assertEqual(items[0][1], "5.0")
        self.assertTrue(all(len(text) <= MAX_CHUNK_CHARS for text, _ in items))

    def test_split_text_cuts_long_sentence(self) -> None:
        pieces = split_text("가" * 3200)

        self.assertTrue(all(len(p) <= HARD_MAX_CHARS for p in pieces))
        self.assertEqual(sum(len(p) for p in pieces), 3200)


@unittest.skipUnless(ELTRON_PDF.is_file() and LUXEN_PDF.is_file(), "data/pdfs/ pdfs not found")
class RealTechPdfTest(unittest.TestCase):
    """data/pdfs/ 의 실제 기술사양서 확인. 원본은 Git에 없으므로 파일이 있을 때만 실행한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from features.processing.pdf_content import extract_pdf_content

        cls.eltron = chunk_tech(
            FakeDocument(), extract_pdf_content(ELTRON_PDF), ["ELVRO 3000", "HYDRO 501"]
        )
        cls.luxen = chunk_tech(
            FakeDocument(1, "LUXEN", "LUXEN.pdf"), extract_pdf_content(LUXEN_PDF), ["LUXEN", "NEW YZER"]
        )

    def test_ids_are_unique_and_within_limit(self) -> None:
        for chunks in (self.eltron, self.luxen):
            ids = [c.chunk_id for c in chunks]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(len(c.text) <= HARD_MAX_CHARS for c in chunks))
            self.assertTrue(all(c.text.strip() for c in chunks))

    def test_eltron_table_header_values_and_merged_speed(self) -> None:
        page6 = [c for c in self.eltron if c.metadata["page"] == 6 and "Model No: " in c.text]
        text = "\n".join(c.text for c in page6)

        self.assertTrue(all(c.metadata["model"] == "ELVRO 3000" for c in page6))
        self.assertIn("Model No: GF207632US | Capacity (㎏): 750 | Speed (M/min): 30 (60) | Car Inside W: 1600", text)
        row = [line for line in text.splitlines() if "GF210032US" in line][0]
        self.assertIn("Speed (M/min): 30 (60)", row)

    def test_eltron_models_follow_page_titles(self) -> None:
        by_page = {c.metadata["page"]: c.metadata.get("model") for c in self.eltron if c.metadata["page"] in (3, 7, 8, 10)}

        self.assertEqual(by_page, {3: "ELVRO 3000", 7: "HYDRO 501", 8: "HYDRO 501", 10: "HYDRO 501"})

    def test_no_unreadable_glyphs_in_chunks(self) -> None:
        for chunks in (self.eltron, self.luxen):
            self.assertEqual([c.chunk_id for c in chunks if re.search("[\ue000-\uf8ff]", c.text)], [])

    def test_eltron_photo_only_page_has_no_chunk(self) -> None:
        self.assertNotIn(5, {c.metadata["page"] for c in self.eltron})

    def test_luxen_spec_tables_follow_page_models(self) -> None:
        def models(page: int) -> set[str]:
            return {c.metadata["model"] for c in self.luxen if c.metadata["page"] == page and "model" in c.metadata}

        self.assertEqual(models(22), {"LUXEN"})
        self.assertEqual(models(24), {"NEW YZER"})
        self.assertEqual(models(27), {"LUXEN", "NEW YZER"})
        self.assertEqual(models(26), set())

    def test_luxen_shared_page_is_duplicated_per_model(self) -> None:
        page27 = [c for c in self.luxen if c.metadata["page"] == 27]
        by_model = {m: [c.text.split("\n", 1)[1] for c in page27 if c.metadata.get("model") == m] for m in ("LUXEN", "NEW YZER")}

        self.assertEqual(by_model["LUXEN"], by_model["NEW YZER"])


if __name__ == "__main__":
    unittest.main()
