"""MANSA 실행 파일: 로그인 화면 → 권한별(사용자/관리자) 메뉴바 + 화면."""

from dataclasses import dataclass

import gradio as gr

from ui import components as ui
from ui import login, navigation, qa, theme
from ui import mock_data as mock
from ui.navigation import HOME, PAGE_BY_KEY, PAGES, Page

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
    logouts: list[gr.Button]
    header: gr.HTML
    pages: dict[str, gr.Column]
    resettable: dict[str, qa.QAView]

    def nav_outputs(self) -> list:
        """메뉴를 바꿀 때 다시 그리는 부분: 머리글, 화면들, 메뉴 버튼들."""
        return [self.header, *self.pages.values(), *self.navs.values()]


def _pending(page: Page) -> None:
    """아직 붙이지 않은 화면 자리. 다음 단계에서 화면 파일로 바꾼다."""
    gr.HTML(
        f'<div class="card"><h3>{page.label}</h3><p>이 화면은 다음 단계에서 붙여요.</p></div>',
        padding=False,
    )


def _build_page(page: Page) -> qa.QAView | None:
    """메뉴 key 에 맞는 화면 파일의 build() 를 부른다.

    메뉴로 다시 들어올 때 처음 상태로 되돌릴 화면이면 그 객체를 돌려준다.
    """
    if page.key == "qa":
        return qa.build()
    if page.key == "question_test":
        return qa.build(test_mode=True)
    _pending(page)
    return None


def _build_sidebar(role: str) -> tuple[gr.Column, dict, gr.Button]:
    """권한별 왼쪽 메뉴바(사용자: 흰색, 관리자: 파란색)를 만든다."""
    admin = role == "admin"
    classes = ["sidebar", "admin"] if admin else ["sidebar"]
    with gr.Column(elem_classes=classes, visible=False, scale=0, min_width=96) as column:
        gr.HTML(ui.logo_html(40, admin), padding=False, elem_classes=["logo-block"])
        buttons = {
            p.key: gr.Button(p.label, elem_classes=["nav-btn", f"ic-{p.icon}"])
            for p in navigation.pages_for(role)
        }
        gr.HTML("", padding=False, elem_classes=["grow"])
        logout = gr.Button("로그아웃", elem_classes=["nav-btn", "ic-logout"])
    return column, buttons, logout


def _build_shell() -> Shell:
    """메뉴바와 모든 화면을 만든다. 처음에는 숨겨 두고 로그인하면 보인다."""
    with gr.Row(elem_id="shell", visible=False) as view:
        side_user, nav_user, logout_user = _build_sidebar("user")
        side_admin, nav_admin, logout_admin = _build_sidebar("admin")
        with gr.Column(elem_id="main"):
            header = gr.HTML(padding=False)
            pages, resettable = {}, {}
            for page in PAGES:
                with gr.Column(visible=False, elem_classes=["page"]) as pages[page.key]:
                    built = _build_page(page)
                if built is not None:
                    resettable[page.key] = built
    sides = {"user": side_user, "admin": side_admin}
    navs = {**nav_user, **nav_admin}
    return Shell(view, sides, navs, [logout_user, logout_admin], header, pages, resettable)


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


def _wire_nav(shell: Shell, user: gr.State) -> None:
    """메뉴 버튼을 누르면 그 화면으로 바꾸고, 필요하면 화면을 처음 상태로 되돌린다."""
    nav_keys = list(shell.navs)
    for key, button in shell.navs.items():
        event = button.click(lambda u, k=key: _show(k, u, nav_keys), user, shell.nav_outputs())
        if key in shell.resettable:
            view = shell.resettable[key]
            event.then(view.reset, None, view.reset_outputs)


def _layout(role: str | None) -> tuple:
    """로그인 상태에 맞는 큰 틀 보이기/숨기기 값.

    순서: 사용자 로그인, 관리자 로그인, 앱 틀, 사용자 메뉴바, 관리자 메뉴바.
    role 이 None 이면 로그아웃 상태(사용자 로그인 화면)다.
    """
    return (
        gr.Column(visible=role is None),
        gr.Column(visible=False),
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
        event = trigger(handle, [form.user_id, form.password], outputs)
        if home is not None:
            event.then(home.reset, None, home.reset_outputs)


def main():
    """화면을 만들고 이벤트를 연결한 뒤 앱을 실행한다."""
    with gr.Blocks(title="MANSA", fill_width=True) as demo:
        user = gr.State(None)
        user_form, admin_form = login.build()
        shell = _build_shell()
        layout_outputs = [user_form.view, admin_form.view, shell.view, *shell.sides.values()]

        _wire_nav(shell, user)
        _wire_login("user", user_form, shell, user, layout_outputs)
        _wire_login("admin", admin_form, shell, user, layout_outputs)
        for button in shell.logouts:
            button.click(lambda: (None, *_layout(None)), None, [user, *layout_outputs])

    demo.launch(theme=theme.build_theme(), css=theme.build_css(), head=FONT_HEAD)


if __name__ == "__main__":
    main()
