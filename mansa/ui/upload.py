"""문서 업로드(A2): PDF 한 개 + 문서 유형(기술/안전) + 소속 부서 → 업로드.

목데이터라 실제 처리는 하지 않고, 문서 관리 목록에 '처리 중' 으로 추가만 한다.
"""

import os
from datetime import datetime
from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView
from ui.theme import BRAND, TEXT3

MAX_MB = 50
SUBMIT_CLASSES = ["btn-primary", "sm-btn"]
CANCEL_CLASSES = ["btn-secondary", "sm-btn"]
TYPE_ICON = {"기술 문서": ("file", "blue", "#2F54EB"), "안전 문서": ("shield", "orange", "#C2410C")}


def _empty() -> dict:
    """업로드 입력 초기값: 고른 파일 없음, 문서 유형 없음."""
    return {"file": None, "type": ""}


def dropzone_html() -> str:
    """파일 끌어오기 영역에 겹쳐 그리는 안내 (클릭·끌어오기는 아래 gr.File 이 받는다)."""
    return (
        '<div class="drop-face">'
        f"{ui.icon('upload', BRAND, 24)}"
        "<b>PDF를 끌어오거나 선택하세요</b>"
        f"<span>PDF · 최대 {MAX_MB}MB</span>"
        '<span class="fake-btn">파일 선택</span></div>'
    )


def file_row_html(file: dict | None) -> str:
    """고른 파일 한 줄 (이름 · 크기 · 지우기)."""
    if not file:
        return ""
    return (
        f'<div class="file-row">{ui.pdf_badge()}<b>{escape(file["name"])}</b>'
        f'<span class="size">{escape(file["size"])}</span>'
        f'<button type="button" class="icon-btn" data-i="0" aria-label="파일 빼기">'
        f"{ui.icon('x', TEXT3, 16)}</button></div>"
    )


def type_cards_html(selected: str) -> str:
    """문서 유형 카드 2개 (하나만 고른다)."""
    cards = []
    for i, (name, desc) in enumerate(mock.DOC_TYPES.items()):
        icon, color, stroke = TYPE_ICON[name]
        on = " on" if name == selected else ""
        cards.append(
            f'<button type="button" class="type-card{on}" data-i="{i}" aria-pressed="{bool(on)}">'
            f'<span class="tile {color}">{ui.icon(icon, stroke, 18)}</span>'
            f"<b>{escape(name)}</b><span>{escape(desc)}</span></button>"
        )
    return f'<div class="type-cards">{"".join(cards)}</div>'


def _size_text(path: str) -> str:
    """파일 크기 글자 (예: 2.4MB, 1MB 보다 작으면 KB)."""
    size = os.path.getsize(path) / 1024
    return f"{size / 1024:.1f}MB" if size >= 1024 else f"{max(size, 1):.0f}KB"


def _pick_file(path: str | None, state: dict) -> tuple:
    """끌어오거나 고른 파일을 확인하고 파일 줄로 보여 준다. PDF 가 아니면 안내만 한다."""
    if not path:
        return gr.skip(), gr.skip(), gr.skip()
    name = os.path.basename(path)
    if not name.lower().endswith(".pdf"):
        ui.warn("PDF 파일만 올릴 수 있어요")
        return state, None, file_row_html(state["file"])
    if os.path.getsize(path) > MAX_MB * 1024 * 1024:
        ui.warn(f"{MAX_MB}MB 이하 파일만 올릴 수 있어요")
        return state, None, file_row_html(state["file"])
    state = {**state, "file": {"name": name, "size": _size_text(path)}}
    return state, None, file_row_html(state["file"])


def _clear_file(state: dict) -> tuple:
    """파일 줄의 X 를 누르면 고른 파일을 뺀다."""
    return {**state, "file": None}, ""


def _pick_type(state: dict, evt: gr.SelectData) -> tuple:
    """문서 유형 카드를 고른다."""
    picked = list(mock.DOC_TYPES)[evt.index]
    return {**state, "type": picked}, type_cards_html(picked)


def _reset() -> tuple:
    """입력을 모두 비운다."""
    return _empty(), None, "", type_cards_html(""), ""


def _upload(state: dict, dept: str, store: dict):
    """필수값을 확인하고 문서 목록에 '처리 중' 으로 추가한다(목데이터).

    올리는 동안 버튼이 '업로드 중' 으로 바뀌고 취소와 함께 잠긴다.
    문서 업로드 기능(features/documents)이 생기면 여기서 그 함수를 부른다.
    """
    missing = [
        n
        for n, ok in (("파일", state["file"]), ("문서 유형", state["type"]), ("소속 부서", dept))
        if not ok
    ]
    if missing:
        ui.warn(f"아직 정하지 않았어요: {' · '.join(missing)}")
        yield tuple(gr.skip() for _ in range(8))
        return
    yield (
        *(gr.skip() for _ in range(6)),
        ui.loading_button("업로드 중", SUBMIT_CLASSES),
        gr.Button(interactive=False),
    )
    mock.wait()
    title = state["file"]["name"].rsplit(".", 1)[0]
    doc = {
        "title": title,
        "type": state["type"],
        "dept": dept,
        "status": "처리 중",
        "date": datetime.now().strftime("%m/%d"),
    }
    ui.notify("업로드했어요. 문서 관리에서 처리 상태를 확인할 수 있어요")
    yield (
        {**store, "docs": [*store["docs"], doc]},
        *_reset(),
        ui.idle_button("업로드", SUBMIT_CLASSES),
        gr.Button(interactive=True),
    )


def build(store: gr.State) -> PageView:
    """문서 업로드 화면을 만든다."""
    state = gr.State(_empty())
    with gr.Column(elem_classes=["card", "upload-card"]):
        gr.HTML('<h4 class="step">1. 파일</h4>', padding=False)
        with gr.Column(elem_classes=["drop-wrap"]):
            file = gr.File(
                file_types=[".pdf"],
                file_count="single",
                type="filepath",
                show_label=False,
                elem_classes=["dropzone"],
            )
            gr.HTML(dropzone_html(), padding=False, elem_classes=["drop-overlay"])
        file_row = ui.click_list("")
        gr.HTML('<h4 class="step">2. 문서 유형</h4>', padding=False)
        types = ui.click_list(type_cards_html(""))
        gr.HTML('<h4 class="step">3. 소속 부서</h4>', padding=False)
        dept = ui.select_box(mock.DEPARTMENTS, "부서 선택", classes=["w-320"])
        with gr.Row(elem_classes=["form-actions"]):
            cancel = gr.Button("취소", elem_classes=CANCEL_CLASSES, scale=0, min_width=0)
            submit = gr.Button("업로드", elem_classes=SUBMIT_CLASSES, scale=0, min_width=0)

    form = [state, file, dept, types, file_row]
    file.upload(_pick_file, [file, state], [state, file, file_row])
    file_row.select(_clear_file, state, [state, file_row])
    types.select(_pick_type, state, [state, types])
    cancel.click(_reset, None, form)
    submit.click(
        _upload, [state, dept, store], [store, *form, submit, cancel], show_progress="hidden"
    )
    return PageView(_reset, [], form)
