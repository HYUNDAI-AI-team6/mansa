"""기준정보(A3): 부서, 설비 모델(시드 데이터), 작업 분류표·관계표(읽기 전용), 동의어 사전."""

from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView

DEPT_COLOR = {"유지보수팀": "blue", "안전팀": "orange", "검사·품질팀": "teal"}
MODEL_COLUMNS = [  # Figma A3: 모델명 칸만 남는 너비를 차지한다
    ("모델 ID", "64px"),
    ("모델명", "1fr"),
    ("제조사", "72px"),
    ("정격속도", "84px"),
    ("정격하중", "72px"),
    ("용도", "48px"),
    ("문서", "36px"),
]
RELATION_COLUMNS = [  # Figma A3: 330 · 300 · 260 · 260 비율
    ("작업", "330fr"),
    ("작업 위치", "300fr"),
    ("위험 유형", "260fr"),
    ("안전 문서 검색에 쓰는 말", "260fr"),
]
TABS = ["관계표", *mock.TAXONOMY]


def _head(title: str, tag: str = "", caption: str = "") -> str:
    """카드 머리 (제목 + 회색 태그 + 오른쪽 설명)."""
    tag_html = ui.tag(tag) if tag else ""
    cap = f'<span class="cap">{escape(caption)}</span>' if caption else ""
    return f'<div class="card-head"><div class="title">{escape(title)}{tag_html}</div>{cap}</div>'


def depts_html(depts: list[dict], docs: list[dict]) -> str:
    """부서 목록 (글자 타일 · 이름 · 설명 · 문서 수)."""
    rows = "".join(
        f'<div class="dept-row"><span class="letter {DEPT_COLOR.get(d["name"], "gray")}">'
        f'{escape(d["name"][0])}</span><span class="body"><b>{escape(d["name"])}</b>'
        f"<span>{escape(d['desc'])}</span></span>"
        f"<em>문서 {sum(doc['dept'] == d['name'] for doc in docs)}개</em></div>"
        for d in depts
    )
    return f'<div class="dept-list">{rows}</div>'


def models_html() -> str:
    """설비 모델 표 (고객센터 등록 모델 조회의 원본)."""
    keys = ["id", "name", "maker", "speed", "load", "use", "docs"]
    rows = [
        [ui.cell(f"<b>{escape(str(m[k]))}</b>" if k == "name" else escape(str(m[k]))) for k in keys]
        for m in mock.MODEL_SPECS
    ]
    head = _head("설비 모델", "시드 데이터")
    return f"{head}{ui.table_html(MODEL_COLUMNS, rows)}"


def taxonomy_html(tab: str) -> str:
    """작업 분류표 탭 내용. 관계표는 표로, 나머지는 태그 목록으로 보여 준다."""
    if tab != "관계표":
        tags = "".join(ui.tag(name) for name in mock.TAXONOMY[tab])
        return f'<div class="tag-wrap">{tags}</div>'
    rows = [
        [
            ui.cell(f"<b>{escape(r['work'])}</b>"),
            ui.cell("".join(ui.tag(p, "blue") for p in r["places"])),
            ui.cell("".join(ui.tag(h, "orange") for h in r["hazards"])),
            ui.cell(escape(" · ".join(r["places"] + r["hazards"]))),
        ]
        for r in mock.RELATIONS
    ]
    return ui.table_html(RELATION_COLUMNS, rows)


def synonyms_html() -> str:
    """동의어 사전 카드."""
    tags = "".join(ui.tag(f"{a} → {b}") for a, b in mock.SYNONYMS)
    head = (
        '<div class="card-head"><div class="title">동의어 사전'
        '<span class="cap">부서·제조사마다 다른 말을 같은 태그로 묶어요</span></div></div>'
    )
    return f'<div class="card syn-card">{head}<div class="tag-wrap">{tags}</div></div>'


def _add_dept(store: dict, name: str, desc: str) -> tuple:
    """부서를 등록한다(목데이터). 이름이 비었거나 이미 있으면 안내만 한다."""
    name, desc = (name or "").strip(), (desc or "").strip()
    if not name:
        ui.warn("부서 이름을 입력해 주세요")
        return (gr.skip(),) * 5
    if any(d["name"] == name for d in store["depts"]):
        ui.warn("이미 등록된 부서예요")
        return (gr.skip(),) * 5
    depts = [*store["depts"], {"name": name, "desc": desc or "설명 없음"}]
    ui.notify(f"‘{name}’ 부서를 등록했어요")
    store = {**store, "depts": depts}
    return store, depts_html(depts, store["docs"]), gr.Column(visible=False), "", ""


def _dept_card() -> dict:
    """부서 카드: 머리(부서 등록 버튼) + 접혀 있는 등록 칸 + 부서 목록."""
    c = {}
    with gr.Column(elem_classes=["card", "dept-card"]):
        with gr.Row(elem_classes=["card-head-row"]):
            gr.HTML(_head("부서"), padding=False, scale=1)
            c["open"] = ui.small_button("부서 등록")
        with gr.Column(visible=False, elem_classes=["inline-form"]) as c["form"]:
            c["name"] = ui.text_input("부서 이름")
            c["desc"] = ui.text_input("설명 (예: 검사 절차서 · 체크리스트)")
            with gr.Row(elem_classes=["form-actions"]):
                c["cancel"] = ui.small_button("취소")
                c["add"] = ui.small_button("등록", primary=True)
        c["list"] = gr.HTML(depts_html(mock.DEPT_INFO, mock.DOCUMENTS), padding=False)
    return c


def build(store: gr.State) -> PageView:
    """기준정보 화면을 만든다."""
    with gr.Row(elem_classes=["body-row", "master-top"]):
        d = _dept_card()
        gr.HTML(
            f'<div class="card model-card">{models_html()}</div>',
            padding=False,
            elem_classes=["grow-col"],
        )
    with gr.Column(elem_classes=["card", "tax-card"]):
        head = _head("작업 분류표 · 관계표", "읽기 전용")
        gr.HTML(head, padding=False)
        tab = ui.chip_radio(TABS)
        taxonomy = gr.HTML(taxonomy_html("관계표"), padding=False)
    gr.HTML(synonyms_html(), padding=False)

    d["open"].click(lambda: gr.Column(visible=True), None, d["form"])
    d["cancel"].click(
        lambda: (gr.Column(visible=False), "", ""), None, [d["form"], d["name"], d["desc"]]
    )
    d["add"].click(
        _add_dept,
        [store, d["name"], d["desc"]],
        [store, d["list"], d["form"], d["name"], d["desc"]],
    )
    tab.input(taxonomy_html, tab, taxonomy)

    def reset(data: dict) -> tuple:
        """메뉴로 들어오면 부서 문서 수를 다시 세고, 등록 칸과 탭을 처음으로 돌린다."""
        depts = depts_html(data["depts"], data["docs"])
        return depts, gr.Column(visible=False), "관계표", taxonomy_html("관계표")

    return PageView(reset, [store], [d["list"], d["form"], tab, taxonomy])
