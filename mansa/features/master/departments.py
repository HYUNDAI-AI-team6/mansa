"""부서 목록·등록·수정. MySQL departments 테이블을 쓴다."""

from collections.abc import Callable
from datetime import date
from typing import Any

from features.master import db
from features.master.errors import DuplicateError, NotFoundError, ValidationError
from features.master.models import Department, DepartmentInput

MAX_LENGTH = 50  # departments.name, departments.description 컬럼이 varchar(50)이다.
_COLUMNS = "id, name, description, created_at"

FetchAll = Callable[[str, dict[str, Any] | None], list[dict[str, Any]]]
Execute = Callable[[str, dict[str, Any] | None], int]


def _to_department(row: dict[str, Any]) -> Department:
    """조회한 행을 Department로 바꾼다."""
    return Department(row["id"], row["name"], row["description"], row.get("created_at"))


def _clean(data: DepartmentInput) -> DepartmentInput:
    """앞뒤 공백을 떼고 이름·설명을 검사한다. 이름이 비었거나 50자를 넘으면 ValidationError다."""
    name, description = (data.name or "").strip(), (data.description or "").strip()
    if not name:
        raise ValidationError("부서 이름을 입력해 주세요")
    if len(name) > MAX_LENGTH or len(description) > MAX_LENGTH:
        raise ValidationError(f"부서 이름과 설명은 {MAX_LENGTH}자 이하로 입력해 주세요")
    return DepartmentInput(name, description)


class DepartmentService:
    """부서 기준정보를 읽고 쓴다. 쿼리 함수는 생성자에서 바꿔 끼울 수 있다."""

    def __init__(self, fetch_all: FetchAll | None = None, execute: Execute | None = None) -> None:
        """지정하지 않은 쿼리 함수는 features.master.db의 기본 함수를 쓴다."""
        self._fetch_all = fetch_all or db.fetch_all
        self._execute = execute or db.execute

    def list_all(self) -> list[Department]:
        """등록된 부서를 등록 순서(id)대로 반환한다. 없으면 빈 리스트다."""
        rows = self._fetch_all(f"SELECT {_COLUMNS} FROM departments ORDER BY id", None)
        return [_to_department(row) for row in rows]

    def create(self, data: DepartmentInput) -> Department:
        """부서를 등록하고 만들어진 부서를 반환한다.

        같은 이름이 있으면 DuplicateError를 발생시킨다. 비교는 DB 정렬 규칙을 따라 대소문자를
        구분하지 않는다. 이름에 UNIQUE 제약이 없어 확인과 저장이 따로라서, 동시에 같은 이름을
        등록하면 둘 다 저장될 수 있다. 등록일은 DB 서버(UTC)가 아니라 앱의 오늘 날짜로 넣는다.
        """
        clean = _clean(data)
        if self._name_taken(clean.name, None):
            raise DuplicateError("이미 등록된 부서예요")
        self._execute(
            "INSERT INTO departments (name, created_at, description) "
            "VALUES (:name, :created_at, :description)",
            {"name": clean.name, "created_at": date.today(), "description": clean.description},
        )
        rows = self._fetch_all(
            f"SELECT {_COLUMNS} FROM departments WHERE name = :name ORDER BY id DESC LIMIT 1",
            {"name": clean.name},
        )
        return _to_department(rows[0])

    def update(self, department_id: int, data: DepartmentInput) -> Department:
        """부서 이름·설명을 바꾸고 바뀐 부서를 반환한다.

        부서가 없으면 NotFoundError, 다른 부서가 같은 이름을 쓰면 DuplicateError를 발생시킨다.
        """
        clean = _clean(data)
        found = self._fetch_all(
            f"SELECT {_COLUMNS} FROM departments WHERE id = :id", {"id": department_id}
        )
        if not found:
            raise NotFoundError(f"department {department_id} not found")
        if self._name_taken(clean.name, department_id):
            raise DuplicateError("이미 등록된 부서예요")
        self._execute(
            "UPDATE departments SET name = :name, description = :description WHERE id = :id",
            {"name": clean.name, "description": clean.description, "id": department_id},
        )
        return Department(department_id, clean.name, clean.description, found[0].get("created_at"))

    def _name_taken(self, name: str, except_id: int | None) -> bool:
        """같은 이름의 부서가 있는지 확인한다. except_id의 부서는 제외한다(자기 자신 수정용)."""
        rows = self._fetch_all("SELECT id FROM departments WHERE name = :name", {"name": name})
        return any(row["id"] != except_id for row in rows)
