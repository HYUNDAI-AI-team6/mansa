"""Figma 디자인 값(색·글꼴·간격)을 Gradio 테마와 CSS로 옮긴 파일.

화면 모양 CSS 는 assets/*.css 에 있고, 아이콘처럼 코드로 만들어야 하는 CSS 만 여기서 만든다.
"""

from pathlib import Path

import gradio as gr

from ui import icons
from ui.navigation import PAGES

BRAND = "#3B5BF6"
TEXT = "#1A1D23"
TEXT2 = "#6B7280"
TEXT3 = "#9CA3AF"
WHITE_SOFT = "rgba(255,255,255,0.78)"

ASSETS = Path(__file__).parent / "assets"
CSS_FILES = ["base.css", "shell.css", "login.css", "qa.css", "pages.css"]

TAG_COLORS = {
    "blue": ("#EAF0FF", "#2F54EB"),
    "orange": ("#FFF1E6", "#C2410C"),
    "teal": ("#E6F7F5", "#0F766E"),
    "purple": ("#F3E8FF", "#7E22CE"),
    "green": ("#E8F7EE", "#15803D"),
    "red": ("#FDECEC", "#B91C1C"),
    "yellow": ("#FFF8DB", "#A16207"),
    "gray": ("#F1F2F4", "#4B5563"),
}


def build_theme() -> gr.themes.Base:
    """기본 테마에 MANSA 글꼴과 바탕색을 적용한다."""
    font = gr.themes.GoogleFont("Noto Sans KR", weights=(400, 500, 700))
    return gr.themes.Base(
        primary_hue="blue",
        neutral_hue="gray",
        font=[font, "Apple SD Gothic Neo", "Malgun Gothic", "sans-serif"],
    ).set(
        body_background_fill="#F4F5F7",
        body_text_color=TEXT,
        block_background_fill="transparent",
        block_border_width="0px",
        block_shadow="none",
        block_padding="0px",
        layout_gap="0px",
    )


def _icon_rule(selector: str, art: str) -> str:
    """아이콘 하나를 ::before 배경으로 넣는 CSS 규칙."""
    return f"{selector}::before{{background-image:{icons.data_uri(art)}}}"


def _nav_icon_css() -> str:
    """메뉴 버튼 아이콘을 상태(기본·선택)와 메뉴바(흰색·파란색)별로 만든다."""
    rules = []
    for name in sorted({p.icon for p in PAGES} | {"logout"}):
        base = f".sidebar .nav-btn.ic-{name}"
        admin = f".sidebar.admin .nav-btn.ic-{name}"
        rules += [
            _icon_rule(base, icons.svg(name, TEXT2)),
            _icon_rule(f"{base}.active", icons.svg(name, BRAND, filled=True)),
            _icon_rule(admin, icons.svg(name, WHITE_SOFT)),
            _icon_rule(f"{admin}.active", icons.svg(name, "#FFFFFF", filled=True, detail=BRAND)),
        ]
    rules.append(_icon_rule(".send-btn", icons.svg("send", "#FFFFFF")))
    chevron = icons.data_uri(icons.svg("chevron-right", TEXT3))
    search = icons.data_uri(icons.svg("search", TEXT3, 18))
    rules.append(f":root{{--icon-chevron:{chevron};--icon-search:{search}}}")
    return "\n".join(rules)


def _tag_css() -> str:
    """태그 색상 규칙을 만든다."""
    return "\n".join(
        f".tag.{name}{{background:{bg};color:{fg}}}" for name, (bg, fg) in TAG_COLORS.items()
    )


def build_head() -> str:
    """페이지 <head>에 넣을 스크립트. 한글 조합 중 엔터가 전송되지 않게 하는 chat_keys.js 를 싣는다."""
    script = (ASSETS / "chat_keys.js").read_text(encoding="utf-8")
    return f"<script>{script}</script>"


def build_css() -> str:
    """앱 전체 CSS를 하나로 묶는다: assets/*.css + 태그 색 + 아이콘."""
    files = [(ASSETS / name).read_text(encoding="utf-8") for name in CSS_FILES]
    return "\n".join([*files, _tag_css(), _nav_icon_css()])
