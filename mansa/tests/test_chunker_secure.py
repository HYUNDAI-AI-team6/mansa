import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from features.processing.chunk_utils import (
    HARD_MAX_CHARS,
    MAX_CHUNK_CHARS,
    MIN_CHUNK_CHARS,
    clean_cell,
    strip_private_use,
)
from features.processing.chunker_secure import chunk_secure
from features.processing.models import Chunk
from features.processing.pdf_content import PageContent, PdfContent
from features.processing.pdf_tables import TableBlock

SAFETY_PDF = Path(__file__).resolve().parents[2] / "data" / "pdfs" / "안전기준.pdf"


@dataclass
class FakeDocument:
    id: int = 12
    title: str = "안전기준"
    filename: str = "안전기준.pdf"
    doc_type: str = "secure"


def make_page(page_no: int, body: str, tables: list[TableBlock] | None = None) -> PageContent:
    """본문과 표만 지정해 PageContent를 만든다."""
    return PageContent(page_no=page_no, body_text=body, tables=tables or [], is_low_text=False, image_count=0)


def make_content(*pages: PageContent) -> PdfContent:
    """페이지 목록으로 PdfContent를 만든다."""
    return PdfContent(file_name="안전기준.pdf", page_count=len(pages), pages=list(pages), failed_table_pages=[])


def make_table(rows: list[list[str]], reliable: bool = True) -> TableBlock:
    """행 목록으로 TableBlock을 만든다."""
    return TableBlock(
        page_no=1,
        table_index=0,
        bbox=(0, 0, 100, 100),
        rows=rows,
        row_count=len(rows),
        col_count=len(rows[0]),
        empty_ratio=0.0,
        is_reliable=reliable,
    )


def sentence(label: str, size: int) -> str:
    """size자 안팎의 한 줄 문장을 만든다."""
    text = (f"{label} " + "승강로의 안전 요구사항을 만족하여야 한다. " * 200)[:size].rstrip()
    assert len(text) >= size - 1, "sentence()가 요청한 길이보다 짧게 만들어졌다"
    return text


class UnreadableGlyphTest(unittest.TestCase):
    def test_removes_private_use_characters_and_collapses_spaces(self) -> None:
        self.assertEqual(strip_private_use("여기서, \ue005\ue047 F 는 \ue0eb 전체 수직력"), "여기서, F 는 전체 수직력")

    def test_drops_lines_left_without_letters_or_digits(self) -> None:
        text = "본문 첫 줄\n\ue03d\ue0f2 ± \ue06d\n\ue0fa\n본문 마지막 줄"

        self.assertEqual(strip_private_use(text), "본문 첫 줄\n본문 마지막 줄")

    def test_keeps_lines_without_private_use_untouched(self) -> None:
        text = "6.1.8.5  피트 바닥은   4배를 지지한다.\n± 0.5 m"

        self.assertEqual(strip_private_use(text), text)

    def test_clean_cell_removes_private_use(self) -> None:
        self.assertEqual(clean_cell("0.37 \ue005\n  m"), "0.37 m")

    def test_chunk_text_has_no_unreadable_glyphs(self) -> None:
        body = "6.1.8.5 피트 바닥은 정하중의 4배를 지지할 수 있어야 한다.\n\ue005\ue047\ue037∙\ue0eb\ue0f2\n여기서, F : 전체 수직력(N)"

        chunks = chunk_secure(FakeDocument(), make_content(make_page(11, body)))

        self.assertEqual(len(chunks), 1)
        self.assertNotRegex(chunks[0].text, "[\ue000-\uf8ff]")
        self.assertIn("여기서, F : 전체 수직력(N)", chunks[0].text)
        self.assertNotIn("∙", chunks[0].text)

    def test_page_with_only_glyphs_makes_no_chunk(self) -> None:
        self.assertEqual(chunk_secure(FakeDocument(), make_content(make_page(11, "\ue005\ue047\n\ue0eb"))), [])


class ChunkMetadataTest(unittest.TestCase):
    def test_metadata_has_required_keys_without_none(self) -> None:
        chunks = chunk_secure(FakeDocument(), make_content(make_page(7, "7 승강장문 및 카문\n7.1 일반사항")))

        meta = chunks[0].metadata
        self.assertEqual(
            {k: meta[k] for k in ("source", "page", "chunk", "document_id", "document_type", "doc_name")},
            {
                "source": "안전기준.pdf",
                "page": 7,
                "chunk": 0,
                "document_id": 12,
                "document_type": "secure",
                "doc_name": "안전기준",
            },
        )
        self.assertNotIn(None, meta.values())
        self.assertEqual(chunks[0].chunk_id, "12:p7:0")

    def test_empty_page_makes_no_chunk(self) -> None:
        self.assertEqual(chunk_secure(FakeDocument(), make_content(make_page(3, ""), make_page(4, "4"))), [])


