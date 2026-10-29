"""안전기준 PDF를 조항 번호 기준의 청크로 나눈다.

청크는 페이지를 넘지 않는다. 출처가 (source, page)로 표시되기 때문이다. 조항이 다음 페이지로
이어지면 그 페이지에서 새 청크가 되고 같은 clause를 이어받는다.
"""

import re
from dataclasses import dataclass, field, replace
from typing import Any

from features.processing.chunk_utils import (
    MAX_CHUNK_CHARS,
    MAX_LINE_CHARS,
    MIN_CHUNK_CHARS,
    clean_cell,
    pack_rows,
    split_text,
    strip_private_use,
)
from features.processing.models import Chunk, DocumentLike, base_metadata
from features.processing.pdf_content import PageContent, PdfContent
from features.processing.pdf_tables import TableBlock

# 직전 조항보다 번호가 이 값을 넘게 건너뛰면 조항이 아니라 본문 속 숫자로 본다.
MAX_CLAUSE_GAP = 5
# 이 글자 수 이하이고 문장으로 끝나지 않는 조항 줄은 제목으로 본다.
MAX_HEADING_CHARS = 30
# 부속서 제목은 페이지 앞쪽에만 나온다. 문장 중간에서 줄이 바뀐 "부속서 Ⅺ"를 제목으로 오인하지 않는다.
ANNEX_HEADING_WITHIN_LINES = 3

Clause = tuple[int, ...]

# "6.5.1.2 본문": 번호 뒤 첫 글자가 숫자·쉼표·마침표면 단위가 붙은 숫자("1 000 ㎏")라서 조항이 아니다.
_CLAUSE_LINE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\s+([^\d\s.,].*)$")
_ANNEX_HEADING = re.compile(r"^부속서\s+[Ⅰ-Ⅻ]+$")
_TABLE_CAPTION = re.compile(r"^\[\s*표\s")
_NUMERIC_CELL = re.compile(r"^[\d\s.,]+$")
_CLAUSE_CELL = re.compile(r"^\d{1,2}(?:\.\d{1,2})*\.?$")


@dataclass
class _Unit:
    """조항 하나(번호 줄과 그 아래 본문). 이어지는 본문과 부속서 본문도 한 단위로 본다."""

    lines: list[str]
    clause: Clause | None = None
    starts_clause: bool = False
    starts_annex: bool = False
    heading: tuple[Clause, str] | None = None
    annex_title: str | None = None

    @property
    def length(self) -> int:
        """줄바꿈을 포함한 본문 글자 수."""
        return len("\n".join(self.lines))

    @property
    def depth(self) -> int:
        """조항 번호의 단계 수. 번호로 시작하지 않는 단위는 아주 깊은 것으로 본다."""
        return len(self.clause) if self.starts_clause and self.clause else 99


@dataclass
class _State:
    """페이지를 넘어 이어지는 조항 상태."""

    last: Clause | None = None
    headings: dict[Clause, str] = field(default_factory=dict)
    in_annex: bool = False
    annex_label: str = ""
    annex_title: str = ""
    annex_pending: bool = False
    annex_unit: _Unit | None = None


def _fmt(clause: Clause) -> str:
    """조항 번호 튜플을 "6.5.1.2" 문자열로 만든다."""
    return ".".join(str(n) for n in clause)


def _is_next(last: Clause | None, candidate: Clause) -> bool:
    """candidate가 직전 조항 last 다음에 올 수 있는 번호인지 확인한다.

    첫 하위 조항(last + 1)이거나, last 또는 그 상위 조항과 같은 단계에서 1~MAX_CLAUSE_GAP만큼
    큰 번호일 때만 참이다. 본문 속 숫자(예: "89 …", "3 참조)")를 조항으로 오인하지 않으려는 검사다.
    아직 조항을 하나도 보지 못했으면(문서의 처음) 비교할 기준이 없어 어떤 번호든 받아들인다.
    """
    if last is None:
        return True
    if candidate == last + (1,):
        return True
    for depth in range(1, len(last) + 1):
        if (
            len(candidate) == depth
            and candidate[:-1] == last[: depth - 1]
            and 1 <= candidate[-1] - last[depth - 1] <= MAX_CLAUSE_GAP
        ):
            return True
    return False


def _nearest_heading(clause: Clause | None, headings: dict[Clause, str]) -> tuple[Clause, str] | None:
    """clause 자신 또는 가장 가까운 상위 조항 중 제목이 있는 것을 (번호, 제목)으로 반환한다."""
    if clause is None:
        return None
    for depth in range(len(clause), 0, -1):
        key = clause[:depth]
        if key in headings:
            return key, headings[key]
    return None


