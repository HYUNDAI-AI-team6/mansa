"""오래 걸리는 작업(문서 업로드, 평가 실행) 동안 화면 내용을 덮는 로딩 레이어.

사이드바와 상단 머리글은 가리지 않아서 기다리는 동안 다른 메뉴로 갈 수 있다. 작업을 시작한 화면은 서버가 상태를
기억하므로, 다른 메뉴에 갔다가 돌아와도 작업이 끝나기 전까지는 레이어가 그대로 떠 있다.

쓰는 법(작업을 처리하는 함수는 generator 로 만든다)::

    started = busy.start()
    yield ..., busy.show("제목", "설명")       # 시작하자마자 바로 보여 준다
    ...작업...
    busy.hold(started)                         # 아무리 빨리 끝나도 MIN_SECONDS 는 보여 준다
    yield ..., busy.hide()

필수값이 빠진 것처럼 작업을 시작하지 않을 때는 show 를 부르지 않는다.
"""

import time
from functools import cache
from html import escape

import gradio as gr

MIN_SECONDS = 3.0
LAYER_CLASS = "busy-layer"

# 8자(∞) 궤적. 빛 하나가 이 선을 따라 한 방향으로 계속 달린다.
LOOP_PATH = "M60 30C75 8 110 8 110 30C110 52 75 52 60 30C45 8 10 8 10 30C10 52 45 52 60 30Z"
TAIL_COLOR = (125, 211, 252)  # 꼬리 끝(하늘색)
MID_COLOR = (59, 91, 246)  # 서비스 파랑
HEAD_COLOR = (124, 58, 237)  # 머리(보라)
TAIL_LAYERS = 26  # 얇은 선을 겹쳐 꼬리가 서서히 옅어지게 한다
TAIL_LONGEST = 40  # 가장 긴 꼬리(전체 길이를 100으로 본 값)
TAIL_SHORTEST = 3
STROKE = 7
LAYER_OPACITY = 0.13
# 머리 쪽 테두리에만 하얗게 번지는 그라데이션: 꼬리 선보다 조금 굵은 흰 선을 아래에 깔아 가장자리로만 비친다.
# (길이, 굵기, 불투명도): 짧을수록 머리 끝에 가깝고 겹쳐서 진해진다.
HEAD_RIM = ((16, 9.4, 0.18), (11, 9.4, 0.22), (7, 9.8, 0.3), (4, 10.2, 0.45), (1.6, 10.6, 0.7))


def _mix(a: tuple, b: tuple, t: float) -> str:
    """두 색 사이 t(0~1) 지점의 색."""
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _tail_color(t: float) -> str:
    """꼬리 끝(0) → 머리(1)로 갈수록 하늘색 → 파랑 → 보라."""
    split = 0.625
    if t < split:
        return _mix(TAIL_COLOR, MID_COLOR, t / split)
    return _mix(MID_COLOR, HEAD_COLOR, (t - split) / (1 - split))


@cache
def _loop_svg() -> str:
    """8자 선과 그 위를 달리는 빛 하나(길이가 다른 선 26겹, 그 아래에 머리 쪽 테두리용 흰 선)."""
    rim = "".join(
        f'<path class="seg" pathLength="100" d="{LOOP_PATH}" '
        f'style="--len:{length};stroke:#ffffff;stroke-width:{width};'
        f'stroke-dasharray:{length} {round(100 - length, 2)};opacity:{opacity}"/>'
        for length, width, opacity in HEAD_RIM
    )
    paths = [f'<path class="track" d="{LOOP_PATH}"/>', f'<g class="busy-rim">{rim}</g>']
    for i in range(TAIL_LAYERS):
        t = i / (TAIL_LAYERS - 1)
        length = round(TAIL_LONGEST - t * (TAIL_LONGEST - TAIL_SHORTEST), 2)
        paths.append(
            f'<path class="seg" pathLength="100" d="{LOOP_PATH}" '
            f'style="--len:{length};stroke:{_tail_color(t)};stroke-width:{STROKE};'
            f'stroke-dasharray:{length} {round(100 - length, 2)};opacity:{LAYER_OPACITY}"/>'
        )
    return f'<svg class="busy-loop" viewBox="0 0 120 60" aria-hidden="true">{"".join(paths)}</svg>'


def layer_html(title: str, sub: str) -> str:
    """레이어 안쪽 모양: 물결·빛·반짝이 + 8자를 도는 빛 + 제목(점 세 개) + 설명."""
    return (
        '<div class="busy-body" role="status" aria-live="polite">'
        '<div class="busy-box">'
        '<div class="busy-stage" aria-hidden="true">'
        '<span class="busy-halo"></span>'
        '<span class="busy-ring"></span><span class="busy-ring"></span><span class="busy-ring"></span>'
        '<span class="busy-spark a"></span><span class="busy-spark b"></span><span class="busy-spark c"></span>'
        '<span class="busy-spark d"></span><span class="busy-spark e"></span>'
        f"{_loop_svg()}</div>"
        f'<div class="busy-title"><span>{escape(title)}</span>'
        '<span class="busy-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>'
        f'<div class="busy-sub">{escape(sub)}</div>'
        "</div></div>"
    )


def component() -> gr.HTML:
    """화면 맨 아래에 한 번 놓는 레이어 자리. 평소에는 숨겨져 있다."""
    return gr.HTML(visible=False, padding=False, elem_classes=[LAYER_CLASS])


def show(title: str, sub: str) -> gr.HTML:
    """레이어를 보인다. 이벤트 처리 함수가 돌려주는 값으로 쓴다."""
    return gr.HTML(layer_html(title, sub), visible=True)


def hide() -> gr.HTML:
    """레이어를 숨긴다."""
    return gr.HTML(visible=False)


def start() -> float:
    """작업을 시작한 시각. hold 에 넘긴다."""
    return time.monotonic()


def hold(started: float) -> None:
    """레이어를 시작한 뒤 MIN_SECONDS 가 지나지 않았으면 남은 만큼 기다린다."""
    remaining = MIN_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)