class ClauseSplitTest(unittest.TestCase):
    def test_small_clauses_merge_with_numbers_kept(self) -> None:
        body = "6.1 총칙\n6.1.1 첫째 조항은 짧다.\n6.1.2 둘째 조항도 짧다.\n6.1.3 셋째 조항이다."

        chunks = chunk_secure(FakeDocument(), make_content(make_page(10, body)))

        self.assertEqual(len(chunks), 1)
        for number in ("6.1 총칙", "6.1.1", "6.1.2", "6.1.3"):
            self.assertIn(number, chunks[0].text)
        self.assertEqual(chunks[0].metadata["clause"], "6.1")
        self.assertEqual(chunks[0].metadata["section_title"], "총칙")

    def test_new_section_starts_new_chunk_once_enough_text(self) -> None:
        body = f"6.1 총칙\n6.1.1 {sentence('가', MIN_CHUNK_CHARS + 50)}\n6.2 구조\n6.2.1 둘째 절 본문이다."

        chunks = chunk_secure(FakeDocument(), make_content(make_page(10, body)))

        self.assertEqual([c.metadata["clause"] for c in chunks], ["6.1", "6.2"])
        self.assertEqual([c.metadata["chunk"] for c in chunks], [0, 1])

    def test_sub_clause_heading_adds_parent_title_prefix(self) -> None:
        body = "6.5 승강로\n6.5.1 일반사항\n" + sentence("6.5.1.1", MAX_CHUNK_CHARS - 20)
        body += "\n6.5.1.2 새 조항 본문은 둘째 청크로 넘어간다."

        chunks = chunk_secure(FakeDocument(), make_content(make_page(15, body)))

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1].metadata["clause"], "6.5.1.2")
        self.assertTrue(chunks[1].text.startswith("[6.5.1 일반사항]\n"))
        self.assertEqual(chunks[1].metadata["section_title"], "일반사항")

    def test_false_clause_numbers_stay_in_body(self) -> None:
        body = (
            "6.5 승강로\n6.5.1 일반사항\n6.5.1.1 본문이다.\n"
            "89 수식 설명 줄\n1 000 ㎏ 이상이어야 한다.\n3 참조)\n6.5.1.2 다음 조항이다."
        )

        chunks = chunk_secure(FakeDocument(), make_content(make_page(15, body)))

        self.assertEqual(len(chunks), 1)
        for line in ("89 수식 설명 줄", "1 000 ㎏ 이상이어야 한다.", "3 참조)", "6.5.1.2 다음 조항이다."):
            self.assertIn(line, chunks[0].text)

    def test_page_number_line_is_dropped(self) -> None:
        chunks = chunk_secure(FakeDocument(), make_content(make_page(51, "51\n8.2.1.3 카 벽에 관한 조항이다.")))

        self.assertNotIn("\n51\n", "\n" + chunks[0].text + "\n")
        self.assertFalse(chunks[0].text.startswith("51"))


class LongAndContinuedTest(unittest.TestCase):
    def test_long_clause_is_split_within_limit(self) -> None:
        body = "3.1 용어\n3.1.1 " + "승강로의 안전 요구사항을 만족하여야 한다. " * 150

        chunks = chunk_secure(FakeDocument(), make_content(make_page(2, body)))

        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(c.text) <= HARD_MAX_CHARS for c in chunks))
        self.assertTrue(all(c.metadata["clause"] == "3.1.1" or c.metadata["clause"] == "3.1" for c in chunks))
        joined = "".join(c.text for c in chunks).replace("\n", "").replace(" ", "")
        self.assertEqual(joined.count("만족하여야한다."), 150)

    def test_single_huge_sentence_is_cut_under_limit(self) -> None:
        chunks = chunk_secure(FakeDocument(), make_content(make_page(2, "3.1 용어\n3.1.1 " + "가" * 4000)))

        self.assertTrue(all(len(c.text) <= HARD_MAX_CHARS for c in chunks))
        self.assertEqual(sum(c.text.count("가") for c in chunks), 4000)

    def test_page_break_continues_previous_clause(self) -> None:
        page1 = make_page(14, "6.5 승강로\n6.5.1 일반사항\n6.5.1.1 승강로 벽은 다음과 같이")
        page2 = make_page(15, "15\n구성되어야 한다.\n6.5.1.2 다음 조항이다.")

        chunks = chunk_secure(FakeDocument(), make_content(page1, page2))

        second_page = [c for c in chunks if c.metadata["page"] == 15]
        self.assertEqual(second_page[0].metadata["clause"], "6.5.1.1")
        self.assertTrue(second_page[0].text.startswith("[6.5.1.1 계속]") or "계속]" in second_page[0].text.splitlines()[0])
        self.assertIn("구성되어야 한다.", second_page[0].text)
        self.assertIn("6.5.1.2 다음 조항이다.", second_page[0].text)

    def test_chunks_never_cross_pages(self) -> None:
        chunks = chunk_secure(
            FakeDocument(),
            make_content(make_page(1, "1 적용 범위\n1.1 첫 페이지."), make_page(2, "1.2 둘째 페이지.")),
        )

        self.assertEqual([c.metadata["page"] for c in chunks], [1, 2])
        self.assertNotIn("둘째 페이지", chunks[0].text)