def _page_units(page: PageContent, state: _State) -> list[_Unit]:
    """한 페이지의 본문을 조항 단위로 나눈다. 조항·부속서 상태는 state에 이어서 기록한다.

    페이지 번호만 있는 줄은 버린다. 번호로 시작하는 줄이어도 직전 조항의 다음 번호가 아니면
    조항으로 보지 않고 앞 단위의 본문으로 붙인다. 첫 조항 줄 앞의 본문은 직전 조항의 이어지는
    내용이다. 부속서 제목 줄을 만나면 이후는 조항 번호 없이 본문으로만 처리한다.
    """
    lines = [line.strip() for line in strip_private_use(page.body_text).splitlines() if line.strip()]
    if lines and lines[0] == str(page.page_no):
        lines = lines[1:]
    elif lines and lines[-1] == str(page.page_no):
        lines = lines[:-1]

    units: list[_Unit] = []
    current: _Unit | None = None
    for index, line in enumerate(lines):
        if index < ANNEX_HEADING_WITHIN_LINES and _ANNEX_HEADING.fullmatch(line):
            state.in_annex = True
            state.annex_label = line
            state.annex_title = line
            state.annex_pending = True
            state.headings.clear()
            state.last = None
            current = _Unit([line], starts_annex=True, annex_title=line)
            state.annex_unit = current
            units.append(current)
            continue
        if state.annex_pending:
            state.annex_pending = False
            state.annex_title = f"{state.annex_label} {line}"
            if current is not None and current is state.annex_unit:
                current.annex_title = state.annex_title
                current.lines.append(line)
                continue
        if not state.in_annex:
            match = _CLAUSE_LINE.match(line)
            if match:
                parts = tuple(int(n) for n in match.group(1).split("."))
                if _is_next(state.last, parts):
                    state.last = parts
                    state.headings = {k: v for k, v in state.headings.items() if parts[: len(k)] == k}
                    rest = match.group(2)
                    if len(rest) <= MAX_HEADING_CHARS and not rest.endswith(("다.", "다")):
                        state.headings[parts] = rest
                    current = _Unit(
                        [line],
                        clause=parts,
                        starts_clause=True,
                        heading=_nearest_heading(parts, state.headings),
                    )
                    units.append(current)
                    continue
        if current is None:
            current = _Unit(
                [],
                clause=state.last,
                heading=_nearest_heading(state.last, state.headings),
                annex_title=state.annex_title if state.in_annex else None,
            )
            units.append(current)
        current.lines.append(line)
    return units


def _split_unit(unit: _Unit, first_budget: int = MAX_CHUNK_CHARS) -> list[_Unit]:
    """MAX_CHUNK_CHARS를 넘는 단위를 줄 경계에서 나눈다. 첫 조각만 조항·부속서의 시작으로 남긴다.

    first_budget은 첫 조각에 쓸 수 있는 글자 수다. 앞에 남은 짧은 내용과 첫 조각을 합칠 때 쓴다.
    """
    pieces: list[str] = []
    for line in unit.lines:
        pieces.extend(split_text(line) if len(line) > MAX_LINE_CHARS else [line])
    parts: list[list[str]] = []
    current: list[str] = []
    size = 0
    limit = first_budget
    for piece in pieces:
        add = len(piece) + (1 if current else 0)
        if current and size + add > limit:
            parts.append(current)
            current, size, add, limit = [], 0, len(piece), MAX_CHUNK_CHARS
        current.append(piece)
        size += add
    if current:
        parts.append(current)
    return [
        replace(
            unit,
            lines=part,
            starts_clause=unit.starts_clause and i == 0,
            starts_annex=unit.starts_annex and i == 0,
        )
        for i, part in enumerate(parts)
    ]


def _merge_units(units: list[_Unit]) -> list[list[_Unit]]:
    """짧은 조항을 같은 페이지 안에서 합쳐 청크 단위 묶음으로 만든다.

    MAX_CHUNK_CHARS를 넘기지 않는 범위에서 합친다. 이미 MIN_CHUNK_CHARS 이상 모였으면 1~2단계
    조항(절·큰 항목)에서 새 묶음을 시작하고, 부속서 제목에서는 언제나 새로 시작한다.
    MAX_CHUNK_CHARS를 넘는 긴 조항은 나누되, 앞에 남은 내용이 짧으면(제목만 있는 경우 등)
    첫 조각에 붙여서 제목만 있는 청크가 따로 생기지 않게 한다.
    """
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    size = 0

    def flush() -> None:
        """모인 단위를 묶음 하나로 내보낸다."""
        nonlocal current, size
        if current:
            groups.append(current)
        current, size = [], 0

    def add(unit: _Unit) -> None:
        """단위를 현재 묶음에 넣는다. 넣으면 MAX_CHUNK_CHARS를 넘을 때는 먼저 묶음을 내보낸다."""
        nonlocal size
        if current and size + 1 + unit.length > MAX_CHUNK_CHARS:
            flush()
        size = size + 1 + unit.length if current else unit.length
        current.append(unit)

    for unit in units:
        if current and (
            unit.starts_annex or (size >= MIN_CHUNK_CHARS and unit.starts_clause and unit.depth <= 2)
        ):
            flush()
        if unit.length <= MAX_CHUNK_CHARS:
            add(unit)
            continue
        if current and size >= MIN_CHUNK_CHARS:
            flush()
        budget = MAX_CHUNK_CHARS - (size + 1) if current else MAX_CHUNK_CHARS
        for index, part in enumerate(_split_unit(unit, budget)):
            if index:
                flush()
            add(part)
    flush()
    return groups


