"""고객센터(U4): MANSA 사용법 안내 챗봇 + 관리자 연결(U4-2, 목데이터 화면만).

관리자 연결은 실제로 연결되지 않는다. 버튼을 누르면 관리자가 들어온 것처럼 보여 준다.
"""

from datetime import datetime
from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock

PLACEHOLDER = {False: "사용법을 물어보세요", True: "관리자에게 메시지를 보내세요"}


def _new_state() -> dict:
    """새 대화: 인사말 하나로 시작한다."""
    return {
        "msgs": [{"who": "bot", "text": mock.SUPPORT_GREETING, "chips": True}],
        "connected": False,
        "admin_replied": False,
    }


# ------------------------------------------------------------------ HTML
def _bot(body: str) -> str:
    """왼쪽 챗봇 말풍선 (서비스 심볼 프로필)."""
    return f'<div class="bot-row">{ui.ai_avatar()}<div class="bot-col">{body}</div></div>'


def _message(msg: dict) -> str:
    """메시지 하나를 종류(챗봇·사용자·안내·관리자)에 맞게 그린다."""
    who = msg["who"]
    if who == "user":
        return ui.user_bubble(msg["text"])
    if who == "system":
        return f'<div class="sys-line"><span>{escape(msg["text"])}</span></div>'
    if who == "admin":
        return (
            '<div class="bot-row"><div class="admin-avatar">관</div>'
            f'<div class="bot-col"><span class="who">{escape(mock.ADMIN_NAME)} · 관리자</span>'
            f'<div class="s-bubble">{escape(msg["text"])}</div></div></div>'
        )
    if "steps" in msg:
        body = "".join(f"<li>{escape(s)}</li>" for s in msg["steps"])
        return _bot(f'<div class="s-bubble"><ol>{body}</ol></div>')
    chips = ""
    if msg.get("chips"):
        chips = "".join(
            f'<button type="button" class="s-chip" data-i="{i}">{escape(c)}</button>'
            for i, c in enumerate(mock.SUPPORT_CHIPS)
        )
        chips = f'<div class="s-chips">{chips}</div>'
    return _bot(f'<div class="s-bubble">{escape(msg["text"])}</div>{chips}')


def messages_html(state: dict) -> str:
    """대화 전체."""
    return f'<div class="s-msgs">{"".join(_message(m) for m in state["msgs"])}</div>'


def status_html(connected: bool) -> str:
    """왼쪽 위 상태 태그."""
    if connected:
        return ui.tag(f"관리자와 연결됐어요 · {mock.ADMIN_NAME}", "green")
    return ui.tag("고객센터 대화는 기술 Q&A와 따로 저장돼요")


def faq_html() -> str:
    """오른쪽 '자주 묻는 질문' 카드. 누르면 그 질문을 보낸다."""
    rows = "".join(
        f'<button type="button" class="list-row click" data-i="{i}"><b>{escape(label)}</b></button>'
        for i, (label, _) in enumerate(mock.SUPPORT_FAQ)
    )
    head = '<div class="card-head"><h3>자주 묻는 질문</h3></div>'
    return f'<div class="card list-card faq">{head}{rows}</div>'


# ------------------------------------------------------------------ 동작
def _now() -> str:
    """안내 문구에 붙는 지금 시각 (HH:MM)."""
    return datetime.now().strftime("%H:%M")


def _render(state: dict) -> tuple:
    """상태에 맞게 화면을 다시 그린다. 순서는 build() 의 outs 와 같다."""
    on = state["connected"]
    return (
        state,
        messages_html(state),
        status_html(on),
        gr.Button(visible=not on),
        gr.Button(visible=not on),
        gr.Button(visible=on),
        gr.Textbox(value="", placeholder=PLACEHOLDER[on]),
    )


