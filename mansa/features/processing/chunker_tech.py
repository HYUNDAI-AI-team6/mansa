"""기술사양서 PDF를 모델 단위의 청크로 나눈다.

청크는 페이지를 넘지 않는다. 모델 이름은 호출하는 쪽이 목록(models)으로 넘긴다. PDF에서 제품명을
규칙으로 추측하면 "PASSENGER ELEVATORS" 같은 일반 문구가 섞여 틀린 model이 들어가기 때문이다.
목록을 주지 않으면 model 키와 모델 머리말을 넣지 않는다.
"""

import re
from collections.abc import Sequence
from typing import Any

from features.processing.chunk_utils import clean_cell, pack_lines, pack_rows, strip_private_use
from features.processing.models import Chunk, DocumentLike, base_metadata
from features.processing.pdf_content import PageContent, PdfContent
from features.processing.pdf_tables import TableBlock

# 열 이름으로 볼 맨 위 행의 최대 개수(예: 그룹 제목 + 세부 제목).
MAX_HEADER_ROWS = 3
# 본문 글자가 이보다 적은 페이지(사진 설명 한두 줄 등)는 본문 청크를 만들지 않는다.
MIN_BODY_CHARS = 30

# 숫자·단위 기호만 있는 칸(예: 750, 30 (60), 1250×1150). 이런 칸이 있는 행부터 데이터로 본다.
_NUMERIC_LIKE = re.compile(r"^[\d\s.,~/×xX()+\-%]+$")
_PAGE_NUMBER_LINE = re.compile(r"^\d{1,3}$")


def _page_models(page: PageContent, models: Sequence[str]) -> list[str]:
    """페이지 본문에 이름이 나오는 모델을 처음 나온 순서대로 돌려준다. 대소문자와 공백 차이는 무시한다."""
    text = " ".join(page.body_text.split()).lower()
    found = [(text.find(model.lower()), model) for model in models]
    return [model for position, model in sorted(item for item in found if item[0] >= 0)]


def _header_row_indexes(rows: list[list[str]]) -> tuple[list[int], int]:
    """맨 위의 열 이름 행 번호와 데이터가 시작하는 행 번호를 찾는다.

    비어 있는 행은 건너뛰고, 숫자 칸이 하나라도 있는 첫 행부터 데이터로 본다. 숫자 칸은 숫자를 하나
    이상 포함해야 한다(열 이름 "X", "W"가 곱셈 기호로 오인되지 않게). 열 이름 행은 최대
    MAX_HEADER_ROWS개이며, 숫자 칸이 있는 행이 맨 위에 있으면 열 이름이 없는 표로 본다.
    """
    header: list[int] = []
    index = 0
    while index < len(rows) and len(header) < MAX_HEADER_ROWS:
        filled = [cell for cell in rows[index] if cell]
        if filled and any(_NUMERIC_LIKE.fullmatch(cell) and any(ch.isdigit() for ch in cell) for cell in filled):
            break
        if filled:
            header.append(index)
        index += 1
    return header, index


def _column_names(rows: list[list[str]], merged: list[list[bool]], header: list[int]) -> list[str]:
    """열 이름 행들을 합쳐 열마다 이름을 만든다(예: "Car Inside" + "W" → "Car Inside W").

    병합으로 가려진 칸은 두 가지로 풀어 읽는다. 바로 위 열 이름 칸에 값이 있으면 위쪽 칸이 아래로
    합쳐진 것이라 그 이름이 이미 반영되어 있고, 위가 비어 있으면 왼쪽 칸이 옆으로 합쳐진 것이라
    왼쪽의 이름을 잇는다.
    """
    width = max((len(row) for row in rows), default=0)
    names: list[str] = []
    for col in range(width):
        parts: list[str] = []
        for pos, r in enumerate(header):
            cell = rows[r][col] if col < len(rows[r]) else ""
            if not cell and col < len(merged[r]) and merged[r][col]:
                above = rows[header[pos - 1]][col] if pos and col < len(rows[header[pos - 1]]) else ""
                if not above:
                    left = col - 1
                    while left >= 0 and not rows[r][left] and merged[r][left]:
                        left -= 1
                    cell = rows[r][left] if left >= 0 else ""
            if cell and cell not in parts:
                parts.append(cell)
        names.append(" ".join(parts))
    return names


