"""MANSA 실행 파일: 로그인 화면 → 권한별(사용자/관리자) 메뉴바 + 화면."""

from dataclasses import dataclass

import gradio as gr

from ui import components as ui
from ui import (
    doc_view,
    documents,
    evaluation,
    history,
    login,
    master,
    members,
    navigation,
    qa,
    support,
    theme,
    upload,
)
from ui import mock_data as mock
from ui.navigation import HOME, PAGE_BY_KEY, PAGES

FONT_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@700&display=swap" '
    'rel="stylesheet">'
)


@dataclass
class Shell:
    """로그인 뒤 보이는 앱 틀: 메뉴바 2개(사용자/관리자), 머리글, 화면들."""

    view: gr.Row
    sides: dict[str, gr.Column]
    navs: dict[str, gr.Button]
    logos: dict[str, gr.HTML]  # 권한 -> 눌러서 첫 메뉴로 가는 로고
    logouts: list[gr.Button]
    header: gr.HTML
    pages: dict[str, gr.Column]
    resettable: dict  # key -> PageView / QAView (메뉴로 들어올 때 다시 그릴 화면)

    def nav_outputs(self) -> list:
        """메뉴를 바꿀 때 다시 그리는 부분: 머리글, 화면들, 메뉴 버튼들."""
        return [self.header, *self.pages.values(), *self.navs.values()]


def _build_page(key: str, store: gr.State, user: gr.State):
    """메뉴 key 에 맞는 화면 파일의 build() 를 부른다.

    메뉴로 다시 들어올 때 다시 그릴 화면이면 그 정보(PageView/QAView)를 돌려준다.
    store 는 로그인 세션의 목데이터(문서·부서·회원), user 는 로그인한 계정이다.
    """
    builders = {
        "qa": lambda: qa.build(),
        "history": lambda: history.build(),
        "doc_view": lambda: doc_view.build(store),
        "support": lambda: support.build(),
        "documents": lambda: documents.build(store),
        "upload": lambda: upload.build(store),
        "master": lambda: master.build(store),
        "evaluation": lambda: evaluation.build(),
        "question_test": lambda: qa.build(test_mode=True),
        "members": lambda: members.build(store, user),
    }
    return builders[key]()


def _build_sidebar(role: str) -> tuple[gr.Column, gr.HTML, dict, gr.Button]:
    """권한별 왼쪽 메뉴바(사용자: 흰색, 관리자: 파란색)를 만든다."""
    admin = role == "admin"
    classes = ["sidebar", "admin"] if admin else ["sidebar"]
    with gr.Column(elem_classes=classes, visible=False, scale=0, min_width=96) as column:
        logo = ui.click_list(ui.logo_html(40, admin, link=True), elem_classes=["logo-block"])
        buttons = {
            p.key: gr.Button(p.label, elem_classes=["nav-btn", f"ic-{p.icon}"])
            for p in navigation.pages_for(role)
        }
        gr.HTML("", padding=False, elem_classes=["grow"])
        logout = gr.Button("로그아웃", elem_classes=["nav-btn", "ic-logout"])
    return column, logo, buttons, logout


def _build_shell(store: gr.State, user: gr.State) -> Shell:
    """메뉴바와 모든 화면을 만든다. 처음에는 숨겨 두고 로그인하면 보인다."""
    with gr.Row(elem_id="shell", visible=False) as view:
        side_user, logo_user, nav_user, logout_user = _build_sidebar("user")
        side_admin, logo_admin, nav_admin, logout_admin = _build_sidebar("admin")
        with gr.Column(elem_id="main"):
            header = gr.HTML(padding=False, elem_classes=["header-block"])
            pages, resettable = {}, {}
            for page in PAGES:
                with gr.Column(visible=False, elem_classes=["page"]) as pages[page.key]:
                    built = _build_page(page.key, store, user)
                if built is not None:
                    resettable[page.key] = built
    sides = {"user": side_user, "admin": side_admin}
    navs = {**nav_user, **nav_admin}
    logos = {"user": logo_user, "admin": logo_admin}
    return Shell(view, sides, navs, logos, [logout_user, logout_admin], header, pages, resettable)


def _nav_classes(key: str, active: bool) -> list[str]:
    """메뉴 버튼 class 목록(아이콘 + 선택 여부)."""
    classes = ["nav-btn", f"ic-{PAGE_BY_KEY[key].icon}"]
    return classes + ["active"] if active else classes


def _show(key: str, user: dict | None, nav_keys: list[str]) -> tuple:
    """메뉴 하나를 보여 준다: 머리글, 화면 보이기/숨기기, 선택한 메뉴 강조."""
    page = PAGE_BY_KEY[key]
    header = ui.page_header(page.label, page.description, user)
    pages = [gr.Column(visible=p.key == key) for p in PAGES]
    navs = [gr.Button(elem_classes=_nav_classes(k, k == key)) for k in nav_keys]
    return (header, *pages, *navs)


def _then_reset(event, view) -> None:
    """화면을 바꾼 다음 그 화면을 처음 상태로 다시 그린다."""
    if view is not None:
        event.then(view.reset, view.reset_inputs or None, view.reset_outputs)