class AnnexTest(unittest.TestCase):
    def test_annex_has_no_clause_and_keeps_title(self) -> None:
        body = "부속서 Ⅴ\n기계류 공간 - 접근\n1 문 및 트랩문(6.3)\n2 기계류 공간(6.6)\n[ 그림 Ⅴ.1 ]"

        chunks = chunk_secure(FakeDocument(), make_content(make_page(161, body)))

        self.assertEqual(len(chunks), 1)
        self.assertNotIn("clause", chunks[0].metadata)
        self.assertEqual(chunks[0].metadata["section_title"], "부속서 Ⅴ 기계류 공간 - 접근")
        self.assertIn("1 문 및 트랩문(6.3)", chunks[0].text)

    def test_numbered_lines_after_annex_start_are_not_clauses(self) -> None:
        main = make_page(150, "18 기타\n18.1 마지막 조항이다.")
        annex1 = make_page(152, "부속서 Ⅰ\n전기안전장치\n1 안전 접점\n2 안전 회로")
        annex2 = make_page(153, "3 계속되는 번호 줄\n4 또 다른 번호 줄")

        chunks = chunk_secure(FakeDocument(), make_content(main, annex1, annex2))

        annex_chunks = [c for c in chunks if c.metadata["page"] >= 152]
        self.assertTrue(all("clause" not in c.metadata for c in annex_chunks))
        self.assertTrue(annex_chunks[-1].text.startswith("[부속서 Ⅰ 전기안전장치]\n"))

    def test_annex_reference_in_sentence_is_not_a_heading(self) -> None:
        body = "11 전기\n11.1 일반\n11.1.1 본문이다.\n부속서 Ⅺ\n에 따라 입증되어야 한다."

        chunks = chunk_secure(FakeDocument(), make_content(make_page(99, body)))

        self.assertEqual(len(chunks), 1)
        self.assertIn("clause", chunks[0].metadata)


class TableChunkTest(unittest.TestCase):
    ROWS = [["정격하중(㎏)", "면적(㎡)"], ["100", "0.37"], ["180", "0.58"]]

    def test_reliable_table_chunk_follows_body_chunks_with_caption(self) -> None:
        body = "8.2.1.4 카의 과부하에 관한 조항이다.\n[ 표 5. 정격하중 및 최대 카 유효 면적 ]"

        chunks = chunk_secure(FakeDocument(), make_content(make_page(51, body, [make_table(self.ROWS)])))

        self.assertEqual([c.metadata["chunk"] for c in chunks], [0, 1])
        table_chunk = chunks[1]
        self.assertEqual(table_chunk.text.splitlines()[0], "[ 표 5. 정격하중 및 최대 카 유효 면적 ]")
        self.assertIn("정격하중(㎏): 100 | 면적(㎡): 0.37", table_chunk.text)
        self.assertIn("정격하중(㎏): 180 | 면적(㎡): 0.58", table_chunk.text)
        self.assertNotIn("clause", table_chunk.metadata)

    def test_unreliable_table_is_skipped(self) -> None:
        chunks = chunk_secure(
            FakeDocument(),
            make_content(make_page(51, "8.2.1.4 본문이다.", [make_table(self.ROWS, reliable=False)])),
        )

        self.assertEqual(len(chunks), 1)
        self.assertNotIn("0.37", chunks[0].text)

    def test_caption_is_dropped_when_count_differs_from_tables(self) -> None:
        body = "8.2.1.4 본문이다.\n[ 표 1. 첫째 ]\n[ 표 2. 둘째 ]"

        chunks = chunk_secure(FakeDocument(), make_content(make_page(51, body, [make_table(self.ROWS)])))

        self.assertFalse(chunks[-1].text.startswith("[ 표"))

    def test_clause_from_first_column(self) -> None:
        rows = [["기준항목", "안전 요구사항"], ["5.1", "안전기준 적합"], ["5.2", "일반사항"]]

        chunks = chunk_secure(FakeDocument(), make_content(make_page(148, "", [make_table(rows)])))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["clause"], "5.1")
        self.assertIn("기준항목: 5.1 | 안전 요구사항: 안전기준 적합", chunks[0].text)

    def test_table_without_header_joins_values(self) -> None:
        rows = [["100", "0.37"], ["180", "0.58"]]

        chunks = chunk_secure(FakeDocument(), make_content(make_page(1, "", [make_table(rows)])))

        self.assertEqual(chunks[0].text, "100 | 0.37\n180 | 0.58")

    def test_single_cell_row_is_written_without_header(self) -> None:
        rows = [["정격하중(㎏)", "면적(㎡)"], ["100", "0.37"], ["비고 1 중간 하중은 보간법으로 계산한다", "", ""]]

        chunks = chunk_secure(FakeDocument(), make_content(make_page(1, "", [make_table(rows)])))

        lines = chunks[0].text.splitlines()
        self.assertEqual(lines[0], "정격하중(㎏): 100 | 면적(㎡): 0.37")
        self.assertEqual(lines[1], "비고 1 중간 하중은 보간법으로 계산한다")

    def test_long_table_is_split_by_rows(self) -> None:
        rows = [["항목", "값"]] + [[f"항목{i}", "값" * 60] for i in range(60)]

        chunks = chunk_secure(FakeDocument(), make_content(make_page(1, "", [make_table(rows)])))

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks))
        self.assertEqual(sum(c.text.count("항목") for c in chunks), 60 + 60)

    def test_chunk_ids_are_unique_per_document(self) -> None:
        pages = [make_page(n, f"{n} 제목\n{n}.1 본문이다.", [make_table(self.ROWS)]) for n in range(1, 4)]

        chunks = chunk_secure(FakeDocument(), make_content(*pages))

        ids = [c.chunk_id for c in chunks]
        self.assertEqual(len(ids), len(set(ids)))


