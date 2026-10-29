"""문서 조회(U7): 등록된 매뉴얼·안전 문서를 유형·부서·이름으로 찾아본다."""

from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView
from ui.sample_pdf import doc_pdf_base64

COLUMNS = [("문서", "1fr"), ("유형", "136px"), ("부서", "148px"), ("등록일", "96px")]
DEPT_PLACEHOLDER = "부서 전체"

# 제목을 누르면 PDF 를 새 탭에서 연다 (브라우저 PDF 보기에서 내려받기도 할 수 있다).
OPEN_PDF_JS = """element.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-pdf]');
  if (!btn) return;
  const bytes = Uint8Array.from(atob(btn.dataset.pdf), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
  window.open(url, '_blank');
  setTimeout(() => URL.revokeObjectURL(url), 60000);
});"""


def title_button(doc: dict) -> str:
    """PDF 표시 + 문서 이름. 누르면 그 문서의 PDF 가 열린다(지금은 시연용 샘플)."""
    label = f"{ui.pdf_badge()}<b>{escape(doc['title'])}</b>"
    return (
        f'<button type="button" class="doc-open" data-pdf="{doc_pdf_base64(doc)}" '
        f'aria-label="{escape(doc["title"])} PDF 열기">{label}</button>'
    )


def load_completed() -> list[dict]:
    """documents_info 에서 처리 상태가 완료인 문서만 읽는다. DB 연결이 필요하다."""
    # ui.documents 가 이 모듈을 import 하므로 순환을 피하려고 함수 안에서 불러온다.
    from ui.documents import load_docs

    return [d for d in load_docs() if d["status"] == "완료"]


def dept_choices(docs: list[dict]) -> list[tuple[str, str]]:
    """부서 드롭다운 보기 (이름, 값). 문서에 나오는 부서만, 부서 없는 문서의 '-' 는 뺀다."""
    names = sorted({d["dept"] for d in docs} - {"-"})
    return [(DEPT_PLACEHOLDER, "")] + [(n, n) for n in names]


def _type_order(doc: dict) -> int:
    """기술 문서를 먼저, 안전 문서를 나중에 보여 준다."""
    return list(mock.DOC_TYPES).index(doc["type"])


def type_choices(docs: list[dict]) -> list[tuple[str, str]]:
    """'전체 6 / 기술 문서 3 / 안전 문서 3' 칩 (개수 포함 이름, 값)."""
    counts = [("전체", len(docs))] + [
        (t, sum(d["type"] == t for d in docs)) for t in mock.DOC_TYPES
    ]
    return [(f"{name} {n}", name) for name, n in counts]


def table(docs: list[dict], doc_type: str, dept: str, keyword: str) -> str:
    """조건에 맞는 문서 표."""
    word = (keyword or "").strip()
    picked = [
        d
        for d in sorted(docs, key=_type_order)
        if doc_type in ("전체", d["type"]) and dept in ("", d["dept"]) and word in d["title"]
    ]
    rows = [
        [
            ui.cell(title_button(d)),
            ui.cell(ui.tag(d["type"], ui.TYPE_TAG[d["type"]])),
            ui.cell(ui.dept_tag(d["dept"])),
            ui.cell(f"<em>{escape(d['date'])}</em>"),
        ]
        for d in picked
    ]
    return ui.table_html(COLUMNS, rows, "조건에 맞는 문서가 없어요")


def build() -> PageView:
    """문서 조회 화면을 만든다. 메뉴로 들어오면 documents_info 의 완료 문서로 다시 그린다."""
    with gr.Column(elem_classes=["card", "filter-card"]):
        doc_type = ui.chip_radio(type_choices([]))
        with gr.Row(elem_classes=["toolbar"]):
            dept = ui.select_box([], DEPT_PLACEHOLDER, scale=0, min_width=240)
            keyword = ui.search_box("문서명 검색", scale=1)
    with gr.Column(elem_classes=["card"]):
        result = gr.HTML(table([], "전체", "", ""), js_on_load=OPEN_PDF_JS, padding=False)

    inputs = [doc_type, dept, keyword]
    for comp in (doc_type, dept, keyword):
        comp.change(lambda t, d, k: table(load_completed(), t, d, k), inputs, result)

    def reset() -> tuple:
        """메뉴로 들어오면 조건을 비우고 DB 의 지금 완료 문서로 다시 그린다."""
        docs = load_completed()
        return (
            gr.Radio(choices=type_choices(docs), value="전체"),
            gr.Dropdown(choices=dept_choices(docs), value=""),
            "",
            table(docs, "전체", "", ""),
        )

    return PageView(reset, [], [doc_type, dept, keyword, result])
