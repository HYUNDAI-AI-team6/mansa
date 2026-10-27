"""평가(A4): 기술 Q&A 테스트셋 실행, 지표 5개, 실패 사례, 지연·토큰, 결과표 내보내기."""

import csv
import tempfile
from datetime import datetime
from html import escape

import gradio as gr

from ui import components as ui
from ui import mock_data as mock

FAIL_COLUMNS = [("질문", "1.4fr"), ("워크플로", "80px"), ("원인", "64px"), ("기대 → 실제", "1fr")]
FLOW_TAG = {"L2": "blue", "L3": "purple"}
CAUSE_TAG = {"검색": "red", "조회": "orange", "생성": "red"}


RUN_STEPS = [10, 35, 60, 85, 100]  # 실행 중 보여 줄 진행률(%)
RUN_CLASSES = ["btn-primary", "sm-btn"]


def run_card_html(last_run: str = "", percent: int | None = None) -> str:
    """테스트셋 카드 왼쪽 내용 (이름 · 설명 · 마지막 실행). percent 가 있으면 진행 막대."""
    if percent is None:
        foot = f'<span class="cap">마지막 실행 {escape(last_run)}</span>'
    else:
        foot = (
            '<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" '
            f'aria-valuenow="{percent}"><span style="width:{percent}%"></span></div>'
            f'<span class="cap">평가하는 중이에요 · {percent}%</span>'
        )
    return (
        f'<div class="run-info"><div class="title">{escape(mock.EVAL_SET["title"])}'
        f"{ui.tag('L2', 'blue')}</div><p>{escape(mock.EVAL_SET['desc'])}</p>{foot}</div>"
    )


def metrics_html() -> str:
    """지표 카드 5개 (값은 예시 [값])."""
    cards = "".join(
        f'<div class="card metric"><span class="label">{escape(name)}</span>'
        '<b>[값]%</b><span class="goal">목표 [값]%</span></div>'
        for name in mock.EVAL_METRICS
    )
    return f'<div class="metrics">{cards}</div>'


def failures_html() -> str:
    """실패 사례 카드."""
    rows = [
        [
            ui.cell(f"<b>{escape(f['q'])}</b>"),
            ui.cell(ui.tag(f["flow"], FLOW_TAG[f["flow"]])),
            ui.cell(ui.tag(f["cause"], CAUSE_TAG[f["cause"]])),
            ui.cell(f"<em>{escape(f['detail'])}</em>"),
        ]
        for f in mock.EVAL_FAILURES
    ]
    head = (
        '<div class="card-head"><div class="title">실패 사례'
        f'<span class="count">{len(mock.EVAL_FAILURES)}건</span></div></div>'
    )
    return f'<div class="card fail-card">{head}{ui.table_html(FAIL_COLUMNS, rows)}</div>'


def latency_html() -> str:
    """지연·토큰 목록."""
    rows = "".join(
        f'<div class="kv-row"><span>{escape(k)}</span><b>{escape(v)}</b></div>'
        for k, v in mock.EVAL_LATENCY
    )
    return f'<div class="card-head"><div class="title">지연 · 토큰</div></div>{rows}'


def export_csv() -> str:
    """결과표를 CSV 파일로 만들어 경로를 돌려준다 (엑셀에서 한글이 깨지지 않게 BOM 포함)."""
    path = tempfile.NamedTemporaryFile(prefix="mansa_eval_", suffix=".csv", delete=False).name
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["구분", "항목", "값"])
        writer.writerows(["지표", name, "[값]%"] for name in mock.EVAL_METRICS)
        writer.writerows(["지연·토큰", k, v] for k, v in mock.EVAL_LATENCY)
        writer.writerows(
            ["실패 사례", f["q"], f"{f['flow']} · {f['cause']} · {f['detail']}"]
            for f in mock.EVAL_FAILURES
        )
    return path


def _run():
    """평가 실행(목데이터): 진행 막대를 채운 뒤 마지막 실행 시각만 바꾼다.

    평가 스크립트가 생기면 진행률을 그 함수에서 받아 온다.
    """
    for percent in RUN_STEPS[:-1]:
        yield run_card_html(percent=percent), ui.loading_button("실행 중…", RUN_CLASSES)
        mock.wait(mock.MOCK_DELAY / 2)
    now = datetime.now().strftime("%m/%d %H:%M")
    ui.notify("평가를 실행했어요 (목데이터라 결과 값은 그대로예요)")
    yield run_card_html(now), ui.idle_button("평가 실행", RUN_CLASSES)


def build() -> None:
    """평가 화면을 만든다. 메뉴를 옮겨도 마지막 실행 시각은 그대로 둔다."""
    with gr.Row(elem_classes=["card", "run-card"]):
        info = gr.HTML(run_card_html(mock.EVAL_SET["last_run"]), padding=False, scale=1)
        run = gr.Button("평가 실행", elem_classes=RUN_CLASSES, scale=0, min_width=0)
    gr.HTML(ui.section_title("기술 Q&A 결과"), padding=False)
    gr.HTML(metrics_html(), padding=False)
    with gr.Row(elem_classes=["body-row"]):
        gr.HTML(failures_html(), padding=False, elem_classes=["grow-col"])
        with gr.Column(elem_classes=["card", "right-panel", "latency-card"]):
            gr.HTML(latency_html(), padding=False)
            gr.DownloadButton(
                "결과표 내보내기 (CSV)",
                value=export_csv,
                elem_classes=["btn-secondary", "sm-btn", "full"],
            )
    run.click(_run, None, [info, run], show_progress="hidden")
