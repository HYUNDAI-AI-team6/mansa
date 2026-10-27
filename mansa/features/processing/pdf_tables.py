from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from features.processing.pdf_text import PdfExtractionError


@dataclass(frozen=True)
class TableBlock:
    """find_tables()가 감지한 표 한 개. page_no는 1부터, table_index는 페이지 안에서 0부터 시작한다."""

    page_no: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]
    row_count: int
    col_count: int
    empty_ratio: float


@dataclass(frozen=True)
class PdfTables:
    """PDF 한 개의 표 추출 결과. failed_pages는 find_tables()에서 예외가 난 페이지 번호다."""

    file_name: str
    page_count: int
    tables: list[TableBlock]
    failed_pages: list[int] = field(default_factory=list)

    @property
    def table_pages(self) -> list[int]:
        """표가 한 개 이상 감지된 페이지 번호 목록(중복 없음, 오름차순)."""
        return sorted({t.page_no for t in self.tables})

    def tables_on_page(self, page_no: int) -> list[TableBlock]:
        """해당 페이지에서 감지된 표를 감지 순서대로 반환한다."""
        return [t for t in self.tables if t.page_no == page_no]


def build_table(page_no: int, table_index: int, table) -> TableBlock:
    """PyMuPDF 표 객체를 TableBlock로 바꾼다. 빈 셀(None)은 빈 문자열로 바꾸고 글자는 그대로 둔다.

    empty_ratio는 빈 셀 비율로, 잘못 감지된 표를 가려내는 참고 지표일 뿐 필터링에는 쓰지 않는다.
    """
    rows = [[cell or "" for cell in row] for row in table.extract()]
    cells = [cell for row in rows for cell in row]
    empty = sum(1 for cell in cells if not cell.strip())
    return TableBlock(
        page_no=page_no,
        table_index=table_index,
        bbox=tuple(table.bbox),
        rows=rows,
        row_count=len(rows),
        col_count=table.col_count,
        empty_ratio=empty / len(cells) if cells else 1.0,
    )


def extract_pdf_tables(path: str | Path) -> PdfTables:
    """PDF 전체에서 page.find_tables()로 표를 추출한다. 감지 결과를 걸러내거나 병합하지 않는다.

    파일이 없거나 PDF가 아니거나 암호화된 경우 PdfExtractionError를 발생시킨다.
    한 페이지의 find_tables()가 실패해도 중단하지 않고 그 페이지를 failed_pages에 기록한다.
    표가 없는 페이지는 결과에 나타나지 않는다. 이미지로 된 표는 감지되지 않는다.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfExtractionError(f"file not found: {path.name}")
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfExtractionError(f"cannot open pdf: {path.name}") from exc

    with doc:
        if doc.needs_pass:
            raise PdfExtractionError(f"encrypted pdf is not supported: {path.name}")
        tables: list[TableBlock] = []
        failed_pages: list[int] = []
        for page in doc:
            page_no = page.number + 1
            try:
                found = page.find_tables().tables
                built = [build_table(page_no, i, t) for i, t in enumerate(found)]
            except Exception:
                failed_pages.append(page_no)
                continue
            tables.extend(built)
        return PdfTables(
            file_name=path.name,
            page_count=len(doc),
            tables=tables,
            failed_pages=failed_pages,
        )
