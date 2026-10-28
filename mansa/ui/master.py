"""기준정보(A3): 부서(DB), 설비 모델(파일), 작업 분류표·관계표(읽기 전용), 동의어 사전."""

import logging  # 불러오기·저장 실패 원인을 서버 로그에 남기려고 쓴다
from functools import cache
from html import escape

import gradio as gr

from features.master.departments import DepartmentService
from features.master.equipment import EquipmentModelService
from features.master.errors import DuplicateError, ValidationError
from features.master.models import Department, DepartmentInput, EquipmentModel, Taxonomy
from features.master.taxonomy import TaxonomyService
from ui import components as ui
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
TABS = ["관계표", *Taxonomy().by_axis()]  # 분류표 네 축 이름은 서비스가 정한다


@cache
def _departments() -> DepartmentService:
    """부서 서비스(DB). 처음 쓸 때 한 번만 만든다."""
    return DepartmentService()


@cache
def _models() -> EquipmentModelService:
    """설비 모델 서비스(data/master 파일)."""
    return EquipmentModelService()


@cache
def _taxonomy() -> TaxonomyService:
    """분류표·관계표·동의어 서비스(data/taxonomy 파일)."""
    return TaxonomyService.from_directory()


def _load_departments() -> list[Department] | None:
    """부서 목록을 DB 에서 읽는다. 실패하면 원인은 서버 로그에만 남기고 None 을 돌려준다."""
    try:
        return _departments().list_all()
    except Exception:
        logging.getLogger(__name__).exception("failed to load departments")
        ui.warn("부서 목록을 불러오지 못했어요. 잠시 후 다시 시도해 주세요")
        return None


def _load_models() -> list[EquipmentModel] | None:
    """설비 모델 목록을 파일에서 읽는다. 실패하면 None 을 돌려주고 화면은 그대로 둔다."""
    try:
        return _models().list_models()
    except Exception:
        logging.getLogger(__name__).exception("failed to load equipment models")
        ui.warn("설비 모델을 불러오지 못했어요. 잠시 후 다시 시도해 주세요")
        return None


def _head(title: str, tag: str = "", caption: str = "") -> str:
    """카드 머리 (제목 + 회색 태그 + 오른쪽 설명)."""
    tag_html = ui.tag(tag) if tag else ""
    cap = f'<span class="cap">{escape(caption)}</span>' if caption else ""
    return f'<div class="card-head"><div class="title">{escape(title)}{tag_html}</div>{cap}</div>'


def depts_html(depts: list[Department], docs: list[dict]) -> str:
    """부서 목록 (글자 타일 · 이름 · 설명 · 문서 수). 문서 수는 문서 DB 가 붙기 전까지 목데이터 기준이다."""
    rows = "".join(
        f'<div class="dept-row"><span class="letter {DEPT_COLOR.get(d.name, "gray")}">'
        f'{escape(d.name[0])}</span><span class="body"><b>{escape(d.name)}</b>'
        f"<span>{escape(d.description or '설명 없음')}</span></span>"
        f"<em>문서 {sum(doc['dept'] == d.name for doc in docs)}개</em></div>"
        for d in depts
    )
    return f'<div class="dept-list">{rows}</div>'


def models_html(models: list[EquipmentModel]) -> str:
    """설비 모델 표 (고객센터 등록 모델 조회의 원본)."""
    rows = [
        [
            ui.cell(escape(m.display_id)),
            ui.cell(f"<b>{escape(m.name)}</b>"),
            ui.cell(escape(m.maker)),
            ui.cell(escape(m.speed_text)),
            ui.cell(escape(m.load_text)),
            ui.cell(escape(m.usage)),
            ui.cell(str(m.doc_count)),
        ]
        for m in models
    ]
    head = _head("설비 모델", "시드 데이터")
    table = ui.table_html(MODEL_COLUMNS, rows, empty="등록된 설비 모델이 없어요")
    return f'<div class="card model-card">{head}{table}</div>'


