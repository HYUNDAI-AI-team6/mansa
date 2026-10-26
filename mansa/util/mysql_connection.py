from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db import engine as default_engine


def _resolve_engine(engine: Engine | None) -> Engine:
    """인자로 받은 엔진을 쓰고, 없으면 core.db의 공용 엔진을 반환한다.

    DATABASE_URL이 설정되지 않아 공용 엔진이 없으면 RuntimeError를 발생시킨다.
    """
    resolved = engine or default_engine
    if resolved is None:
        raise RuntimeError("DATABASE_URL is not set; check mansa/.env")
    return resolved


def check_connection(engine: Engine | None = None) -> bool:
    """MySQL에 SELECT 1을 보내 연결을 확인한다. 성공하면 True를 반환한다.

    접속 실패는 False로 숨기지 않고 SQLAlchemy 예외를 그대로 전달한다.
    """
    with _resolve_engine(engine).connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1


def fetch_all(
    sql: str, params: dict[str, Any] | None = None, engine: Engine | None = None
) -> list[dict[str, Any]]:
    """SELECT 쿼리를 보내고 결과 행을 컬럼명 키의 dict 리스트로 반환한다.

    값은 반드시 `:name` 자리표시자와 params로 전달한다. 외부 입력을 sql 문자열에
    직접 이어 붙이면 SQL 인젝션이 생긴다. 조회만 하며 데이터를 바꾸지 않는다.
    """
    with _resolve_engine(engine).connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def execute(
    sql: str, params: dict[str, Any] | None = None, engine: Engine | None = None
) -> int:
    """INSERT/UPDATE/DELETE 쿼리를 보내고 영향받은 행 수를 반환한다.

    쿼리 하나를 하나의 트랜잭션으로 실행해 성공하면 커밋하고, 예외가 나면 롤백한다.
    값 전달 규칙은 fetch_all과 같다. WHERE 없는 UPDATE/DELETE는 호출하는 쪽에서 막아야 한다.
    """
    with _resolve_engine(engine).begin() as conn:
        return conn.execute(text(sql), params or {}).rowcount