@unittest.skipUnless(SAFETY_PDF.is_file(), "safety pdf not found")
class RealSafetyPdfTest(unittest.TestCase):
    """data/pdfs/ 의 실제 안전기준 PDF 확인. 원본은 Git에 없으므로 파일이 있을 때만 실행한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from features.processing.pdf_content import extract_pdf_content

        cls.content = extract_pdf_content(SAFETY_PDF)
        cls.chunks = chunk_secure(FakeDocument(), cls.content)

    def test_every_text_page_has_a_chunk(self) -> None:
        pages_with_chunks = {c.metadata["page"] for c in self.chunks}
        missing = [p.page_no for p in self.content.pages if not p.is_low_text and p.page_no not in pages_with_chunks]
        self.assertEqual(missing, [])

    def test_ids_are_unique_and_types_are_valid(self) -> None:
        ids = [c.chunk_id for c in self.chunks]
        self.assertEqual(len(ids), len(set(ids)))
        for chunk in self.chunks:
            meta = chunk.metadata
            self.assertIsInstance(meta["page"], int)
            self.assertIsInstance(meta["chunk"], int)
            self.assertNotIn(None, meta.values())
            self.assertTrue(chunk.text.strip())

    def test_no_unreadable_glyphs_in_chunks(self) -> None:
        dirty = [c.chunk_id for c in self.chunks if re.search("[\ue000-\uf8ff]", c.text)]
        self.assertEqual(dirty, [])

    def test_chunk_length_is_within_limit(self) -> None:
        too_long = [c.chunk_id for c in self.chunks if len(c.text) > HARD_MAX_CHARS]
        self.assertEqual(too_long, [])

    def test_page_51_has_body_and_table_chunks(self) -> None:
        page = [c for c in self.chunks if c.metadata["page"] == 51]

        self.assertTrue(any("8.2.1.3" in c.text for c in page))
        table = [c for c in page if "표 5." in c.text.splitlines()[0]]
        self.assertGreaterEqual(len(table), 1)
        table_text = "\n".join(c.text for c in table)
        self.assertIn("0.37", table_text)
        self.assertIn("2,500다)", table_text)
        body = "".join(c.text for c in page if c not in table)
        self.assertNotIn("0.37", body)

    def test_annex_pages_have_no_clause(self) -> None:
        annex = [c for c in self.chunks if c.metadata["page"] >= 152 and "부속서" in c.metadata.get("section_title", "")]
        self.assertTrue(annex)
        self.assertTrue(all("clause" not in c.metadata for c in annex))

    def test_main_clauses_carry_clause_numbers(self) -> None:
        main = [c for c in self.chunks if c.metadata["page"] < 152]
        with_clause = [c for c in main if "clause" in c.metadata]
        self.assertGreater(len(with_clause) / len(main), 0.8)


if __name__ == "__main__":
    unittest.main()
