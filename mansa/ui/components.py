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


def logo_html(size: int = 40, admin: bool = False, link: bool = False) -> str:
    """메뉴바 맨 위 서비스 심볼. 관리자 메뉴바에서는 흰색으로 그린다.

    link=True 이면 누르면 첫 메뉴로 가는 버튼이 된다(click_list 와 함께 쓴다).
    """
    art = icons.logo(size, "#FFFFFF", "rgba(255,255,255,0.5)") if admin else icons.logo(size)
    if link:
        attrs = 'data-i="0" role="button" tabindex="0" aria-label="첫 화면으로"'
        return f'<div class="logo link" {attrs}>{art}</div>'
    return f'<div class="logo">{art}</div>'


def ai_avatar() -> str:
    """AI 답변 옆에 붙는 서비스 심볼 프로필."""
    return f'<div class="ai-avatar">{icons.logo(24)}</div>'


def typing_html(text: str, avatar: str = "") -> str:
    """'답을 찾는 중' 말풍선: 점 세 개가 깜빡이고 무슨 일을 하는지 한 줄로 알려 준다."""
    dots = '<span class="dots"><i></i><i></i><i></i></span>'
    return (
        f'<div class="bot-row typing-row" role="status">{avatar or ai_avatar()}'
        f'<div class="typing">{dots}<span>{escape(text)}</span></div></div>'
    )


def loading_button(label: str, classes: list[str]) -> gr.Button:
    """처리 중인 버튼: 글자가 바뀌고 빙글빙글 돌며 누를 수 없다."""
    return gr.Button(value=label, interactive=False, elem_classes=[*classes, "loading"])


def idle_button(label: str, classes: list[str]) -> gr.Button:
    """처리가 끝난 버튼을 원래 모습으로 돌린다."""
    return gr.Button(value=label, interactive=True, elem_classes=classes)


def user_bubble(text: str) -> str:
    """오른쪽에 붙는 사용자 질문 말풍선."""
    return f'<div class="user-msg"><div class="bubble">{escape(text)}</div></div>'


def icon(name: str, color: str = TEXT2, size: int = 20) -> str:
    """HTML 안에 넣는 선 아이콘."""
    return icons.svg(name, color, size)


# 목록 HTML 안에서 data-i 가 붙은 줄(버튼)을 누르면 .select 이벤트로 번호를 보낸다.
# data-v 가 있으면 value 로 함께 보낸다 (예: "edit", "toggle" 처럼 어떤 버튼인지 구분).
CLICK_JS = """const pick = (e) => {
  const row = e.target.closest('[data-i]');
  if (row) trigger('select', {index: Number(row.dataset.i), value: row.dataset.v || ''});
};
element.addEventListener('click', pick);
element.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[role=button]')) {
    e.preventDefault();
    pick(e);
  }
});"""


# 내용이 바뀌면 둘러싼 .chat-scroll 을 맨 아래로 내린다 (새 메시지가 보이게).
SCROLL_JS = """const toBottom = () => setTimeout(() => {
  const box = element.closest('.chat-scroll');
  if (box) box.scrollTop = box.scrollHeight;
}, 60);
watch('value', toBottom);
toBottom();"""


def click_list(value: str = "", scroll_bottom: bool = False, **kwargs) -> gr.HTML:
    """줄을 누를 수 있는 목록 HTML.

    누른 줄 번호는 gr.SelectData.index, 버튼 종류(data-v)는 gr.SelectData.value 로 받는다.
    scroll_bottom=True 이면 내용이 바뀔 때 대화 영역을 맨 아래로 내린다.
    """
    js = CLICK_JS + ("\n" + SCROLL_JS if scroll_bottom else "")
    return gr.HTML(value, js_on_load=js, padding=False, **kwargs)


def chat_html(value: str = "", **kwargs) -> gr.HTML:
    """대화 내용 HTML. 내용이 바뀌면 대화 영역을 맨 아래로 내린다."""
    return gr.HTML(value, js_on_load=SCROLL_JS, padding=False, **kwargs)


def chip_radio(choices: list, value=None, empty: bool = False, **kwargs) -> gr.Radio:
    """알약 모양 버튼으로 보이는 하나 고르기. value 가 없으면 첫 항목을 고른다.

    empty=True 이면 아무것도 고르지 않은 채로 시작한다(되묻기 카드처럼 직접 골라야 할 때).
    """
    first = choices[0][1] if isinstance(choices[0], tuple) else choices[0]
    if value is None and not empty:
        value = first
    return gr.Radio(
        choices,
        value=value,
        show_label=False,
        container=False,
        elem_classes=["chip-radio"],
        **kwargs,
    )


def enable_when_filled(text: gr.Textbox, button: gr.Button) -> None:
    """글자가 들어 있을 때만 버튼을 켠다 (비어 있으면 회색으로 눌리지 않는다)."""
    text.change(
        lambda t: gr.Button(interactive=bool((t or "").strip())),
        text,
        button,
        show_progress="hidden",
        queue=False,
    )