def taxonomy_html(tab: str) -> str:
    """작업 분류표 탭 내용. 관계표는 표로, 나머지는 태그 목록으로 보여 준다."""
    service = _taxonomy()
    if tab != "관계표":
        tags = "".join(ui.tag(name) for name in service.taxonomy.by_axis()[tab])
        return f'<div class="tag-wrap">{tags}</div>'
    rows = [
        [
            ui.cell(f"<b>{escape(r.work)}</b>"),
            ui.cell("".join(ui.tag(p, "blue") for p in r.places)),
            ui.cell("".join(ui.tag(h, "orange") for h in r.hazards)),
            ui.cell(escape(" · ".join(r.places + r.hazards))),
        ]
        for r in service.relations.values()
    ]
    return ui.table_html(RELATION_COLUMNS, rows)


def synonyms_html() -> str:
    """동의어 사전 카드."""
    tags = "".join(ui.tag(f"{a} → {b}") for a, b in _taxonomy().synonyms.items())
    head = (
        '<div class="card-head"><div class="title">동의어 사전'
        '<span class="cap">부서·제조사마다 다른 말을 같은 태그로 묶어요</span></div></div>'
    )
    return f'<div class="card syn-card">{head}<div class="tag-wrap">{tags}</div></div>'


def _add_dept(store: dict, name: str, desc: str) -> tuple:
    """부서를 DB(departments)에 등록하고 목록을 DB 기준으로 다시 그린다.

    이름이 비었거나 너무 길거나 이미 있으면, 저장하지 못했을 때도 안내만 하고 화면은 그대로 둔다.
    """
    # 검사(빈 이름·길이·중복)와 저장은 DepartmentService.create 가 한다.
    # 값은 서비스 안에서 :name 같은 자리표시자로 DB 에 넘기므로 SQL 인젝션이 생기지 않는다.
    # 돌려주는 값 4개는 등록 버튼 outputs [부서 목록, 등록 칸, 이름 칸, 설명 칸] 순서다.
    # gr.skip() 은 "그 칸을 바꾸지 않는다"는 뜻이라, 실패해도 등록 칸과 입력한 글자가 그대로 남는다.
    try:
        _departments().create(DepartmentInput(name or "", desc or ""))
    except (ValidationError, DuplicateError) as e:
        ui.warn(str(e))  # 사용자에게 보여도 되는 문구로 서비스가 만든 메시지다
        return (gr.skip(),) * 4
    except Exception:
        # DB 접속·쿼리 실패: 원인은 서버 로그에만 남기고 화면에는 일반 문구만 보여 준다.
        logging.getLogger(__name__).exception("failed to register department")
        ui.warn("부서를 저장하지 못했어요. 잠시 후 다시 시도해 주세요")
        return (gr.skip(),) * 4
    ui.notify(f"‘{(name or '').strip()}’ 부서를 등록했어요")
    # 저장은 끝났다. 목록은 DB 에서 다시 읽는다(읽기만 실패하면 목록은 그대로 두고 등록 칸은 닫는다).
    depts = _load_departments()
    listing = gr.skip() if depts is None else depts_html(depts, store["docs"])
    return listing, gr.Column(visible=False), "", ""


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
        c["list"] = gr.HTML(depts_html([], []), padding=False)  # 메뉴로 들어올 때 DB 에서 채운다
    return c


def build(store: gr.State) -> PageView:
    """기준정보 화면을 만든다."""
    with gr.Row(elem_classes=["body-row", "master-top"]):
        d = _dept_card()
        # 설비 모델 표는 메뉴로 들어올 때 파일에서 채운다(파일을 고치면 다시 들어올 때 반영된다).
        models = gr.HTML(models_html([]), padding=False, elem_classes=["grow-col"])
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
        [d["list"], d["form"], d["name"], d["desc"]],
    )
    tab.input(taxonomy_html, tab, taxonomy)

    def reset(data: dict) -> tuple:
        """메뉴로 들어오면 부서(DB)·설비 모델(파일)을 다시 읽고, 등록 칸과 탭을 처음으로 돌린다.

        읽기에 실패한 목록은 gr.skip() 으로 그대로 두고 안내만 띄운다.
        """
        depts, found = _load_departments(), _load_models()
        return (
            gr.skip() if depts is None else depts_html(depts, data["docs"]),
            gr.skip() if found is None else models_html(found),
            gr.Column(visible=False),
            "관계표",
            taxonomy_html("관계표"),
        )

    return PageView(reset, [store], [d["list"], models, d["form"], tab, taxonomy])