def _table_row_texts(table: TableBlock) -> list[tuple[str, str | None]]:
    """표를 행 단위 문장 "열 이름: 값 | …"으로 바꾼다.

    병합으로 가려진 칸은 같은 열의 바로 위 행 값으로 채운다(세로로 합쳐진 칸). 실제로 비어 있는
    칸은 채우지 않고 건너뛴다. 열 이름을 알 수 없거나 값이 한 칸뿐인 행은 값만 " | "로 잇는다.
    """
    rows = [[clean_cell(cell) for cell in row] for row in table.rows]
    merged = table.merged or [[False] * len(row) for row in table.rows]
    header, start = _header_row_indexes(rows)
    names = _column_names(rows, merged, header)

    result: list[tuple[str, str | None]] = []
    previous: list[str] | None = None
    for r in range(start, len(rows)):
        row = list(rows[r])
        for col, cell in enumerate(row):
            hidden = col < len(merged[r]) and merged[r][col]
            if not cell and hidden and previous is not None and col < len(previous):
                row[col] = previous[col]
        previous = row
        filled = [(col, cell) for col, cell in enumerate(row) if cell]
        if not filled:
            continue
        use_names = len(filled) > 1
        parts = [
            f"{names[col]}: {cell}" if use_names and col < len(names) and names[col] else cell
            for col, cell in filled
        ]
        result.append((" | ".join(parts), None))
    return result


def _body_texts(page: PageContent) -> list[str]:
    """페이지 본문을 줄 단위로 읽어 길이 기준에 맞는 청크 본문으로 묶는다.

    숫자만 있는 줄(페이지 번호)은 버리고, 남은 글자가 MIN_BODY_CHARS보다 적으면 만들지 않는다.
    """
    lines = [line.strip() for line in strip_private_use(page.body_text).splitlines() if line.strip()]
    lines = [line for line in lines if not _PAGE_NUMBER_LINE.fullmatch(line)]
    if sum(len(line) for line in lines) < MIN_BODY_CHARS:
        return []
    return pack_lines(lines)


def chunk_tech(
    document: DocumentLike, content: PdfContent, models: Sequence[str] | None = None
) -> list[Chunk]:
    """기술사양서 추출 결과를 청크 목록으로 나눈다.

    models는 모델 이름 목록이다. 페이지 본문에 이름이 나오는 모델마다 그 페이지의 청크를 하나씩
    만들고, 본문 맨 앞에 "[모델]" 머리말을, 메타데이터에 model을 둔다. 한 페이지에 모델이 둘 이상
    나오면(두 모델이 공유하는 표나 소개 페이지) 같은 내용을 모델별로 복제한다. 모델이 하나도
    나오지 않거나 models가 없으면 model 없이 청크를 만든다. 신뢰도 낮은 표는 만들지 않는다.
    페이지마다 본문 청크를 먼저, 표 청크를 다음에 하나의 chunk 순번(0부터)으로 매긴다.
    """
    names = [" ".join(model.split()) for model in models or [] if model.strip()]
    chunks: list[Chunk] = []
    for page in content.pages:
        texts = _body_texts(page)
        for table in page.tables:
            if table.is_reliable:
                texts.extend(text for text, _ in pack_rows(_table_row_texts(table)))
        labels: list[str | None] = list(_page_models(page, names)) or [None]
        index = 0
        for text in texts:
            for label in labels:
                metadata: dict[str, Any] = base_metadata(document, page.page_no, index)
                if label:
                    metadata["model"] = label
                chunks.append(Chunk(text=f"[{label}]\n{text}" if label else text, metadata=metadata))
                index += 1
    return chunks
