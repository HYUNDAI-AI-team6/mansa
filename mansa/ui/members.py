"""회원 관리(A6): 회원 목록(권한·부서로 거르기) + 회원 수정 + 회원 등록.

users(사용자)와 admins(관리자) 테이블의 실제 계정을 features/auth/membersmanage.py 의 함수로 읽고 쓴다.
"""

from html import escape

import gradio as gr

from config import ADMIN_DEPT_LABEL
from features.auth import membersmanage
from features.master.errors import DuplicateError, NotFoundError, ValidationError
from ui import components as ui
from ui.page import PageView

COLUMNS = [
    ("회원", "1.2fr"),
    ("부서", "1fr"),
    ("권한", "70px"),
    ("등록일", "60px"),
    ("관리", "96px"),
]
ROLES = ["사용자", "관리자"]
ROLE_TAG = {"관리자": "purple", "사용자": "gray"}
ROLE_LABEL = {"user": "사용자", "admin": "관리자"}
ROLE_KEY = {label: key for key, label in ROLE_LABEL.items()}


# ------------------------------------------------------------------ 목록
def role_choices(members: list[dict]) -> list[tuple[str, str]]:
    """'전체 5 / 관리자 1 / 사용자 4' 칩."""
    counts = [("전체", len(members))] + [
        (r, sum(m["role"] == r for m in members)) for r in ("관리자", "사용자")
    ]
    return [(f"{name} {n}", name) for name, n in counts]


def _load() -> list[dict]:
    """DB 회원을 목록 모양으로 바꾼다. pk 는 수정할 때 DB 행을 찾는 id 다."""
    return [
        {
            "name": m["name"],
            "id": m["login_id"],
            "dept": m["dept"] or "-",
            "role": ROLE_LABEL[m["role"]],
            "date": m["created_at"].strftime("%m/%d"),
            "pk": m["id"],
        }
        for m in membersmanage.list_members()
    ]


def _row(i: int, m: dict) -> list[str]:
    """회원 한 줄. 관리 버튼의 data-i 는 목록 번호다."""
    who = (
        f'<span class="letter">{escape(m["name"][0])}</span>'
        f'<span class="who"><b>{escape(m["name"])}</b><em>{escape(m["id"])}</em></span>'
    )
    actions = f'<button type="button" class="mini-btn" data-i="{i}" data-v="edit">수정</button>'
    return [
        ui.cell(who),
        ui.cell(ui.dept_tag(m["dept"])),
        ui.cell(ui.tag(m["role"], ROLE_TAG[m["role"]])),
        ui.cell(f"<em>{escape(m['date'])}</em>"),
        ui.cell(actions),
    ]


def table(members: list[dict], role: str = "전체", dept: str = "") -> str:
    """조건에 맞는 회원 표."""
    rows = []
    for i, m in enumerate(members):
        if role not in ("전체", m["role"]) or dept not in ("", m["dept"]):
            continue
        rows.append(_row(i, m))
    html = ui.table_html(COLUMNS, rows, "조건에 맞는 회원이 없어요")
    return f'<div class="member-table">{html}</div>'


# ------------------------------------------------------------------ 등록·수정 칸
def _form(index=None, member: dict | None = None, depts: list[str] | None = None) -> tuple:
    """오른쪽 등록 칸 값. member 가 있으면 수정 모드로 채운다. depts 가 있으면 부서 목록도 새로 채운다.

    순서: 수정 중인 번호, 제목, 아이디, 이름, 부서, 권한, 비밀번호, 저장 버튼, 취소 버튼.
    수정할 때 아이디와 권한은 바꿀 수 없다(권한마다 테이블이 달라서).
    """
    editing = member is not None
    m = member or {"id": "", "name": "", "dept": "", "role": "사용자"}
    dept = {"value": "" if m["dept"] in ("", ADMIN_DEPT_LABEL) else m["dept"]}
    if depts is not None:
        dept["choices"] = [("부서 선택", ""), *[(d, d) for d in depts]]
    return (
        index,
        f'<h3 class="form-title">{"회원 수정" if editing else "회원 등록"}</h3>',
        gr.Textbox(value=m["id"], interactive=not editing),
        m["name"],
        gr.Dropdown(**dept),
        gr.Radio(value=m["role"], interactive=not editing),
        gr.Textbox(value="", placeholder="바꿀 때만 입력" if editing else "초기 비밀번호"),
        gr.Button(value="저장" if editing else "등록"),
        gr.Button(visible=editing),
    )


def _label(text: str) -> None:
    """입력칸 위 작은 제목."""
    gr.HTML(f'<span class="f-label">{escape(text)}</span>', padding=False)


# ------------------------------------------------------------------ 동작
def _act(store: dict, evt: gr.SelectData) -> tuple:
    """표의 수정 버튼: 그 회원의 값으로 오른쪽 칸을 채운다."""
    return _form(evt.index, store["members"][evt.index])


