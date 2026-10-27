"""테스트셋 JSON 파일을 읽고 형식을 검증한다."""

import json
from pathlib import Path
from typing import Any, get_args

from features.evaluation.models import TestCase, TestSet, Workflow

_REQUIRED = ("id", "question", "workflow", "expected_numbers", "expected_sources")


class TestSetError(ValueError):
    """테스트셋 파일이 없거나 형식이 잘못됐을 때 발생한다. 메시지에 문제 문항과 이유가 들어간다."""

    __test__ = False


def load_testset(path: Path) -> TestSet:
    """테스트셋 파일을 읽어 TestSet으로 반환한다.

    문항 하나라도 잘못되면 일부만 쓰지 않고 TestSetError를 발생시킨다(평가 시작 전 거부).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise TestSetError(f"testset file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TestSetError(f"testset is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise TestSetError("testset must be an object with a 'cases' list")

    cases = [_parse_case(item, index) for index, item in enumerate(raw["cases"], start=1)]
    _check_unique_ids(cases)
    return TestSet(
        title=str(raw.get("title") or path.stem),
        description=str(raw.get("description") or ""),
        cases=cases,
    )


def _parse_case(item: Any, index: int) -> TestCase:
    """문항 하나를 검증해 TestCase로 바꾼다. index는 오류 메시지용 1부터 시작하는 순번이다."""
    label = f"case #{index}"
    if not isinstance(item, dict):
        raise TestSetError(f"{label}: must be an object")
    if isinstance(item.get("id"), str):
        label = f"case {item['id']!r}"
    missing = [key for key in _REQUIRED if key not in item]
    if missing:
        raise TestSetError(f"{label}: missing fields {missing}")
    if not isinstance(item["id"], str) or not item["id"].strip():
        raise TestSetError(f"{label}: 'id' must be a non-empty string")
    if not isinstance(item["question"], str) or not item["question"].strip():
        raise TestSetError(f"{label}: 'question' must be a non-empty string")
    if item["workflow"] not in get_args(Workflow):
        raise TestSetError(f"{label}: 'workflow' must be one of {list(get_args(Workflow))}")
    for key in ("expected_numbers", "expected_sources"):
        values = item[key]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise TestSetError(f"{label}: '{key}' must be a list of strings")
    return TestCase(
        id=item["id"],
        question=item["question"],
        workflow=item["workflow"],
        expected_numbers=list(item["expected_numbers"]),
        expected_sources=list(item["expected_sources"]),
    )


def _check_unique_ids(cases: list[TestCase]) -> None:
    """문항 id가 중복되면 TestSetError를 발생시킨다."""
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise TestSetError(f"case {case.id!r}: duplicate id")
        seen.add(case.id)
