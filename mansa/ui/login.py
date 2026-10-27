"""로그인 화면: 기본은 사용자 로그인, 버튼으로 관리자 로그인(파란 바탕·좌우 반전)으로 바꾼다.

두 카드와 두 소개를 한 화면에 겹쳐 두고, 바꾸기 버튼은 서버를 거치지 않고(JS)
#login 에 admin 클래스만 붙였다 뗀다. 움직임과 색 변화는 assets/login.css 가 맡는다.
"""

from dataclasses import dataclass
from html import escape

import gradio as gr

from ui import icons
from ui.theme import BRAND

INTRO = {
    "user": {
        "pill": ("user", "사용자 로그인"),
        "headline": "매뉴얼을 물으면<br>안전이 따라옵니다",
        "features": [
            ("chat", "매뉴얼·사양 질문에 출처와 함께 답해요"),
            ("shield", "작업에 맞는 안전 요건을 함께 보여 줘요"),
            ("headset", "사용법과 등록 모델은 고객센터에서 안내해요"),
        ],
    },
    "admin": {
        "pill": ("shield", "관리자 로그인"),
        "headline": "문서와 기준정보를<br>한 곳에서 관리해요",
        "features": [
            ("folder", "문서 업로드와 처리 상태를 한눈에 확인해요"),
            ("database", "모델·부품 기준정보를 관리해요"),
            ("chart", "질문 테스트와 성능 평가를 실행해요"),
        ],
    },
}

CARD = {
    "user": (
        "로그인",
        "사번과 비밀번호를 입력하세요",
        "아이디",
        "사번 또는 아이디",
        "로그인",
        "관리자 계정으로 로그인",
        "계정이 없으면 관리자에게 문의하세요",
    ),
    "admin": (
        "관리자 로그인",
        "관리자 권한이 있는 계정만 들어갈 수 있어요",
        "관리자 아이디",
        "관리자 아이디",
        "관리자 로그인",
        "사용자 로그인으로 돌아가기",
        "관리자 계정은 미리 등록된 계정만 쓸 수 있어요",
    ),
}


# 바꾸기 버튼: 관리자 모드로 가면 True, 사용자 모드로 돌아오면 False
SWITCH_JS = "() => {{ document.getElementById('login')?.classList.toggle('admin', {admin}); }}"
RESET_JS = SWITCH_JS.format(admin="false")


@dataclass
class LoginForm:
    """로그인 카드 하나(사용자 또는 관리자)의 입력·버튼."""

    user_id: gr.Textbox
    password: gr.Textbox
    error: gr.HTML
    submit: gr.Button
    switch: gr.Button


def intro_html(role: str) -> str:
    """로그인 화면 왼쪽(관리자는 오른쪽) 소개 영역을 만든다."""
    data = INTRO[role]
    admin = role == "admin"
    tone = "#FFFFFF" if admin else BRAND
    pill_icon, pill_text = data["pill"]
    logo = icons.logo(40, "#FFFFFF", "rgba(255,255,255,0.5)") if admin else icons.logo(40)
    features = "".join(
        f'<div class="feature"><span class="tile">{icons.svg(name, tone, 20)}</span>'
        f"{escape(text)}</div>"
        for name, text in data["features"]
    )
    return (
        f'<div class="login-intro {role}">'
        f'<span class="mode-pill">{icons.svg(pill_icon, tone, 16)}{escape(pill_text)}</span>'
        f'<div class="lockup">{logo}MANSA</div>'
        f"<h1>{data['headline']}</h1>"
        '<div class="intro-gap"></div>'  # Figma: 설명 문구 자리는 비워 두고 간격만 남김
        f'<div class="features">{features}</div>'
        "</div>"
    )


def _card(role: str) -> LoginForm:
    """로그인 카드(입력칸·버튼)를 만든다. 호출한 위치(카드 자리 Column 안)에 그려진다."""
    title, sub, id_label, id_hint, submit, switch, help_text = CARD[role]
    with gr.Column(elem_classes=["login-card", f"{role}-card"]):
        gr.HTML(f'<h2>{escape(title)}</h2><p class="sub">{escape(sub)}</p>', padding=False)
        with gr.Column(elem_classes=["fields"]):
            user_id = gr.Textbox(
                label=id_label, placeholder=id_hint, elem_classes=["field"], max_lines=1
            )
            password = gr.Textbox(
                label="비밀번호",
                placeholder="비밀번호를 입력하세요",
                type="password",
                elem_classes=["field"],
                max_lines=1,
            )
        error = gr.HTML(visible=False, padding=False)
        submit_btn = gr.Button(submit, elem_classes=["btn-primary"])
        gr.HTML('<div class="or-divider">또는</div>', padding=False)
        switch_btn = gr.Button(switch, elem_classes=["btn-secondary"])
        gr.HTML(f'<p class="help">{escape(help_text)}</p>', padding=False)
    return LoginForm(user_id, password, error, submit_btn, switch_btn)


def build() -> tuple[gr.Column, LoginForm, LoginForm]:
    """로그인 화면(사용자·관리자 카드 겹침)을 만들고 서로 바꾸는 버튼을 연결한다.

    로그인 성공 처리는 화면 전환이 필요해 app.py 에서 연결한다.
    """
    with gr.Column(elem_classes=["login"], elem_id="login") as view:
        with gr.Row(elem_classes=["login-row"]):
            stack = f'<div class="intro-stack">{intro_html("user")}{intro_html("admin")}</div>'
            gr.HTML(stack, padding=False, elem_classes=["intro-stage"])
            with gr.Column(elem_classes=["card-stage"]):
                user_form = _card("user")
                admin_form = _card("admin")
    user_form.switch.click(None, js=SWITCH_JS.format(admin="true"))
    admin_form.switch.click(None, js=SWITCH_JS.format(admin="false"))
    return view, user_form, admin_form


def error_html(message: str) -> str:
    """로그인 실패 안내 상자를 만든다."""
    return f'<div class="error">{icons.svg("alert", "#B91C1C", 18)}{escape(message)}</div>'
