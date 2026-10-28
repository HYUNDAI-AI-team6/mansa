"""부서 서비스 테스트용 가짜 DB. 쓰는 쿼리 문장만 알아듣는 아주 단순한 메모리 구현이다."""

from datetime import datetime


class FakeMasterDb:
    """departments 테이블을 메모리에 두고 서비스가 보내는 쿼리에 답한다."""

    def __init__(self, departments=None):
        self.departments = [dict(d) for d in (departments or [])]
        self.queries = []

    def fetch_all(self, sql, params=None):
        """SELECT 쿼리에 답한다. 모르는 쿼리면 AssertionError로 테스트를 멈춘다."""
        params = params or {}
        self.queries.append((sql, params))
        if "FROM departments" in sql:
            return self._select_departments(sql, params)
        raise AssertionError(f"unexpected query: {sql}")

    def _select_departments(self, sql, params):
        """부서 SELECT 네 가지(전체·이름 하나·id 하나·이름만)에 답한다."""
        rows = sorted(self.departments, key=lambda d: d["id"])
        if "WHERE name" in sql:
            rows = [d for d in rows if d["name"].lower() == params["name"].lower()]
            return rows[-1:] if "LIMIT 1" in sql else [{"id": d["id"]} for d in rows]
        if "WHERE id" in sql:
            return [d for d in rows if d["id"] == params["id"]]
        if sql.startswith("SELECT name"):
            return [{"name": d["name"]} for d in rows]
        return rows

    def execute(self, sql, params=None):
        """INSERT·UPDATE를 메모리에 반영하고 영향받은 행 수를 반환한다."""
        params = params or {}
        self.queries.append((sql, params))
        if sql.startswith("INSERT INTO departments"):
            next_id = max([d["id"] for d in self.departments], default=0) + 1
            self.departments.append({"id": next_id, "name": params["name"],
                                     "description": params["description"],
                                     "created_at": datetime(2026, 10, 28)})
        elif sql.startswith("UPDATE departments"):
            for d in self.departments:
                if d["id"] == params["id"]:
                    d.update(name=params["name"], description=params["description"])
        else:
            raise AssertionError(f"unexpected statement: {sql}")
        return 1
