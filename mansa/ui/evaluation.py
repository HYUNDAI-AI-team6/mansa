"""평가(A4): 기술 Q&A 테스트셋 실행, 지표 5개, 실패 사례, 지연·토큰, 결과표 내보내기."""

import logging
import threading
from datetime import datetime
from html import escape

import gradio as gr

from features.evaluation import storage
from features.evaluation.answerer import CodexAnswerer
from features.evaluation.codex_cli import CodexError, find_codex
from features.evaluation.judge import CodexJudge
from features.evaluation.models import (
    LATENCY_UNITS,
    METRIC_NAMES,
    EvalProgress,
    EvalReport,
)
from features.evaluation.runner import run_evaluation
from features.evaluation.testset import TestSetError, load_testset
from ui import components as ui
from ui.page import PageView

logger = logging.getLogger(__name__)

FAIL_COLUMNS = [
    ("질문", "1.4fr"),
    ("워크플로", "80px"),
    ("원인", "64px"),
    ("기대 → 실제", "1fr"),
]
LLM_ERROR_COLUMNS = [("질문", "1.4fr"), ("단계", "64px"), ("사유", "1fr")]
NUMBER_NOTE_COLUMNS = [
    ("질문", "1.4fr"),
    ("판정", "72px"),
    ("정답 수치 → 근거 원문", "1fr"),
]
FLOW_TAG = {"L2": "blue", "L3": "purple"}
CAUSE_TAG = {"검색": "red", "조회": "orange", "생성": "red"}

RUN_CLASSES = ["btn-primary", "sm-btn"]
# shortcut: 목표값이 정해지지 않아 임시로 60% 이상(과잉 첨부율만 낮을수록 좋아 40% 이하). 기준이 정해지면 바꾼다.
TARGET_PERCENT = 60
LOWER_IS_BETTER = {"과잉 첨부율": 40}
NO_RESULT = "평가 결과가 없어요"

# 평가 1회는 Codex를 문항 수 × 2번 부르므로 동시에 하나만 돌린다(세션이 달라도).
_RUN_LOCK = threading.Lock()


def _testset_info() -> tuple[str, str]:
    """테스트셋 카드에 보일 (이름, 설명). 테스트셋을 못 읽으면 오류 내용을 설명에 보여 준다."""
    try:
        testset = load_testset(storage.TESTSET_PATH)
    except TestSetError as exc:
        return "기술 Q&A 테스트셋", f"테스트셋을 읽을 수 없어요: {exc}"
    return testset.title, f"{len(testset.cases)}문항 · {testset.description}"


def _last_run(report: EvalReport | None) -> str:
    """마지막 실행(전체 평가가 끝난 시각)을 MM/DD HH:MM으로 보여 준다."""
    if report is None:
        return "없음"
    return datetime.fromisoformat(report.finished_at).strftime("%m/%d %H:%M")


def run_card_html(
    report: EvalReport | None = None, caption: str = "", percent: int | None = None
) -> str:
    """테스트셋 카드 왼쪽 내용 (이름 · 설명 · 마지막 실행). percent 가 있으면 진행 막대."""
    title, desc = _testset_info()
    if percent is None:
        foot = f'<span class="cap">마지막 실행 {escape(_last_run(report))}</span>'
    else:
        foot = (
            '<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" '
            f'aria-valuenow="{percent}"><span style="width:{percent}%"></span></div>'
            f'<span class="cap">{escape(caption)} · {percent}%</span>'
        )
    return (
        f'<div class="run-info"><div class="title">{escape(title)}'
        f"{ui.tag('L2', 'blue')}</div><p>{escape(desc)}</p>{foot}</div>"
    )


def metrics_html(report: EvalReport | None = None) -> str:
    """지표 카드 5개. 결과가 없으면 [값] 자리표시를 보여 준다."""

    def value(name: str) -> str:
        """지표 하나의 표시 값."""
        return storage.format_metric(report.metrics.get(name)) if report else "[값]%"

    cards = "".join(
        f'<div class="card metric"><span class="label">{escape(name)}</span>'
        f"<b>{escape(value(name))}</b></div>"
        for name in METRIC_NAMES
    )
    return f'<div class="metrics">{cards}</div>'


