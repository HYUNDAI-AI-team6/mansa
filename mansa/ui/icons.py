"""화면에서 쓰는 아이콘 모음 (Figma Components 페이지에서 내보낸 24px 아이콘).

아이콘 모양(path 데이터)은 assets/icons.json 에 있다.
선 아이콘은 한 가지 색, 채운 아이콘(선택된 메뉴용)은 바깥 모양 색과 안쪽 선 색 두 가지를 쓴다.
"""

import json
from pathlib import Path
from urllib.parse import quote

_DATA = json.loads((Path(__file__).parent / "assets" / "icons.json").read_text(encoding="utf-8"))

# 그리는 방식: s = 선, f = 채우기+선, F = 채우기만, d = 안쪽 선(채운 아이콘의 흰 선)
ICONS: dict[str, list[list[str]]] = _DATA["outline"]
FILLED: dict[str, list[list[str]]] = _DATA["filled"]

_ROUND = 'stroke-linecap="round" stroke-linejoin="round"'

# 서비스 심볼 (S2 펼친 매뉴얼)
LOGO_SYMBOL = (
    '<svg width="{size}" height="{size}" viewBox="0 0 96 96" fill="none" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 26.48C12 24.34 14.17 22.89 16.14 23.71L44.14 35.24C45.27 35.7 46 36.79 46 38.01'
    "V81.76C46 83.83 43.95 85.28 42 84.59L14 74.71C12.8 74.28 12 73.15 12 71.88V26.48Z"
    '" fill="{main}"/>'
    '<path d="M84 26.48C84 24.34 81.83 22.89 79.86 23.71L51.86 35.24C50.73 35.7 50 36.79 50 38.01'
    "V81.76C50 83.83 52.05 85.28 54 84.59L82 74.71C83.2 74.28 84 73.15 84 71.88V26.48Z"
    '" fill="{accent}"/>'
    '<path d="M48 5C49.3 12.2 51.8 14.7 59 16C51.8 17.3 49.3 19.8 48 27C46.7 19.8 44.2 17.3 37 16'
    'C44.2 14.7 46.7 12.2 48 5Z" fill="{main}"/></svg>'
)


def _path(kind: str, d: str, color: str, detail: str) -> str:
    """아이콘 조각(path) 하나를 그리는 방식(kind)에 맞게 만든다."""
    if kind == "s":
        return f'<path d="{d}" stroke="{color}" stroke-width="1.8" {_ROUND}/>'
    if kind == "f":
        return f'<path d="{d}" fill="{color}" stroke="{color}" stroke-width="1.8" {_ROUND}/>'
    if kind == "F":
        return f'<path d="{d}" fill="{color}"/>'
    return f'<path d="{d}" stroke="{detail}" stroke-width="1.8" {_ROUND}/>'


def svg(
    name: str,
    color: str = "#6B7280",
    size: int = 24,
    filled: bool = False,
    detail: str = "#FFFFFF",
) -> str:
    """아이콘 SVG 문자열을 만든다. filled=True 이면 채운 아이콘을 쓴다."""
    parts = (FILLED if filled and name in FILLED else ICONS)[name]
    body = "".join(_path(kind, d, color, detail) for kind, d in parts)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg">{body}</svg>'
    )


def logo(size: int = 40, main: str = "#3B5BF6", accent: str = "#9CB0FF") -> str:
    """서비스 심볼 SVG 문자열을 만든다."""
    return LOGO_SYMBOL.format(size=size, main=main, accent=accent)


def data_uri(svg_text: str) -> str:
    """CSS background-image 에 넣을 수 있는 data URI 로 바꾼다."""
    return 'url("data:image/svg+xml;utf8,' + quote(svg_text) + '")'
