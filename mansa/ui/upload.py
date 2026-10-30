"""문서 업로드(A2): PDF 한 개 + 문서 유형(기술/안전) + 소속 부서 → 업로드.

소속 부서 목록은 DB(기준정보)에서 읽는다. 문서 기록(documents_info.department_id)은 NULL을 허용하지만
앱에서는 기술·안전 문서 모두 부서를 꼭 골라야 한다.
업로드하면 문서를 등록하고(DocumentService) 처리(추출·청킹·태그·임베딩·저장)를 백그라운드에서 시작한다.
처리 결과는 기다리지 않고, 문서 관리 목록의 처리 상태로 확인한다.
"""

import logging  # 부서 목록을 못 불러온 원인을 서버 로그에 남기려고 쓴다
import os
from functools import cache
from html import escape

import gradio as gr

from features.documents.errors import DocumentStorageError, DuplicateDocumentError
from features.master.departments import DepartmentService
from ui import busy
from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView
from ui.theme import BRAND, TEXT3

MAX_MB = 50
SUBMIT_CLASSES = ["btn-primary", "sm-btn"]
CANCEL_CLASSES = ["btn-secondary", "sm-btn"]
TYPE_ICON = {"기술 문서": ("file", "blue", "#2F54EB"), "안전 문서": ("shield", "orange", "#C2410C")}
DEPT_BOX_CLASSES = ["select", "w-320"]
DEPT_PLACEHOLDER = "부서 선택"
BUSY_TITLE = "문서를 올리고 있어요"
BUSY_SUB = "처리가 끝나면 문서 관리에서 확인할 수 있어요"
# 화면의 문서 유형 이름 -> 서비스가 쓰는 값
TYPE_CODE = {"기술 문서": "tech", "안전 문서": "secure"}
logger = logging.getLogger(__name__)


@cache
def _departments() -> DepartmentService:
    """부서 서비스(DB). 처음 쓸 때 한 번만 만든다."""
    return DepartmentService()


def _load_department_names() -> list[str] | None:
    """부서 이름 목록을 DB 에서 읽는다. 실패하면 원인은 서버 로그에만 남기고 None 을 돌려준다."""
    try:
        return [d.name for d in _departments().list_all()]
    except Exception:
        logger.exception("failed to load departments")
        ui.warn("부서 목록을 불러오지 못했어요. 잠시 후 다시 시도해 주세요")
        return None


def _dept_box() -> gr.Dropdown:
    """부서 드롭다운을 DB 의 최신 목록으로 채우고 고른 값을 비운다.

    목록을 못 불러오면 보기 목록은 그대로 두고 고른 값만 비운다.
    """
    names = _load_department_names()
    if names is None:
        return gr.Dropdown(value="", elem_classes=DEPT_BOX_CLASSES)
    choices = [(DEPT_PLACEHOLDER, ""), *((name, name) for name in names)]
    return gr.Dropdown(choices=choices, value="", elem_classes=DEPT_BOX_CLASSES)


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
    state = {**state, "file": {"name": name, "size": _size_text(path), "path": path}}
    return state, None, file_row_html(state["file"])


def _clear_file(state: dict) -> tuple:
    """파일 줄의 X 를 누르면 고른 파일을 뺀다."""
    return {**state, "file": None}, ""


def _pick_type(state: dict, evt: gr.SelectData) -> tuple:
    """문서 유형 카드를 고른다."""
    picked = list(mock.DOC_TYPES)[evt.index]
    return {**state, "type": picked}, type_cards_html(picked)


def _reset() -> tuple:
    """입력을 모두 비우고 부서 목록을 DB 에서 다시 읽는다."""
    return _empty(), None, _dept_box(), type_cards_html(""), ""


def upload_error_message(exc: Exception) -> str:
    """등록하지 못한 이유를 사용자가 이해할 수 있는 문구로 바꾼다. 내부 오류 문구는 화면에 보이지 않는다."""
    if isinstance(exc, DuplicateDocumentError):
        return "이미 등록된 문서예요. 문서 관리에서 삭제한 뒤 다시 올려 주세요"
    if isinstance(exc, ValueError):
        return "올린 내용을 확인해 주세요. PDF 파일인지, 부서를 제대로 골랐는지 확인하고 다시 시도해 주세요"
    if isinstance(exc, DocumentStorageError):
        return "파일을 저장하지 못했어요. 잠시 후 다시 시도해 주세요"
    return "문서를 등록하지 못했어요. 잠시 후 다시 시도해 주세요"