def failures_html(report: EvalReport | None = None) -> str:
    """실패 사례 카드. LLM 오류·수치 LLM 판정 기록이 있으면 그 아래에 카드를 붙인다."""
    failures = report.failures if report else []
    rows = [
        [
            ui.cell(f"<b>{escape(f.question)}</b>"),
            ui.cell(ui.tag(f.workflow, FLOW_TAG[f.workflow])),
            ui.cell(ui.tag(f.cause, CAUSE_TAG[f.cause])),
            ui.cell(f"<em>{escape(f.detail)}</em>"),
        ]
        for f in failures
    ]
    empty = "실패한 문항이 없어요" if report else NO_RESULT
    head = (
        '<div class="card-head"><div class="title">실패 사례'
        f'<span class="count">{len(failures)}건</span></div></div>'
    )
    card = f'<div class="card fail-card">{head}{ui.table_html(FAIL_COLUMNS, rows, empty)}</div>'
    extra = llm_errors_html(report) + number_notes_html(report)
    return f'<div class="fail-stack">{card}{extra}</div>' if extra else card


def llm_errors_html(report: EvalReport | None) -> str:
    """답변·채점 LLM 호출 실패 카드. 오류가 없으면 빈 문자열이다.

    이 문항들은 지표에서는 실패로 세지만 답변 품질 실패와 구분하려고 따로 보여 준다.
    """
    errors = report.llm_errors if report else []
    if not errors:
        return ""
    rows = [
        [
            ui.cell(f"<b>{escape(e.question)}</b>"),
            ui.cell(ui.tag(e.stage, "gray")),
            ui.cell(f"<em>{escape(e.reason)}</em>"),
        ]
        for e in errors
    ]
    head = (
        '<div class="card-head"><div class="title">LLM 오류'
        f'<span class="count">{len(errors)}건</span></div></div>'
    )
    return f'<div class="card fail-card">{head}{ui.table_html(LLM_ERROR_COLUMNS, rows)}</div>'


def number_notes_html(report: EvalReport | None) -> str:
    """수치 정확도를 규칙과 채점 LLM이 다르게 본 기록 카드. 기록이 없으면 빈 문자열이다.

    LLM 통과는 지표에서 통과로 셌고, LLM 이견은 규칙 판정(통과)을 따랐다. 사람이 확인할 대상이다.
    """
    notes = report.number_notes if report else []
    if not notes:
        return ""
    rows = [
        [
            ui.cell(f"<b>{escape(n.question)}</b>"),
            ui.cell(ui.tag(n.kind, "gray")),
            ui.cell(f"<em>{escape(n.expected)} → {escape(n.quote or '없음')}</em>"),
        ]
        for n in notes
    ]
    head = (
        '<div class="card-head"><div class="title">수치 LLM 판정'
        f'<span class="count">{len(notes)}건</span></div></div>'
    )
    return f'<div class="card fail-card">{head}{ui.table_html(NUMBER_NOTE_COLUMNS, rows)}</div>'


def latency_html(report: EvalReport | None = None) -> str:
    """지연·토큰 목록. 결과가 없으면 [값] 자리표시를 보여 준다."""

    def value(name: str) -> str:
        """지연·토큰 항목 하나의 표시 값."""
        return (
            storage.format_latency(name, report.latency.get(name)) if report else "[값]"
        )

    rows = "".join(
        f'<div class="kv-row"><span>{escape(name)}</span><b>{escape(value(name))}</b></div>'
        for name in LATENCY_UNITS
    )
    return f'<div class="card-head"><div class="title">지연 · 토큰</div></div>{rows}'


def export_csv() -> str | None:
    """가장 최근 결과의 CSV 경로 (eval/save/). 결과가 없으면 None."""
    path = storage.latest_csv()
    return str(path) if path else None


