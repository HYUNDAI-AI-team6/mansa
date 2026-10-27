import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from features.processing.pdf_text import PdfExtractionError

# 빈 셀 비율이 이 값을 넘으면 구조가 어긋났을 가능성이 높다고 본다.
MAX_EMPTY_RATIO = 0.5
# 행·열이 모두 이 값 이하인 아주 작은 표는 오감지 가능성이 높다고 본다.
TINY_TABLE_LIMIT = 2

# 글자 없이 숫자·기호만 있는 셀이 줄바꿈 뒤 "." 또는 ","로 끝나는 경우(예: "0 37\n.")
_LETTER = re.compile(r"[A-Za-z가-힣]")
_TRAILING_PUNCT_LINE = re.compile(r"\n[.,]( [.,])*\s*$")


@dataclass(frozen=True)
class TableBlock:
    """find_tables()가 감지한 표 한 개. page_no는 1부터, table_index는 페이지 안에서 0부터 시작한다.

    is_reliable이 False인 표는 구조가 틀렸을 가능성이 있어 본문 텍스트에서 표 영역을 지우지 않는다.
    """

    page_no: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]
    row_count: int
    col_count: int
    empty_ratio: float
    is_reliable: bool = True


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


def is_reliable_table(row_count: int, col_count: int, empty_ratio: float) -> bool:
    """표 구조를 믿을 수 있는지 판단한다. 빈 셀이 너무 많거나 아주 작은 표는 False.

    임계값은 실제 PDF 3개의 일부 표를 눈으로 확인해 정한 경험값이다. 구조가 틀렸어도
    이 조건에 걸리지 않는 표가 있을 수 있으므로 정확도를 보장하지 않는다.
    """
    if empty_ratio > MAX_EMPTY_RATIO:
        return False
    return not (row_count <= TINY_TABLE_LIMIT and col_count <= TINY_TABLE_LIMIT)


def point_in_box(word: tuple, box: tuple[float, float, float, float]) -> bool:
    """get_text("words")의 단어 중심점이 box 안에 있으면 True."""
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def restore_split_number(cell_text: str, cell_box, words: list[tuple]) -> str:
    """셀 안의 분리된 숫자("0 37\\n.")를 페이지의 글자 좌표로 복원한다("0.37").

    글자 없이 숫자·기호만 있고 줄바꿈 뒤 ".", ","로 끝나는 셀만 대상으로 하고, 그 외 셀은 그대로 반환한다.
    소수점 위치를 문자열 규칙으로 추정하면 "225\\n."가 2.25인지 22.5인지 알 수 없어서,
    셀 영역 안의 단어를 위에서 아래, 왼쪽에서 오른쪽 순으로 이어 붙인다.
    영역 안에 단어가 없으면 원문을 유지한다.
    """
    if cell_box is None or _LETTER.search(cell_text) or not _TRAILING_PUNCT_LINE.search(cell_text):
        return cell_text
    inside = sorted(
        (w for w in words if point_in_box(w, cell_box)), key=lambda w: (round(w[1]), w[0])
    )
    return " ".join(w[4] for w in inside) or cell_text


def build_table(page_no: int, table_index: int, table, words: list[tuple] | None = None) -> TableBlock:
    """PyMuPDF 표 객체를 TableBlock으로 바꾼다. 빈 셀(None)은 빈 문자열로 바꾸고 글자는 그대로 둔다.

    words(해당 페이지의 get_text("words"))를 주면 분리된 숫자 셀을 복원한다.
    empty_ratio는 빈 셀 비율이고, is_reliable은 is_reliable_table()의 판단이다.
    """
    rows = [[cell or "" for cell in row] for row in table.extract()]
    if words:
        for r, row in enumerate(table.rows):
            for c, box in enumerate(row.cells):
                if c < len(rows[r]):
                    rows[r][c] = restore_split_number(rows[r][c], box, words)
    cells = [cell for row in rows for cell in row]
    empty = sum(1 for cell in cells if not cell.strip())
    empty_ratio = empty / len(cells) if cells else 1.0
    return TableBlock(
        page_no=page_no,
        table_index=table_index,
        bbox=tuple(table.bbox),
        rows=rows,
        row_count=len(rows),
        col_count=table.col_count,
        empty_ratio=empty_ratio,
        is_reliable=is_reliable_table(len(rows), table.col_count, empty_ratio),
    )


def extract_pdf_tables(path: str | Path) -> PdfTables:
    """PDF 전체에서 page.find_tables()로 표를 추출한다. 감지 결과를 걸러내거나 병합하지 않는다.

    파일이 없거나 PDF가 아니거나 암호화된 경우 PdfExtractionError를 발생시킨다.
    한 페이지의 find_tables()가 실패해도 중단하지 않고 그 페이지를 failed_pages에 기록한다.
    표가 없는 페이지는 결과에 나타나지 않는다. 이미지로 된 표는 감지되지 않는다.
    분리된 숫자 셀은 복원하고, 표마다 is_reliable을 기록한다.
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
                words = page.get_text("words") if found else None
                built = [build_table(page_no, i, t, words) for i, t in enumerate(found)]
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