def _department_id(name: str) -> int:
    """부서 이름으로 부서 ID를 찾는다. 없으면(그 사이에 지워졌으면) ValueError를 발생시킨다."""
    for department in _departments().list_all():
        if department.name == name:
            return department.id
    raise ValueError(f"unknown department: {name!r}")


def _register(state: dict, dept: str) -> None:
    """고른 파일을 등록하고 처리를 시작한다. 오류는 그대로 전달한다."""
    from features.processing.workflow import default_workflow  # DB·외부 서비스 설정은 처음 쓸 때 읽는다

    file = state["file"]
    default_workflow().upload(file["path"], file["name"], TYPE_CODE[state["type"]], _department_id(dept))


def _upload(state: dict, dept: str, store: dict):
    """필수값을 확인하고 문서를 등록한 뒤 처리를 시작한다.

    필수값은 파일·문서 유형·소속 부서이고, 문서 유형과 상관없이 모두 필요하다. 필수값이 빠졌으면 안내만 하고
    로딩 레이어는 띄우지 않는다.
    올리는 동안 화면 내용을 로딩 레이어가 덮고, 버튼은 '업로드 중' 으로 바뀌어 취소와 함께 잠긴다. 등록은 바로
    끝나고 처리는 백그라운드로 돌아가므로 처리 결과는 기다리지 않는다. 등록이 아무리 빨리 끝나도 로딩 레이어는
    최소 busy.MIN_SECONDS 동안 보여 준다. 등록하지 못하면 입력을 그대로 두고 이유를 알려 준다.
    """
    required = [("파일", state["file"]), ("문서 유형", state["type"]), ("소속 부서", dept)]
    missing = [name for name, ok in required if not ok]
    if missing:
        ui.warn(f"아직 정하지 않았어요: {' · '.join(missing)}")
        yield tuple(gr.skip() for _ in range(9))
        return
    started = busy.start()
    yield (
        *(gr.skip() for _ in range(6)),
        ui.loading_button("업로드 중", SUBMIT_CLASSES),
        gr.Button(interactive=False),
        busy.show(BUSY_TITLE, BUSY_SUB),
    )
    try:
        _register(state, dept)
    except Exception as exc:
        if isinstance(exc, DuplicateDocumentError):
            logger.info("duplicate upload rejected: existing document %s", exc.document_id)
        else:
            logger.exception("upload failed")
        busy.hold(started)
        ui.warn(upload_error_message(exc))
        yield (
            *(gr.skip() for _ in range(6)),
            ui.idle_button("업로드", SUBMIT_CLASSES),
            gr.Button(interactive=True),
            busy.hide(),
        )
        return
    busy.hold(started)
    ui.notify("업로드했어요. 문서 관리에서 처리 상태를 확인할 수 있어요")
    yield (
        gr.skip(),
        *_reset(),
        ui.idle_button("업로드", SUBMIT_CLASSES),
        gr.Button(interactive=True),
        busy.hide(),
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
        dept = ui.select_box([], DEPT_PLACEHOLDER, classes=["w-320"])  # 메뉴로 들어올 때 DB 에서 채운다
        with gr.Row(elem_classes=["form-actions"]):
            cancel = gr.Button("취소", elem_classes=CANCEL_CLASSES, scale=0, min_width=0)
            submit = gr.Button("업로드", elem_classes=SUBMIT_CLASSES, scale=0, min_width=0)
    layer = busy.component()  # 업로드하는 동안 위 내용을 덮는다

    form = [state, file, dept, types, file_row]
    file.upload(_pick_file, [file, state], [state, file, file_row])
    file_row.select(_clear_file, state, [state, file_row])
    types.select(_pick_type, state, [state, types])
    cancel.click(_reset, None, form)
    submit.click(
        _upload, [state, dept, store], [store, *form, submit, cancel, layer], show_progress="hidden"
    )
    return PageView(_reset, [], form)
