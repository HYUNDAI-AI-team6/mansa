"""기준정보(A3): 부서, 설비 모델(시드 데이터), 작업 분류표·관계표(읽기 전용), 동의어 사전."""

import logging  # [DB 연동] 저장 실패 원인을 서버 로그에 남기려고 추가
from datetime import date  # [DB 연동] 등록일자(created_at)에 오늘 날짜를 넘기려고 추가
from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView

# [DB 연동] MySQL 에 쿼리를 보내는 함수. fetch_all = 조회(SELECT), execute = 입력·수정·삭제.
from util.mysql_connection import execute, fetch_all

# [DB 연동] departments.name, departments.description 컬럼이 varchar(50) 이라 이 글자 수까지만 저장된다.
MAX_LENGTH = 50
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
    """부서를 DB(departments)에 등록하고 목록에 더한다.

    이름이 비었거나 너무 길거나 이미 있으면, DB에 저장하지 못했을 때도 안내만 하고 목록은 그대로 둔다.
    """
    # 처리 순서: 입력 정리 → 화면에서 거를 수 있는 것(빈 이름·길이·화면 목록 중복)
    #            → [DB 연동] DB 중복 확인과 저장 → 화면 목록 갱신.
    # 앞의 거르는 단계에서는 DB 에 접속하지 않는다.
    # 돌려주는 값 5개는 등록 버튼 outputs [store, 부서 목록, 등록 칸, 이름 칸, 설명 칸] 순서다.
    # gr.skip() 은 "그 칸을 바꾸지 않는다"는 뜻이라, 실패해도 등록 칸과 입력한 글자가 그대로 남는다.
    name, desc = (name or "").strip(), (desc or "").strip()
    if not name:
        ui.warn("부서 이름을 입력해 주세요")
        return (gr.skip(),) * 5
    # [DB 연동] 컬럼 길이(varchar(50))를 넘으면 DB 가 오류를 내므로, 보내기 전에 막는다.
    if len(name) > MAX_LENGTH or len(desc) > MAX_LENGTH:
        ui.warn(f"부서 이름과 설명은 {MAX_LENGTH}자 이하로 입력해 주세요")
        return (gr.skip(),) * 5
    if any(d["name"] == name for d in store["depts"]):
        ui.warn("이미 등록된 부서예요")
        return (gr.skip(),) * 5
    # [DB 연동] 이 try 안에서 DB 에 저장한다. 성공할 때만 아래에서 화면 목록에 더한다.
    try:
        # 화면 목록(store)에는 없어도 DB 에는 있을 수 있다(앱을 다시 켠 뒤 등).
        # 이름에 UNIQUE 제약이 없어서 직접 확인한다. 비교는 DB 정렬 규칙을 따라 대소문자를 구분하지 않는다.
        # 확인과 저장이 따로라서 정말 동시에 같은 이름을 등록하면 둘 다 저장될 수 있다.
        if fetch_all("SELECT 1 FROM departments WHERE name = :name", {"name": name}):
            ui.warn("이미 등록된 부서예요")
            return (gr.skip(),) * 5
        # 등록일자(created_at)에는 시각 없이 오늘 날짜만 넘긴다. 앱이 있는 컴퓨터의 날짜라서
        # DB 서버(UTC)의 NOW() 를 쓸 때처럼 한국 시각과 하루 가까이 어긋나지 않는다.
        # 컬럼이 DATETIME 이라 DB 에는 '2026-10-27 00:00:00' 처럼 시각이 0시로 채워져 저장된다.
        # 값은 :name 같은 자리표시자로 넘긴다. SQL 문자열에 이어 붙이면 SQL 인젝션이 생긴다.
        execute(
            "INSERT INTO departments (name, created_at, description) "
            "VALUES (:name, :created_at, :description)",
            {"name": name, "created_at": date.today(), "description": desc},
        )
    except Exception:
        # DB 접속·쿼리 실패: 원인은 서버 로그에만 남기고 화면에는 일반 문구만 보여 준다.
        logging.getLogger(__name__).exception("failed to register department")
        ui.warn("부서를 저장하지 못했어요. 잠시 후 다시 시도해 주세요")
        return (gr.skip(),) * 5
    # 여기까지 오면 DB 저장이 끝난 상태다. 화면용 목록(store)에 같은 부서를 더하고 등록 칸을 닫는다.
    # 설명이 비면 DB 에는 빈 문자열로 저장되고, 화면에서만 "설명 없음"으로 보여 준다.
    # 이 목록은 DB 에서 읽은 게 아니라 목데이터(store) 기준이라, 앱을 다시 켜면 화면에서는 사라진다.
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
