"""문서 관리(A1): 문서 현황 + 목록(처리 상태: 처리 중 · 완료 · 실패) + 휴지통으로 삭제."""

from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView
from ui.theme import TEXT3

COLUMNS = [
    ("문서", "1fr"),
    ("유형", "116px"),
    ("부서", "128px"),
    ("처리 상태", "128px"),
    ("등록일", "64px"),
    ("", "48px"),
]
# 현황 카드: (이름, 설명, 아이콘, 색)
STATS = [
    ("기술 문서", "매뉴얼 · 사양서", "file", "blue"),
    ("안전 문서", "법규 · 지침 · 사내 규정", "shield", "orange"),
    ("처리 중", "추출 · 청킹 · 색인 진행", "refresh", "blue"),
    ("실패", "다시 올려 주세요", "alert", "red"),
]
ICON_COLOR = {"blue": "#2F54EB", "orange": "#C2410C", "red": "#B91C1C"}


def stats_html(docs: list[dict]) -> str:
    """현황 카드 4개."""
    cards = []
    for name, desc, icon, color in STATS:
        key = "type" if name.endswith("문서") else "status"
        count = sum(d[key] == name for d in docs)
        cards.append(
            f'<div class="card stat"><span class="tile {color}">'
            f"{ui.icon(icon, ICON_COLOR[color], 20)}</span>"
            f'<div><span class="label">{escape(name)}</span><b>{count}</b>'
            f'<span class="desc">{escape(desc)}</span></div></div>'
        )
    return f'<div class="stats">{"".join(cards)}</div>'


def table(docs: list[dict], keyword: str = "") -> str:
    """문서 표. 휴지통 버튼의 data-i 는 docs 의 번호다."""
    word = (keyword or "").strip()
    rows = []
    for i, d in enumerate(docs):
        if word not in d["title"]:
            continue
        trash = (
            f'<button type="button" class="icon-btn" data-i="{i}" '
            f'aria-label="{escape(d["title"])} 삭제">{ui.icon("trash", TEXT3, 18)}</button>'
        )
        rows.append(
            [
                ui.cell(f"{ui.pdf_badge()}<b>{escape(d['title'])}</b>"),
                ui.cell(ui.tag(d["type"], ui.TYPE_TAG[d["type"]])),
                ui.cell(ui.dept_tag(d["dept"])),
                ui.cell(ui.tag(d["status"], ui.STATUS_TAG[d["status"]])),
                ui.cell(f"<em>{escape(d['date'])}</em>"),
                ui.cell(trash),
            ]
        )
    return ui.table_html(COLUMNS, rows, "조건에 맞는 문서가 없어요")


def _delete(store: dict, keyword: str, evt: gr.SelectData) -> tuple:
    """휴지통을 누른 문서를 지운다(목데이터). 문서 삭제 기능이 생기면 그 함수를 부른다."""
    docs = list(store["docs"])
    removed = docs.pop(evt.index)
    ui.notify(f"‘{removed['title']}’ 문서를 삭제했어요")
    store = {**store, "docs": docs}
    return store, stats_html(docs), table(docs, keyword)


def build(store: gr.State) -> PageView:
    """문서 관리 화면을 만든다. '문서 업로드' 버튼은 app.py 에서 업로드 화면으로 연결한다."""
    docs = mock.DOCUMENTS
    with gr.Row(elem_classes=["section-row"]):
        gr.HTML(ui.section_title("현황"), padding=False, scale=1)
        upload = gr.Button(
            "문서 업로드", elem_classes=["btn-primary", "sm-btn"], scale=0, min_width=0
        )
    stats = gr.HTML(stats_html(docs), padding=False)
    with gr.Column(elem_classes=["card"]):
        keyword = ui.search_box("문서명 검색", ["w-280"])
        result = ui.click_list(table(docs))

    keyword.change(lambda s, k: table(s["docs"], k), [store, keyword], result)
    result.select(_delete, [store, keyword], [store, stats, result])

    def reset(data: dict) -> tuple:
        """메뉴로 들어오면 검색어를 비우고 지금 문서 목록으로 다시 그린다."""
        return "", stats_html(data["docs"]), table(data["docs"])

    return PageView(reset, [store], [keyword, stats, result], links={"upload": upload})
