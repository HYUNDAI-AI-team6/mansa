"""안전기준·기술사양서 청커가 함께 쓰는 길이 기준과 문자열·표 묶음 도구."""

import re

# 청크 본문 길이(글자 수). 머리말을 붙이기 전의 본문 기준이며 한 줄의 상한은 머리말 여유를 둔다.
MIN_CHUNK_CHARS = 300
MAX_CHUNK_CHARS = 1200
HARD_MAX_CHARS = 1500
PREFIX_ALLOWANCE = 100
MAX_LINE_CHARS = HARD_MAX_CHARS - PREFIX_ALLOWANCE

_SENTENCE_END = re.compile(r"(?<=\.)\s+")
# 수식 폰트(HyhwpEQ 등)가 쓰는 사설 영역 문자. 폰트 고유 코드라 사람이 읽을 수 없고 임베딩에 잡음이 된다.
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff]")
_READABLE = re.compile(r"[A-Za-z0-9가-힣]")


def split_text(text: str) -> list[str]:
    """한 줄이 MAX_LINE_CHARS를 넘으면 문장 끝(마침표)에서 나누고, 문장 하나가 길면 글자 수로 자른다."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > MAX_LINE_CHARS:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:MAX_LINE_CHARS])
            sentence = sentence[MAX_LINE_CHARS:]
        if current and len(current) + 1 + len(sentence) > MAX_LINE_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def strip_private_use(text: str) -> str:
    """읽을 수 없는 사설 영역 문자(수식 폰트 글리프)를 지우고, 지워서 비게 된 줄은 버린다.

    사설 영역 문자가 없는 줄은 그대로 둔다. 있던 줄은 연속 공백을 줄이고, 글자·숫자가 하나도 남지
    않으면(예: 기호 "±"만 남은 수식 조각) 줄 전체를 버린다. 추출 결과는 바꾸지 않고 청크를 만들 때만
    적용해서, 나중에 수식을 읽을 수 있게 되면 원본 텍스트를 다시 쓸 수 있다.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        if not _PRIVATE_USE.search(line):
            lines.append(line)
            continue
        cleaned = re.sub(r"[ \t]{2,}", " ", _PRIVATE_USE.sub("", line)).strip()
        if _READABLE.search(cleaned):
            lines.append(cleaned)
    return "\n".join(lines)


def clean_cell(cell: str) -> str:
    """셀 안의 사설 영역 문자를 지우고 줄바꿈과 연속 공백을 공백 하나로 줄인다."""
    return re.sub(r"\s+", " ", _PRIVATE_USE.sub("", cell)).strip()


def pack_lines(lines: list[str]) -> list[str]:
    """줄을 순서대로 MAX_CHUNK_CHARS 이내의 본문으로 묶는다. 너무 긴 줄은 문장 단위로 나눈다.

    마지막 묶음이 MIN_CHUNK_CHARS보다 짧고 앞 묶음과 합쳐도 한 줄 상한 안이면 앞 묶음에 붙인다.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        for piece in split_text(line) if len(line) > MAX_LINE_CHARS else [line]:
            if current and size + 1 + len(piece) > MAX_CHUNK_CHARS:
                chunks.append(current)
                current, size = [], 0
            size = size + 1 + len(piece) if current else len(piece)
            current.append(piece)
    if current:
        chunks.append(current)
    texts = ["\n".join(chunk) for chunk in chunks]
    if len(texts) >= 2 and len(texts[-1]) < MIN_CHUNK_CHARS and len(texts[-2]) + 1 + len(texts[-1]) <= MAX_LINE_CHARS:
        texts[-2:] = [texts[-2] + "\n" + texts[-1]]
    return texts


def pack_rows(rows: list[tuple[str, str | None]], title: str = "") -> list[tuple[str, str | None]]:
    """표 행 문장을 MAX_CHUNK_CHARS 이내의 청크 본문으로 묶고 (본문, 묶음 첫 행의 조항)을 돌려준다.

    title이 있으면 모든 묶음 맨 앞에 붙인다. 한 행이 MAX_LINE_CHARS를 넘으면 문장 단위로 나눈다.
    """
    items: list[tuple[str, str | None]] = []
    current: list[str] = []
    clause: str | None = None
    size = len(title)

    def flush() -> None:
        """모인 행을 청크 본문 하나로 내보낸다."""
        if current:
            items.append(("\n".join(([title] if title else []) + current), clause))

    for text, row_clause in rows:
        for piece in split_text(text) if len(text) > MAX_LINE_CHARS else [text]:
            if current and size + len(piece) + 1 > MAX_CHUNK_CHARS:
                flush()
                current, clause, size = [], None, len(title)
            if not current:
                clause = row_clause
            current.append(piece)
            size += len(piece) + 1
    flush()
    return items