def _send(text: str, state: dict) -> tuple:
    """질문을 보낸다. 관리자와 연결 중이면 관리자에게, 아니면 챗봇이 답한다(목데이터)."""
    text = (text or "").strip()
    if not text:
        return tuple(gr.skip() for _ in range(7))
    state = {**state, "msgs": [*state["msgs"], {"who": "user", "text": text}]}
    if state["connected"]:
        if not state["admin_replied"]:
            state["msgs"].append({"who": "admin", "text": "확인해 볼게요. 잠시만 기다려 주세요."})
            state["admin_replied"] = True
    else:
        state["msgs"].append({"who": "bot", **mock.mock_support(text)})
    return _render(state)


def _connect(state: dict) -> tuple:
    """관리자 연결(목데이터): 관리자가 대화에 들어온 것처럼 보여 준다."""
    msgs = [
        *state["msgs"],
        {"who": "bot", "text": "가이드에서 답을 찾지 못했어요. 관리자에게 연결해 드릴게요."},
        {"who": "system", "text": f"{mock.ADMIN_NAME} 관리자가 대화에 들어왔어요 · {_now()}"},
        {"who": "admin", "text": f"안녕하세요, {mock.ADMIN_NAME}입니다. 무엇을 도와드릴까요?"},
    ]
    return _render({"msgs": msgs, "connected": True, "admin_replied": False})


def _end(state: dict) -> tuple:
    """연결 종료: 다시 챗봇이 답한다."""
    msgs = [*state["msgs"], {"who": "system", "text": f"관리자와 연결이 끝났어요 · {_now()}"}]
    return _render({**state, "msgs": msgs, "connected": False})


def _pick_chip(state: dict, evt: gr.SelectData) -> tuple:
    """인사말 아래 예시 질문 칩을 누르면 그 질문을 보낸다."""
    return _send(mock.SUPPORT_CHIPS[evt.index], state)


def _pick_faq(state: dict, evt: gr.SelectData) -> tuple:
    """오른쪽 자주 묻는 질문을 누르면 그 질문을 보낸다."""
    return _send(mock.SUPPORT_FAQ[evt.index][1], state)


# ------------------------------------------------------------------ 화면
def build() -> None:
    """고객센터 화면을 만들고 이벤트를 연결한다."""
    state = gr.State(_new_state())
    with gr.Row(elem_classes=["body-row", "chat-layout"]):
        with gr.Column(elem_classes=["content", "support-main"]):
            with gr.Row(elem_classes=["toolbar"]):
                status = gr.HTML(status_html(False), padding=False, scale=1)
                connect = gr.Button(
                    "관리자 연결", elem_classes=["soft-btn", "sm-btn"], scale=0, min_width=0
                )
                new = gr.Button(
                    "새 대화", elem_classes=["btn-secondary", "sm-btn"], scale=0, min_width=0
                )
                end = gr.Button(
                    "연결 종료",
                    elem_classes=["btn-secondary", "sm-btn"],
                    scale=0,
                    visible=False,
                    min_width=0,
                )
            with gr.Column(elem_classes=["chat-scroll"]):
                msgs = ui.click_list(messages_html(_new_state()), scroll_bottom=True)
            with gr.Row(elem_classes=["chat-input"]):
                text = gr.Textbox(
                    placeholder=PLACEHOLDER[False],
                    show_label=False,
                    container=False,
                    scale=1,
                    max_lines=3,
                    elem_classes=["chat-text"],
                )
                send = gr.Button("", elem_classes=["send-btn"], scale=0, min_width=40)
        with gr.Column(elem_classes=["right-panel", "side-scroll"]):
            faq = ui.click_list(faq_html())

    outs = [state, msgs, status, connect, new, end, text]
    send.click(_send, [text, state], outs)
    text.submit(_send, [text, state], outs)
    msgs.select(_pick_chip, state, outs)
    faq.select(_pick_faq, state, outs)
    connect.click(_connect, state, outs)
    end.click(_end, state, outs)
    new.click(lambda: _render(_new_state()), None, outs)
    return None  # 메뉴를 옮겨 다녀도 고객센터 대화는 그대로 둔다
