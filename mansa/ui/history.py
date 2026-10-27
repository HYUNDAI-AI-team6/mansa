"""질문 기록(U5): 지난 기술 Q&A 대화 목록. 항목을 누르면 기술 Q&A 에서 그 대화가 열린다."""

from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView
from ui.theme import TEXT3

PERIODS = ["오늘", "전체"]


def rows_html(keyword: str = "", period: str = "오늘") -> str:
    """검색어·기간에 맞는 대화 목록. data-i 는 mock.HISTORY 의 번호다."""
    word = (keyword or "").strip()
    rows = []
    for i, item in enumerate(mock.HISTORY):
        if period == "오늘" and item["day"] != "오늘":
            continue
        if word and word not in item["title"]:
            continue
        tags = (ui.tag(item["model"], "blue") if item["model"] else "") + ui.tag(item["task"])
        rows.append(
            f'<button type="button" class="hist-row" data-i="{i}">'
            f'<span class="time">{escape(item["time"])}</span>'
            f'<span class="body"><b>{escape(item["title"])}</b>'
            f'<span class="meta">{tags}<em>질문 {item["count"]}개</em></span></span>'
            f"{ui.icon('chevron-right', TEXT3, 18)}</button>"
        )
    if not rows:
        return '<div class="empty">조건에 맞는 대화가 없어요</div>'
    return f'<div class="hist-list">{"".join(rows)}</div>'


def build() -> PageView:
    """질문 기록 화면을 만든다. 목록 클릭은 app.py 에서 기술 Q&A 로 연결한다."""
    with gr.Column(elem_classes=["card", "hist-card"]):
        with gr.Row(elem_classes=["toolbar"]):
            keyword = ui.search_box("질문 검색", ["w-320"])
            gr.HTML("", padding=False, scale=1)
            period = ui.chip_radio(PERIODS, scale=0)
        rows = ui.click_list(rows_html())
    keyword.change(rows_html, [keyword, period], rows)
    period.input(rows_html, [keyword, period], rows)

    def reset() -> tuple:
        """메뉴로 들어오면 검색어를 비우고 오늘 목록을 보여 준다."""
        return "", "오늘", rows_html()

    return PageView(reset, [], [keyword, period, rows], links={"open": rows})