def _group_item(group: list[_Unit]) -> tuple[str, dict[str, Any]]:
    """묶음을 청크 본문과 조항 메타데이터(clause, section_title)로 만든다.

    본문 앞에는 맥락을 알 수 있는 머리말을 붙인다. 상위 제목([6.5 승강로]), 이어지는 조항
    ([6.5.1.1 일반사항 계속]), 부속서 제목이다. BM25는 본문만 보므로 번호와 제목이 본문에 있어야 한다.
    """
    first = group[0]
    body = "\n".join(line for unit in group for line in unit.lines)
    extra: dict[str, Any] = {}
    prefix = ""
    if first.annex_title is not None:
        extra["section_title"] = first.annex_title
        if not first.starts_annex:
            prefix = f"[{first.annex_title}]\n"
    else:
        ref = first if first.clause is not None else next((u for u in group if u.starts_clause), first)
        if ref.clause is not None:
            extra["clause"] = _fmt(ref.clause)
            if ref.heading:
                extra["section_title"] = ref.heading[1]
            if ref.starts_clause and ref is first:
                if ref.heading and ref.heading[0] != ref.clause:
                    prefix = f"[{_fmt(ref.heading[0])} {ref.heading[1]}]\n"
            elif ref is first:
                title = f" {ref.heading[1]}" if ref.heading else ""
                prefix = f"[{_fmt(ref.clause)}{title} 계속]\n"
    return prefix + body, extra


def _table_rows(table: TableBlock) -> list[tuple[str, str | None]]:
    """표를 (행 문장, 조항 번호) 목록으로 만든다.

    첫 행에 숫자만 있는 칸이 없으면 열 이름으로 보고 각 행을 "열 이름: 값 | …"로 쓴다. 열 이름을
    알 수 없거나 값이 한 칸뿐인 행은 값만 " | "로 잇는다. 첫 칸이 조항 번호(예: 5.1)면 그 행의
    clause로 돌려준다.
    """
    rows = table.rows
    header: list[str] | None = None
    data = rows
    if len(rows) >= 2:
        first = [clean_cell(cell) for cell in rows[0]]
        filled = [cell for cell in first if cell]
        if filled and not any(_NUMERIC_CELL.fullmatch(cell) for cell in filled):
            header, data = first, rows[1:]
    result: list[tuple[str, str | None]] = []
    for row in data:
        cells = [clean_cell(cell) for cell in row]
        filled = [(col, value) for col, value in enumerate(cells) if value]
        if not filled:
            continue
        # 값이 한 칸뿐인 행(예: 표 아래 "비고")은 병합된 칸이라 열 이름과 연결하지 않는다.
        use_header = header is not None and len(filled) > 1
        parts = [
            f"{header[col]}: {value}" if use_header and col < len(header) and header[col] else value
            for col, value in filled
        ]
        clause = cells[0].rstrip(".") if cells and _CLAUSE_CELL.fullmatch(cells[0]) else None
        result.append((" | ".join(parts), clause))
    return result


def _table_items(table: TableBlock, caption: str | None) -> list[tuple[str, dict[str, Any]]]:
    """신뢰할 수 있는 표 하나를 행 묶음 단위 청크 본문과 메타데이터로 만든다.

    표 제목(caption)이 있으면 모든 청크 맨 앞에 붙인다. 묶음 첫 행의 첫 칸이 조항 번호면 clause로 둔다.
    """
    return [
        (text, {"clause": clause} if clause else {})
        for text, clause in pack_rows(_table_rows(table), caption or "")
    ]


def chunk_secure(document: DocumentLike, content: PdfContent) -> list[Chunk]:
    """안전기준 추출 결과를 청크 목록으로 나눈다.

    페이지마다 본문 청크를 먼저, 표 청크를 그다음에 하나의 chunk 순번(0부터)으로 매긴다.
    텍스트가 없는 페이지와 신뢰도 낮은 표는 청크를 만들지 않는다. 신뢰도 낮은 표의 글자는
    본문에 남아 있어서 본문 청크에 들어간다. 수식과 그림은 추출되지 않으므로 내용을 만들지 않는다.
    """
    state = _State()
    chunks: list[Chunk] = []
    for page in content.pages:
        items = [_group_item(group) for group in _merge_units(_page_units(page, state))]
        reliable = [table for table in page.tables if table.is_reliable]
        captions = [
            line.strip() for line in page.body_text.splitlines() if _TABLE_CAPTION.match(line.strip())
        ]
        # 표 제목은 개수가 표와 같을 때만 순서대로 짝짓는다. 어긋나면 잘못 붙이지 않고 비운다.
        paired = captions if len(captions) == len(reliable) else [None] * len(reliable)
        for table, caption in zip(reliable, paired):
            items.extend(_table_items(table, caption))
        index = 0
        for text, extra in items:
            if not text.strip():
                continue
            metadata = base_metadata(document, page.page_no, index)
            metadata.update(extra)
            chunks.append(Chunk(text=text, metadata=metadata))
            index += 1
    return chunks
