"""시연용 부서를 DB에 넣는다. 기본은 확인만 하고, --apply를 줘야 DB를 바꾼다.

사용: cd mansa && PYTHONPATH=. uv run --locked python -m scripts.seed [--apply]
이미 있는 부서는 건너뛰므로 여러 번 실행해도 중복되지 않는다.
"""

import argparse
from collections.abc import Callable
from typing import Any

from features.master import db
from features.master.departments import DepartmentService
from features.master.models import DepartmentInput

DEMO_DEPARTMENTS = [
    DepartmentInput("유지보수팀", "매뉴얼 · 사양서 관리"),
    DepartmentInput("안전팀", "법규 · 지침 · 사내 규정"),
    DepartmentInput("검사·품질팀", "검사 절차서 · 체크리스트"),
]
FetchAll = Callable[[str, dict[str, Any] | None], list[dict[str, Any]]]
Execute = Callable[[str, dict[str, Any] | None], int]


def seed_departments(fetch_all: FetchAll, execute: Execute, apply: bool) -> list[str]:
    """없는 시연용 부서만 등록한다. 등록했거나(apply) 등록할(확인만) 부서 이름을 반환한다."""
    existing = {row["name"] for row in fetch_all("SELECT name FROM departments", None)}
    missing = [d for d in DEMO_DEPARTMENTS if d.name not in existing]
    if apply:
        service = DepartmentService(fetch_all, execute)
        for department in missing:
            service.create(department)
    return [d.name for d in missing]


def run(apply: bool, fetch_all: FetchAll, execute: Execute) -> list[str]:
    """데모 부서를 처리하고 한 줄씩 결과를 반환한다. apply가 아니면 DB를 바꾸지 않는다."""
    prefix = "" if apply else "[dry-run] "
    return [f"{prefix}departments to add: {seed_departments(fetch_all, execute, apply)}"]


def main() -> None:
    """명령줄에서 실행한다. --apply가 없으면 DB를 바꾸지 않는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="DB에 실제로 반영한다")
    for line in run(parser.parse_args().apply, db.fetch_all, db.execute):
        print(line)


if __name__ == "__main__":
    main()
