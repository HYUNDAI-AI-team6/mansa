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
# "." 또는 ","만 있는 줄과, 페이지 단어 안의 소수점·천 단위 구분 숫자(예: 0.16, 2,500)
_PUNCT_ONLY_LINE = re.compile(r"[.,]( [.,])*")
_PUNCTUATED_NUMBER = re.compile(r"\d+(?:[.,]\d+)+")


@dataclass(frozen=True)
class TableBlock:
    """find_tables()가 감지한 표 한 개. page_no는 1부터, table_index는 페이지 안에서 0부터 시작한다.

    is_reliable이 False인 표는 구조가 틀렸을 가능성이 있어 본문 텍스트에서 표 영역을 지우지 않는다.
    merged는 rows와 같은 크기의 표시로, True인 칸은 병합된 셀에 가려진 칸(PyMuPDF가 None으로 준 칸)이다.
    실제로 비어 있는 칸(False)과 구분하려고 둔다. 값을 주지 않으면 빈 목록이다.
    """

    page_no: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]
    row_count: int
    col_count: int
    empty_ratio: float
    is_reliable: bool = True
    merged: list[list[bool]] = field(default_factory=list)


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


def _digit_pattern(digits: str) -> re.Pattern:
    """숫자열을 공백이 끼어 있어도 찾는 패턴으로 만든다. "1020"은 "1 020"에도 맞는다.

    앞뒤가 다른 숫자의 일부면 맞지 않는다. "0 10" 안의 "10"을 잘못 찾지 않도록
    공백 하나를 사이에 둔 숫자까지 앞뒤 경계로 본다.
    """
    body = r"\s?".join(digits)
    return re.compile(r"(?<!\d)(?<!\d\s)" + body + r"(?!\s?\d)")


def _repair_text_cell(cell_text: str, cell_words: list[tuple]) -> str:
    """글자가 섞인 셀의 소수점·쉼표를 복원하고 떨어져 나온 기호 줄을 지운다.

    셀을 통째로 다시 만들지 않는다. 여러 줄 문장은 단어를 좌표 순서로 이으면 순서가 뒤섞이고
    띄어쓰기가 사라지기 때문이다. 대신 페이지 단어에 있는 "0.16", "2,500" 같은 숫자를 찾아,
    셀 본문에서 구분 기호가 빠진 같은 숫자열("016", "2 500")을 그 값으로 바꾼다.
    이미 본문에 있는 값은 건드리지 않고, 숫자 자체는 바꾸지 않으며 구분 기호만 채운다.
    그 뒤 "."이나 ","만 남은 줄은 지운다. 이 기호들은 문장 부호라서 지워도 값은 변하지 않는다.
    """
    text = cell_text
    for word in cell_words:
        for match in _PUNCTUATED_NUMBER.finditer(word[4]):
            number = match.group()
            if number in text:
                continue
            digits = re.sub(r"\D", "", number)
            text = _digit_pattern(digits).sub(number, text, count=1)
    lines = [line for line in text.split("\n") if not _PUNCT_ONLY_LINE.fullmatch(line.strip())]
    return "\n".join(lines)


def restore_split_number(cell_text: str, cell_box, words: list[tuple]) -> str:
    """셀 안의 분리된 숫자("0 37\\n.")를 페이지의 글자 좌표로 복원한다("0.37").

    "."·","만 있는 줄이 없는 셀과 셀 영역이 없는 셀은 그대로 반환한다.
    - 글자 없이 숫자·기호만 있는 셀: 소수점 위치를 문자열 규칙으로 추정하면 "225\\n."가
      2.25인지 22.5인지 알 수 없어서, 셀 영역 안의 단어를 위에서 아래, 왼쪽에서 오른쪽 순으로
      공백으로 이어 붙인다(값이 여러 줄이면 한 줄이 된다). 영역 안에 단어가 없으면 원문을 유지한다.
    - 글자가 섞인 셀: 숫자의 구분 기호만 복원하고 기호만 남은 줄을 지운다(_repair_text_cell).
    """
    if cell_box is None or not any(
        _PUNCT_ONLY_LINE.fullmatch(line.strip()) for line in cell_text.split("\n")
    ):
        return cell_text
    inside = sorted(
        (w for w in words if point_in_box(w, cell_box)), key=lambda w: (round(w[1]), w[0])
    )
    if _LETTER.search(cell_text):
        return _repair_text_cell(cell_text, inside)
    return " ".join(w[4] for w in inside) or cell_text


def build_table(page_no: int, table_index: int, table, words: list[tuple] | None = None) -> TableBlock:
    """PyMuPDF 표 객체를 TableBlock으로 바꾼다. 빈 셀(None)은 빈 문자열로 바꾸고 글자는 그대로 둔다.

    words(해당 페이지의 get_text("words"))를 주면 분리된 숫자 셀을 복원한다.
    empty_ratio는 빈 셀 비율이고, is_reliable은 is_reliable_table()의 판단이다.
    """
    raw = table.extract()
    rows = [[cell or "" for cell in row] for row in raw]
    merged = [[cell is None for cell in row] for row in raw]
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
        merged=merged,
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