def enable_when_chosen(radios: list[gr.Radio], button: gr.Button) -> None:
    """모두 골랐을 때만 버튼을 켠다."""
    for radio in radios:
        radio.change(
            lambda *values: gr.Button(interactive=all(values)),
            radios,
            button,
            show_progress="hidden",
            queue=False,
        )


def select_box(
    choices: list[str],
    placeholder: str,
    value: str = "",
    classes: list[str] | None = None,
    **kwargs,
) -> gr.Dropdown:
    """흰 드롭다운. 아무것도 고르지 않은 값("")은 placeholder 문구로 흐리게 보인다.

    classes 로 너비 등 class 를 더한다.
    """
    base = ["select", *(classes or [])]
    box = gr.Dropdown(
        [(placeholder, "")] + [(c, c) for c in choices],
        value=value,
        show_label=False,
        container=False,
        elem_classes=base + (["filled"] if value else []),
        **kwargs,
    )
    box.change(lambda v: gr.Dropdown(elem_classes=base + (["filled"] if v else [])), box, box)
    return box


def search_box(placeholder: str, classes: list[str] | None = None, **kwargs) -> gr.Textbox:
    """돋보기 아이콘이 붙은 검색 입력칸. classes 로 너비 등 class 를 더한다."""
    return gr.Textbox(
        placeholder=placeholder,
        show_label=False,
        container=False,
        max_lines=1,
        elem_classes=["search", *(classes or [])],
        **kwargs,
    )


def table_html(columns: list[tuple[str, str]], rows: list[list[str]], empty: str = "") -> str:
    """표 HTML. columns 는 (제목, 너비) 목록, rows 는 이미 escape 된 칸 HTML 목록이다.

    줄에 칸이 하나 더 있으면 그 값은 줄 class 로 붙는다 (예: 흐리게 보일 줄 "off").

    너비는 CSS grid 값(예: "1fr", "120px")이다. 행이 없으면 empty 문구를 보여 준다.
    """
    grid = " ".join(width for _, width in columns)
    head = "".join(f"<span>{escape(name)}</span>" for name, _ in columns)
    body = "".join(_tr(grid, cells, len(columns)) for cells in rows)
    if not rows and empty:
        body = f'<div class="empty">{escape(empty)}</div>'
    header = f'<div class="th" style="grid-template-columns:{grid}">{head}</div>'
    return f'<div class="tbl">{header}{body}</div>'


def _tr(grid: str, cells: list[str], count: int) -> str:
    """표 한 줄. 칸 수보다 하나 더 있으면 마지막 값은 줄 class 다 (예: 흐리게 보일 줄 "off")."""
    extra = f" {cells[count]}" if len(cells) > count else ""
    body = "".join(cells[:count])
    return f'<div class="tr{extra}" style="grid-template-columns:{grid}">{body}</div>'


def cell(html: str) -> str:
    """표 칸 하나. html 은 이미 escape 된 값이어야 한다."""
    return f"<span>{html}</span>"


def pdf_badge() -> str:
    """문서 이름 앞에 붙는 PDF 표시."""
    return '<span class="pdf">PDF</span>'


DEPT_TAG = {"유지보수팀": "blue", "안전팀": "orange", "검사·품질팀": "teal"}
TYPE_TAG = {"기술 문서": "blue", "안전 문서": "orange"}
STATUS_TAG = {"완료": "green", "처리 중": "blue", "실패": "red"}


def dept_tag(dept: str) -> str:
    """부서 태그 (부서마다 색이 정해져 있고, 새 부서는 회색)."""
    return tag(dept, DEPT_TAG.get(dept, "gray"))


def notify(message: str) -> None:
    """오른쪽 위 안내 알림 (몇 초 뒤 사라짐)."""
    gr.Info(message, title="안내", duration=4)


def warn(message: str) -> None:
    """오른쪽 위 확인 요청 알림 (입력이 빠졌거나 할 수 없는 동작일 때)."""
    gr.Warning(message, title="확인해 주세요", duration=5)


def text_input(placeholder: str, password: bool = False, **kwargs) -> gr.Textbox:
    """제목 없이 안내 문구만 있는 한 줄 입력칸."""
    return gr.Textbox(
        placeholder=placeholder,
        type="password" if password else "text",
        show_label=False,
        container=False,
        max_lines=1,
        elem_classes=["field"],
        **kwargs,
    )


def small_button(label: str, primary: bool = False, **kwargs) -> gr.Button:
    """글자 길이만큼만 넓은 작은 버튼 (파란 버튼 또는 흰 버튼)."""
    kind = "btn-primary" if primary else "btn-secondary"
    return gr.Button(label, elem_classes=[kind, "sm-btn"], scale=0, min_width=0, **kwargs)
