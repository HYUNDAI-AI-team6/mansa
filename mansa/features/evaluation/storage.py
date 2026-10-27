"""평가 파일 위치와 저장·읽기.

실행 1회는 SAVE_DIR에 세 파일을 남긴다.
- <run_id>_answers.json: 질문-답변 세트. 채점은 이 파일만으로 다시 돌릴 수 있다.
- <run_id>_result.json: 집계 결과(EvalReport). 화면은 가장 최근 것을 읽는다.
- <run_id>_result.csv: 결과표. 엑셀용 UTF-8 BOM.
"""

import csv
import io
import json
import logging
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from features.evaluation.models import (
    LATENCY_UNITS,
    METRIC_NAMES,
    AnswerRecord,
    EvalReport,
    Failure,
    LlmError,
)

logger = logging.getLogger(__name__)

# 저장소 루트의 eval/. 실행 위치(cwd)와 상관없이 이 파일 기준으로 계산한다.
EVAL_ROOT = Path(__file__).resolve().parents[3] / "eval"
TESTSET_PATH = EVAL_ROOT / "testsets" / "tech_qa.json"
SAVE_DIR = EVAL_ROOT / "save"

NO_VALUE = "값 없음"


def new_run_id(save_dir: Path = SAVE_DIR, now: datetime | None = None) -> str:
    """실행 ID(시작 시각 YYYYMMDD-HHMMSS)를 만든다. 같은 초에 이미 있으면 -2, -3을 붙인다.

    ID가 시각 순으로 정렬되므로 load_latest는 파일명 정렬로 최신 결과를 고른다.
    """
    base = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    run_id, n = base, 1
    while any(save_dir.glob(f"{run_id}_*")):
        n += 1
        run_id = f"{base}-{n}"
    return run_id


def save_answers(
    run_id: str,
    testset_title: str,
    answerer: str,
    started_at: str,
    records: list[AnswerRecord],
    save_dir: Path = SAVE_DIR,
) -> Path:
    """질문-답변 세트 파일을 저장하고 경로를 반환한다. 같은 이름 파일이 있으면 교체한다."""
    data = {
        "run_id": run_id,
        "testset": testset_title,
        "answerer": answerer,
        "started_at": started_at,
        "records": [asdict(r) for r in records],
    }
    path = save_dir / f"{run_id}_answers.json"
    _write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_answers(path: Path) -> tuple[dict, list[AnswerRecord]]:
    """질문-답변 세트 파일을 읽어 (메타 정보, 문항 기록 목록)을 반환한다.

    파일 형식이 맞지 않으면 ValueError를 발생시킨다. 메타 정보는 records를 뺀 나머지 키다.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = [AnswerRecord(**r) for r in data.pop("records")]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"invalid answers file: {path}") from exc
    return data, records


def save_report(report: EvalReport, save_dir: Path = SAVE_DIR) -> tuple[Path, Path]:
    """결과 JSON과 CSV를 저장하고 (json 경로, csv 경로)를 반환한다.

    CSV를 먼저 쓰고 JSON을 나중에 쓴다. 화면은 JSON을 기준으로 최신 결과를 찾으므로
    중간에 실패해도 CSV 없는 결과가 최신으로 잡히지 않는다.
    """
    csv_path = save_dir / f"{report.run_id}_result.csv"
    json_path = save_dir / f"{report.run_id}_result.json"
    _write_atomic(csv_path, report_csv(report), encoding="utf-8-sig")
    _write_atomic(json_path, json.dumps(asdict(report), ensure_ascii=False, indent=2), "utf-8")
    return json_path, csv_path


def load_latest(save_dir: Path = SAVE_DIR) -> EvalReport | None:
    """가장 최근 결과를 읽는다. 결과가 없으면 None이다.

    읽을 수 없는 결과 파일은 경고만 남기고 그 이전 결과를 찾는다.
    """
    for path in sorted(save_dir.glob("*_result.json"), reverse=True):
        try:
            return _report_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("skipping unreadable eval result %s: %s", path.name, exc)
    return None


def latest_csv(save_dir: Path = SAVE_DIR) -> Path | None:
    """가장 최근 결과의 CSV 경로를 반환한다. 결과나 CSV가 없으면 None이다."""
    report = load_latest(save_dir)
    if report is None:
        return None
    path = save_dir / f"{report.run_id}_result.csv"
    return path if path.exists() else None


def format_metric(value: float | None) -> str:
    """지표 백분율을 표시 문자열로 바꾼다. None은 "값 없음"이다."""
    return NO_VALUE if value is None else f"{value:.1f}%"


def format_latency(name: str, value: float | None) -> str:
    """지연(초)·토큰 값을 표시 문자열로 바꾼다. None은 "값 없음"이다."""
    if value is None:
        return NO_VALUE
    return f"{value:.1f}초" if LATENCY_UNITS[name] == "초" else f"{round(value):,}"


def report_csv(report: EvalReport) -> str:
    """결과표 CSV 본문(구분, 항목, 값)을 만든다. 화면의 지표·지연·실패 사례와 같은 내용이다."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["구분", "항목", "값"])
    writer.writerow(["실행", "완료 시각", report.finished_at])
    writer.writerow(["실행", "테스트셋", f"{report.testset_title} ({report.total}문항)"])
    writer.writerow(["실행", "응답기", report.answerer])
    writer.writerows(["지표", n, format_metric(report.metrics.get(n))] for n in METRIC_NAMES)
    writer.writerows(
        ["지연·토큰", n, format_latency(n, report.latency.get(n))] for n in LATENCY_UNITS
    )
    writer.writerows(
        ["실패 사례", f.question, f"{f.workflow} · {f.cause} · {f.detail}"]
        for f in report.failures
    )
    writer.writerows(
        ["LLM 오류", e.question, f"{e.stage} · {e.reason}"] for e in report.llm_errors
    )
    return buffer.getvalue()


def _report_from_dict(data: dict) -> EvalReport:
    """저장된 결과 JSON을 EvalReport로 되돌린다. 필드가 맞지 않으면 KeyError/TypeError가 난다."""
    failures = [Failure(**f) for f in data.pop("failures")]
    # llm_errors가 없는 이전 결과 파일도 읽는다.
    llm_errors = [LlmError(**e) for e in data.pop("llm_errors", [])]
    return EvalReport(failures=failures, llm_errors=llm_errors, **data)


def _write_atomic(path: Path, text: str, encoding: str) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 os.replace로 교체한다. 실패하면 임시 파일을 지운다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
