"""기준정보 서비스가 MySQL에 쿼리를 보내는 기본 함수. 서버 설정이 필요해 호출할 때 불러온다."""

from typing import Any


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """util.mysql_connection.fetch_all로 조회한다. 값은 반드시 params로 넘긴다."""
    from util.mysql_connection import fetch_all as run

    return run(sql, params)


def execute(sql: str, params: dict[str, Any] | None = None) -> int:
    """util.mysql_connection.execute로 입력·수정·삭제를 한다. 영향받은 행 수를 반환한다."""
    from util.mysql_connection import execute as run

    return run(sql, params)
