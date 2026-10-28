from dataclasses import dataclass
from pathlib import Path

import pymupdf

from features.processing.pdf_tables import TableBlock, extract_pdf_tables, point_in_box
from features.processing.pdf_text import PdfExtractionError, extract_pdf_text


@dataclass(frozen=True)
class PageContent:
    """한 페이지의 본문과 표. body_text에서는 신뢰할 수 있는 표 영역의 글자가 빠져 있다."""

    page_no: int
    body_text: str
    tables: list[TableBlock]
    is_low_text: bool
    image_count: int


@dataclass(frozen=True)
class PdfContent:
    """PDF 한 개의 본문·표 통합 추출 결과."""

    file_name: str
    page_count: int
    pages: list[PageContent]
    failed_table_pages: list[int]

    @property
    def low_text_pages(self) -> list[int]:
        """텍스트가 거의 없는 페이지 번호 목록. 이미지·도면 위주 페이지일 수 있다."""
        return [p.page_no for p in self.pages if p.is_low_text]


def body_without_tables(page: pymupdf.Page, tables: list[TableBlock]) -> str:
    """신뢰할 수 있는 표(is_reliable=True) 영역의 글자를 뺀 본문을 반환한다.

    그런 표가 없으면 page.get_text() 원문을 그대로 반환한다. 있으면 get_text("words")에서
    표 영역 안의 단어를 빼고 같은 줄(block, line)끼리 이어 붙이므로 공백이 원문과 조금 다를 수 있다.
    신뢰할 수 없는 표는 구조가 틀렸을 수 있어 본문에서 지우지 않는다(중복보다 누락이 더 해롭다).
    """
    boxes = [t.bbox for t in tables if t.is_reliable]
    if not boxes:
        return page.get_text()
    lines: dict[tuple[int, int], list[str]] = {}
    for word in page.get_text("words"):
        if any(point_in_box(word, box) for box in boxes):
            continue
        lines.setdefault((word[5], word[6]), []).append(word[4])
    return "\n".join(" ".join(ws) for ws in lines.values())


def extract_pdf_content(path: str | Path) -> PdfContent:
    """PDF에서 본문과 표를 함께 추출하고, 신뢰할 수 있는 표 영역은 본문에서 제외한다.

    스캔 PDF는 ScannedPdfError, 열 수 없는 PDF는 PdfExtractionError를 발생시킨다.
    표 추출이 실패한 페이지는 failed_table_pages에 기록하고 본문은 원문을 유지한다.
    분리된 숫자 복원은 표 셀에만 필요하다. 본문(get_text)에서는 같은 문제가 발견되지 않았다.
    """
    path = Path(path)
    text = extract_pdf_text(path)
    tables = extract_pdf_tables(path)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfExtractionError(f"cannot open pdf: {path.name}") from exc

    with doc:
        pages = []
        for page_text in text.pages:
            page_tables = tables.tables_on_page(page_text.page_no)
            page = doc[page_text.page_no - 1]
            pages.append(
                PageContent(
                    page_no=page_text.page_no,
                    body_text=body_without_tables(page, page_tables),
                    tables=page_tables,
                    is_low_text=page_text.is_low_text,
                    image_count=page_text.image_count,
                )
            )
    return PdfContent(
        file_name=text.file_name,
        page_count=text.page_count,
        pages=pages,
        failed_table_pages=tables.failed_pages,
    )
