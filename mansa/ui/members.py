"""회원 관리(A6): 회원 목록(권한·부서로 거르기) + 수정·삭제(휴지통) + 회원 등록.

목데이터라 비밀번호는 저장하지 않는다. features/auth 의 회원 기능이 생기면 그 함수를 부른다.
"""

from datetime import datetime
from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock
from ui.page import PageView
from ui.theme import TEXT3

COLUMNS = [
    ("회원", "1.2fr"),
    ("부서", "1fr"),
    ("권한", "70px"),
    ("등록일", "60px"),
    ("관리", "96px"),
]
ROLES = ["사용자", "관리자"]
ROLE_TAG = {"관리자": "purple", "사용자": "gray"}


# ------------------------------------------------------------------ 목록
def role_choices(members: list[dict]) -> list[tuple[str, str]]:
    """'전체 5 / 관리자 1 / 사용자 4' 칩."""
    counts = [("전체", len(members))] + [
        (r, sum(m["role"] == r for m in members)) for r in ("관리자", "사용자")
    ]
    return [(f"{name} {n}", name) for name, n in counts]


def _row(i: int, m: dict) -> list[str]:
    """회원 한 줄. 관리 버튼의 data-v 로 수정/삭제를 구분한다."""
    who = (
        f'<span class="letter">{escape(m["name"][0])}</span>'
        f'<span class="who"><b>{escape(m["name"])}</b><em>{escape(m["id"])}</em></span>'
    )
    actions = (
        f'<button type="button" class="mini-btn" data-i="{i}" data-v="edit">수정</button>'
        f'<button type="button" class="icon-btn" data-i="{i}" data-v="delete" '
        f'aria-label="{escape(m["name"])} 삭제">{ui.icon("trash", TEXT3, 18)}</button>'
    )
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
def _form(index=None, member: dict | None = None) -> tuple:
    """오른쪽 등록 칸 값. member 가 있으면 수정 모드로 채운다.

    순서: 수정 중인 번호, 제목, 아이디, 이름, 부서, 권한, 비밀번호, 저장 버튼, 취소 버튼.
    """
    editing = member is not None
    m = member or {"id": "", "name": "", "dept": "", "role": "사용자"}
    return (
        index,
        f'<h3 class="form-title">{"회원 수정" if editing else "회원 등록"}</h3>',
        gr.Textbox(value=m["id"], interactive=not editing),
        m["name"],
        m["dept"],
        m["role"],
        gr.Textbox(value="", placeholder="바꿀 때만 입력" if editing else "초기 비밀번호"),
        gr.Button(value="저장" if editing else "등록"),
        gr.Button(visible=editing),
    )


def _label(text: str) -> None:
    """입력칸 위 작은 제목."""
    gr.HTML(f'<span class="f-label">{escape(text)}</span>', padding=False)


# ------------------------------------------------------------------ 동작
def _remove(members: list[dict], i: int, me: dict | None) -> list[dict] | None:
    """회원을 지운다. 본인 계정과 마지막 남은 관리자는 막는다(None 반환)."""
    target = members[i]
    if me and target["id"] == me.get("id"):
        ui.warn("본인 계정은 삭제할 수 없어요")
        return None
    admins = [m for m in members if m["role"] == "관리자"]
    if target["role"] == "관리자" and len(admins) == 1:
        ui.warn("마지막 남은 관리자는 삭제할 수 없어요")
        return None
    ui.notify(f"{target['name']} 회원을 삭제했어요")
    return [m for k, m in enumerate(members) if k != i]


def _act(store: dict, role: str, dept: str, me: dict | None, editing, evt: gr.SelectData) -> tuple:
    """표의 수정 / 휴지통(삭제) 버튼."""
    keep = (gr.skip(),) * 3
    if evt.value == "edit":
        return (*keep, *_form(evt.index, store["members"][evt.index]))
    members = _remove(store["members"], evt.index, me)
    if members is None:
        return (*keep, *(gr.skip(),) * 9)
    form = _form() if editing is not None else (gr.skip(),) * 9  # 수정 중이던 칸은 비운다
    store = {**store, "members": members}
    radio = gr.Radio(choices=role_choices(members), value=role)
    return (store, radio, table(members, role, dept), *form)


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
    """등록 또는 수정 내용을 저장한다(목데이터, 비밀번호는 저장하지 않음)."""
    uid, name = (uid or "").strip(), (name or "").strip()
    need = [("아이디", uid), ("이름", name), ("소속 부서", dept)]
    if index is None:
        need.append(("초기 비밀번호", (pw or "").strip()))
    missing = [n for n, v in need if not v]
    if missing:
        ui.warn(f"아직 입력하지 않았어요: {' · '.join(missing)}")
        return (gr.skip(),) * 12
    members = [dict(m) for m in store["members"]]
    if index is None:
        if any(m["id"] == uid for m in members):
            ui.warn("이미 쓰고 있는 아이디예요")
            return (gr.skip(),) * 12
        members.append(
            {
                "name": name,
                "id": uid,
                "dept": dept,
                "role": role,
                "active": True,
                "date": datetime.now().strftime("%m/%d"),
            }
        )
        ui.notify(f"{name} 회원을 등록했어요")
    else:
        members[index].update(name=name, dept=dept, role=role)
        ui.notify(f"{name} 회원 정보를 저장했어요")
    store = {**store, "members": members}
    radio = gr.Radio(choices=role_choices(members), value=f_role)
    return (store, radio, table(members, f_role, f_dept), *_form())


# ------------------------------------------------------------------ 화면
def _member_list() -> dict:
    """왼쪽 회원 목록 카드: 권한 칩 · 부서 거르기 · 표."""
    c = {}
    with gr.Column(elem_classes=["card", "content"]):
        with gr.Row(elem_classes=["toolbar"]):
            c["role"] = ui.chip_radio(role_choices(mock.MEMBERS), scale=0)
            gr.HTML("", padding=False, scale=1)
            c["dept"] = ui.select_box(mock.DEPARTMENTS, "부서 전체", scale=0, min_width=150)
        c["table"] = ui.click_list(table(mock.MEMBERS))
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
        c["dept"] = ui.select_box(mock.DEPARTMENTS, "부서 선택")
        _label("권한")
        c["role"] = ui.chip_radio(ROLES)
        _label("초기 비밀번호")
        c["pw"] = ui.text_input("초기 비밀번호", password=True)
        c["submit"] = gr.Button("등록", elem_classes=["btn-primary", "full"])
        c["cancel"] = gr.Button("취소", elem_classes=["btn-secondary", "full"], visible=False)
        note = "본인 계정과 마지막 남은 관리자는 삭제할 수 없어요."
        gr.HTML(f'<p class="note">{note}</p>', padding=False)
    return c


def build(store: gr.State, user: gr.State) -> PageView:
    """회원 관리 화면을 만든다. user 는 로그인한 관리자(본인 계정 확인용)."""
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
    lst["table"].select(_act, [store, *filters, user, edit_index], list_outs + form_outs)
    f["check"].click(_check_id, [store, f["uid"]], None)
    f["submit"].click(_save, [store, edit_index, *fields, *filters], list_outs + form_outs)
    f["cancel"].click(_form, None, form_outs)

    def reset(data: dict) -> tuple:
        """메뉴로 들어오면 거르기 조건과 등록 칸을 처음으로 돌린다."""
        radio = gr.Radio(choices=role_choices(data["members"]), value="전체")
        return (radio, "", table(data["members"]), *_form())

    return PageView(reset, [store], [*filters, lst["table"], *form_outs])
