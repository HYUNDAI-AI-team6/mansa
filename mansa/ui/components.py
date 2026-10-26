"""여러 화면에서 함께 쓰는 HTML 조각.

모든 글자는 html.escape 로 감싸서 넣는다.
목데이터나 기능 결과에 섞인 태그가 그대로 실행되지 않게 하기 위해서다.
"""

from html import escape

import gradio as gr

from ui import icons
from ui.theme import BRAND, TEXT2


def tag(label: str, color: str = "gray") -> str:
    """색 태그 하나를 만든다. color 는 theme.TAG_COLORS 의 키."""
    return f'<span class="tag {color}">{escape(label)}</span>'


def section_title(title: str, caption: str = "") -> str:
    """'질문하기 · 설명' 형태의 구역 제목을 만든다."""
    cap = f"<span>{escape(caption)}</span>" if caption else ""
    return f'<div class="section-title"><h3>{escape(title)}</h3>{cap}</div>'


def page_header(title: str, description: str | None, user: dict | None) -> str:
    """화면 맨 위 머리글(제목·설명·계정 표시)을 만든다."""
    desc = f"<p>{escape(description)}</p>" if description else ""
    account = ""
    if user:
        who = f"{user['name']} · {user['dept']}"
        account = (
            f'<div class="meta"><div class="account"><span class="dot"></span>{escape(who)}</div>'
            f'<div class="avatar">{icons.svg("user", BRAND, 24)}</div></div>'
        )
    return f'<div class="page-header"><div><h1>{escape(title)}</h1>{desc}</div>{account}</div>'


def logo_html(size: int = 40, admin: bool = False) -> str:
    """메뉴바 맨 위 서비스 심볼. 관리자 메뉴바에서는 흰색으로 그린다."""
    art = icons.logo(size, "#FFFFFF", "rgba(255,255,255,0.5)") if admin else icons.logo(size)
    return f'<div class="logo">{art}</div>'


def ai_avatar() -> str:
    """AI 답변 옆에 붙는 서비스 심볼 프로필."""
    return f'<div class="ai-avatar">{icons.logo(24)}</div>'


def user_bubble(text: str) -> str:
    """오른쪽에 붙는 사용자 질문 말풍선."""
    return f'<div class="user-msg"><div class="bubble">{escape(text)}</div></div>'


def icon(name: str, color: str = TEXT2, size: int = 20) -> str:
    """HTML 안에 넣는 선 아이콘."""
    return icons.svg(name, color, size)


# 목록 HTML 안에서 data-i 가 붙은 줄을 누르면 .select 이벤트로 그 번호를 보낸다.
CLICK_JS = """element.addEventListener('click', (e) => {
  const row = e.target.closest('[data-i]');
  if (row) trigger('select', {index: Number(row.dataset.i), value: row.dataset.i});
});"""


def click_list(value: str = "", **kwargs) -> gr.HTML:
    """줄을 누를 수 있는 목록 HTML. 누른 줄 번호는 .select 의 gr.SelectData.index 로 받는다."""
    return gr.HTML(value, js_on_load=CLICK_JS, padding=False, **kwargs)