def _check_id(store: dict, uid: str) -> None:
    """아이디 중복 확인."""
    uid = (uid or "").strip()
    if not uid:
        ui.warn("아이디를 입력해 주세요")
    elif any(m["id"] == uid for m in store["members"]):
        ui.warn("이미 쓰고 있는 아이디예요")
    else:
        ui.notify("쓸 수 있는 아이디예요")


def _save(store, index, uid, name, dept, role, pw, f_role, f_dept) -> tuple:
    """등록 또는 수정 내용을 DB 에 저장한다."""
    uid, name = (uid or "").strip(), (name or "").strip()
    need = [("아이디", uid), ("이름", name)]
    if role == "사용자":  # 관리자 계정에는 부서가 없다
        need.append(("소속 부서", dept))
    if index is None:
        need.append(("초기 비밀번호", (pw or "").strip()))
    missing = [n for n, v in need if not v]
    if missing:
        ui.warn(f"아직 입력하지 않았어요: {' · '.join(missing)}")
        return (gr.skip(),) * 12
    dept_id = membersmanage.list_departments().get(dept)
    try:
        if index is None:
            membersmanage.create_member(ROLE_KEY[role], uid, name, dept_id, pw or "")
            ui.notify(f"{name} 회원을 등록했어요")
        else:
            m = store["members"][index]
            membersmanage.update_member(ROLE_KEY[m["role"]], m["pk"], uid, name, dept_id, pw or "")
            ui.notify(f"{name} 회원 정보를 저장했어요")
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        ui.warn(str(exc))
        return (gr.skip(),) * 12
    members = _load()
    store = {**store, "members": members}
    radio = gr.Radio(choices=role_choices(members), value=f_role)
    return (store, radio, table(members, f_role, f_dept), *_form())


# ------------------------------------------------------------------ 화면
def _member_list() -> dict:
    """왼쪽 회원 목록 카드: 권한 칩 · 부서 거르기 · 표. 내용은 메뉴로 들어올 때 DB 에서 채운다."""
    c = {}
    with gr.Column(elem_classes=["card", "content"]):
        with gr.Row(elem_classes=["toolbar"]):
            c["role"] = ui.chip_radio(role_choices([]), scale=0)
            gr.HTML("", padding=False, scale=1)
            c["dept"] = ui.select_box([], "부서 전체", scale=0, min_width=150)
        c["table"] = ui.click_list(table([]))
        gr.HTML('<p class="note">계정 삭제는 DB관리자에게 문의하세요</p>', padding=False)
    return c


def _member_form() -> dict:
    """오른쪽 회원 등록(수정) 카드."""
    c = {}
    with gr.Column(elem_classes=["card", "right-panel", "member-form"]):
        c["title"] = gr.HTML('<h3 class="form-title">회원 등록</h3>', padding=False)
        _label("아이디")
        with gr.Row(elem_classes=["id-row"]):
            c["uid"] = ui.text_input("아이디", scale=1)
            c["check"] = ui.small_button("중복 확인")
        _label("이름")
        c["name"] = ui.text_input("이름")
        _label("소속 부서")
        c["dept"] = ui.select_box([], "부서 선택")
        _label("권한")
        c["role"] = ui.chip_radio(ROLES)
        _label("초기 비밀번호")
        c["pw"] = ui.text_input("초기 비밀번호", password=True)
        c["submit"] = gr.Button("등록", elem_classes=["btn-primary", "full"])
        c["cancel"] = gr.Button("취소", elem_classes=["btn-secondary", "full"], visible=False)
    return c


def build(store: gr.State) -> PageView:
    """회원 관리 화면을 만든다."""
    edit_index = gr.State(None)
    with gr.Row(elem_classes=["body-row"]):
        lst = _member_list()
        f = _member_form()

    filters = [lst["role"], lst["dept"]]
    list_outs = [store, lst["role"], lst["table"]]
    fields = [f["uid"], f["name"], f["dept"], f["role"], f["pw"]]
    form_outs = [edit_index, f["title"], *fields, f["submit"], f["cancel"]]
    for comp in filters:
        comp.change(lambda s, r, d: table(s["members"], r, d), [store, *filters], lst["table"])
    lst["table"].select(_act, [store], form_outs)
    f["check"].click(_check_id, [store, f["uid"]], None)
    f["submit"].click(_save, [store, edit_index, *fields, *filters], list_outs + form_outs)
    f["cancel"].click(_form, None, form_outs)

    def reset(data: dict) -> tuple:
        """메뉴로 들어오면 DB 의 지금 회원·부서로 목록과 등록 칸을 처음부터 다시 채운다."""
        members, depts = _load(), list(membersmanage.list_departments())
        store = {**data, "members": members}
        radio = gr.Radio(choices=role_choices(members), value="전체")
        dept = gr.Dropdown(choices=[("부서 전체", ""), *[(d, d) for d in depts]], value="")
        return (store, radio, dept, table(members), *_form(depts=depts))

    return PageView(reset, [store], [store, *filters, lst["table"], *form_outs])