def _wire_nav(shell: Shell, user: gr.State) -> None:
    """메뉴 버튼을 누르면 그 화면으로 바꾸고, 필요하면 화면을 처음 상태로 되돌린다."""
    nav_keys = list(shell.navs)
    for key, button in shell.navs.items():
        event = button.click(lambda u, k=key: _show(k, u, nav_keys), user, shell.nav_outputs())
        _then_reset(event, shell.resettable.get(key))
    for role, logo in shell.logos.items():  # 로고를 누르면 그 권한의 첫 메뉴로
        home = HOME[role]
        event = logo.select(lambda u, k=home: _show(k, u, nav_keys), user, shell.nav_outputs())
        _then_reset(event, shell.resettable.get(home))


def _wire_links(shell: Shell, user: gr.State) -> None:
    """화면 안에서 다른 화면으로 가는 버튼을 연결한다.

    문서 관리의 '문서 업로드' → 문서 업로드, 질문 기록의 대화 → 기술 Q&A 에서 그 대화 열기.
    """
    nav_keys = list(shell.navs)
    upload_btn = shell.resettable["documents"].links["upload"]
    event = upload_btn.click(lambda u: _show("upload", u, nav_keys), user, shell.nav_outputs())
    _then_reset(event, shell.resettable["upload"])

    picked = gr.State(0)
    qa_view = shell.resettable["qa"]

    def open_chat(u: dict, evt: gr.SelectData) -> tuple:
        """질문 기록에서 고른 대화 번호를 기억하고 기술 Q&A 화면으로 간다."""
        return (*_show("qa", u, nav_keys), evt.index)

    rows = shell.resettable["history"].links["open"]
    event = rows.select(open_chat, user, [*shell.nav_outputs(), picked])
    event.then(qa_view.open_history, picked, qa_view.reset_outputs)


def _layout(role: str | None) -> tuple:
    """로그인 상태에 맞는 큰 틀 보이기/숨기기 값.

    순서: 로그인 화면, 앱 틀, 사용자 메뉴바, 관리자 메뉴바.
    role 이 None 이면 로그아웃 상태(로그인 화면)다.
    """
    return (
        gr.Column(visible=role is None),
        gr.Row(visible=role is not None),
        gr.Column(visible=role == "user"),
        gr.Column(visible=role == "admin"),
    )


def _wire_login(
    role: str, form: login.LoginForm, shell: Shell, user: gr.State, layout_outputs: list
) -> None:
    """로그인 버튼·Enter 를 연결한다. 성공하면 권한별 첫 화면으로 간다."""
    nav_keys = list(shell.navs)
    outputs = [form.error, user, *layout_outputs, *shell.nav_outputs()]

    def handle(user_id: str, password: str) -> tuple:
        """목데이터로 로그인하고 화면을 바꾼다. 실패하면 안내 상자만 보여 준다."""
        account, message = mock.mock_login(user_id, password, role)
        if account is None:
            skips = [gr.skip()] * (len(outputs) - 1)
            return (gr.HTML(login.error_html(message), visible=True), *skips)
        shown = _show(HOME[role], account, nav_keys)
        return (gr.HTML(visible=False), account, *_layout(role), *shown)

    home = shell.resettable.get(HOME[role])
    for trigger in (form.submit.click, form.password.submit):
        _then_reset(trigger(handle, [form.user_id, form.password], outputs), home)


def _wire_logout(
    shell: Shell,
    states: list[gr.State],
    layout_outputs: list,
    forms: list[login.LoginForm],
) -> None:
    """로그아웃: 사용자 로그인 모드로 되돌리고, 입력했던 아이디·비밀번호와 목데이터를 지운다.

    states 는 [로그인 계정, 세션 목데이터] 순서다.
    """
    fields = [box for form in forms for box in (form.user_id, form.password)]

    def logout() -> tuple:
        """로그인 화면을 다시 보여 주는 값."""
        return (None, mock.new_store(), *_layout(None), *[""] * len(fields))

    for button in shell.logouts:
        event = button.click(None, js=login.RESET_JS)
        event.then(logout, None, [*states, *layout_outputs, *fields])


def main():
    """화면을 만들고 이벤트를 연결한 뒤 앱을 실행한다."""
    with gr.Blocks(title="MANSA", fill_width=True) as demo:
        user = gr.State(None)
        store = gr.State(mock.new_store())
        login_view, user_form, admin_form = login.build()
        shell = _build_shell(store, user)
        layout_outputs = [login_view, shell.view, *shell.sides.values()]

        _wire_nav(shell, user)
        _wire_links(shell, user)
        _wire_login("user", user_form, shell, user, layout_outputs)
        _wire_login("admin", admin_form, shell, user, layout_outputs)
        _wire_logout(shell, [user, store], layout_outputs, [user_form, admin_form])

    demo.launch(theme=theme.build_theme(), css=theme.build_css(), head=FONT_HEAD)


if __name__ == "__main__":
    main()