def _warn_if_no_result() -> None:
    """결과가 없을 때 내보내기를 누르면 안내한다."""
    if storage.latest_csv() is None:
        ui.warn(NO_RESULT)


def _view(report: EvalReport | None) -> tuple:
    """결과 하나로 카드·지표·실패 사례·지연·내보내기 파일을 다시 그린다."""
    return (
        run_card_html(report),
        metrics_html(report),
        failures_html(report),
        latency_html(report),
        export_csv(),
    )


def _progress(event: EvalProgress) -> tuple[str, int]:
    """진행 상황을 (안내 문구, 전체 %)로 바꾼다. 답변 받기가 앞 절반, 채점이 뒤 절반이다."""
    total = max(event.total, 1)
    half = 50 * event.done // total
    if event.stage == "judge":
        return f"채점하는 중이에요 {event.done}/{event.total}", 50 + half
    return f"답변을 받는 중이에요 {event.done}/{event.total}", half


def _run():
    """평가를 실행하고 진행률과 결과를 화면에 내보낸다.

    Codex를 문항 수 × 2번 실행한다. 다른 평가가 실행 중이면 시작하지 않는다.
    """
    skip = (gr.skip(),) * 4
    if not _RUN_LOCK.acquire(blocking=False):
        ui.warn("이미 평가가 실행 중이에요")
        yield gr.skip(), gr.skip(), *skip
        return
    try:
        find_codex()
        events = run_evaluation(CodexAnswerer(), CodexJudge())
        for event in events:
            if isinstance(event, EvalProgress):
                caption, percent = _progress(event)
                card = run_card_html(caption=caption, percent=percent)
                yield card, ui.loading_button("실행 중", RUN_CLASSES), *skip
            else:
                ui.notify(
                    f"평가를 마쳤어요 · 실패 {len(event.failures)}건 · LLM 오류 {len(event.llm_errors)}건"
                )
                card, *rest = _view(event)
                yield card, ui.idle_button("평가 실행", RUN_CLASSES), *rest
    except (CodexError, TestSetError) as exc:
        ui.warn(str(exc))
        yield run_card_html(storage.load_latest()), ui.idle_button(
            "평가 실행", RUN_CLASSES
        ), *skip
    except Exception:
        # 화면 경계: 버튼이 "실행 중"에 멈추지 않게 되돌리고 원인은 로그로 남긴다.
        logger.exception("evaluation run failed")
        ui.warn("평가 중 오류가 났어요. 로그를 확인해 주세요")
        yield run_card_html(storage.load_latest()), ui.idle_button(
            "평가 실행", RUN_CLASSES
        ), *skip
    finally:
        _RUN_LOCK.release()


def build() -> PageView:
    """평가 화면을 만든다. 메뉴로 들어올 때마다 eval/save/의 최근 결과로 다시 그린다."""
    report = storage.load_latest()
    with gr.Row(elem_classes=["card", "run-card"]):
        info = gr.HTML(run_card_html(report), padding=False, scale=1)
        run = gr.Button("평가 실행", elem_classes=RUN_CLASSES, scale=0, min_width=0)
    gr.HTML(ui.section_title("기술 Q&A 결과"), padding=False)
    metrics = gr.HTML(metrics_html(report), padding=False)
    with gr.Row(elem_classes=["body-row"]):
        failures = gr.HTML(
            failures_html(report), padding=False, elem_classes=["grow-col"]
        )
        with gr.Column(elem_classes=["card", "right-panel", "latency-card"]):
            latency = gr.HTML(latency_html(report), padding=False)
            download = gr.DownloadButton(
                "결과표 내보내기 (CSV)",
                value=export_csv(),
                elem_classes=["btn-secondary", "sm-btn", "full"],
            )
    run.click(
        _run,
        None,
        [info, run, metrics, failures, latency, download],
        show_progress="hidden",
    )
    download.click(_warn_if_no_result, None, None)
    return PageView(
        lambda: _view(storage.load_latest()),
        reset_outputs=[info, metrics, failures, latency, download],
    )
