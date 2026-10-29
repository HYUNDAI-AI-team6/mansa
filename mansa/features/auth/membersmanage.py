"""회원 관리: users(사용자)와 admins(관리자) 테이블의 회원 목록·등록·수정.

SQL 은 util.mysql_connection 의 fetch_all, execute 로만 보낸다.
서버 설정이 필요해 호출할 때 불러온다.
"""

from typing import Any

from config import ADMIN_DEPT_LABEL, MEMBER_MAX_LENGTH
from features.auth.service import hash_password
from features.master.errors import DuplicateError, NotFoundError, ValidationError

ROLES = ("user", "admin")

LIST_SQL = (
    "SELECT 'user' AS role, u.id, u.login_id, u.name, d.name AS dept, u.created_at "
    "FROM users u LEFT JOIN departments d ON d.id = u.department_id "
    "WHERE u.status <> 'deleted' "
    "UNION ALL "
    "SELECT 'admin', a.id, a.login_id, a.name, :admin_dept, a.created_at FROM admins a "
    "ORDER BY created_at, id"
)
# 테이블명은 고정 값이라 외부 입력이 섞이지 않는다. id 는 AUTO_INCREMENT 가 아니라 한 문장 안에서
# 최댓값+1 로 정하고, 같은 아이디가 이미 있으면 한 줄도 넣지 않는다(영향받은 행 0).
# shortcut: 두 테이블 사이의 아이디 중복은 먼저 조회해서 막는다,
# DB 에 UNIQUE 를 걸면 이 우회가 필요 없다.
INSERT_USER = (
    "INSERT INTO users (id, login_id, password_hash, name, department_id) "
    "SELECT n.id, :login_id, :hash, :name, :dept "
    "FROM (SELECT COALESCE(MAX(id), 0) + 1 AS id FROM users) n "
    "WHERE NOT EXISTS (SELECT 1 FROM users WHERE login_id = :login_id)"
)
INSERT_ADMIN = (
    "INSERT INTO admins (id, login_id, password_hash, name) "
    "SELECT n.id, :login_id, :hash, :name "
    "FROM (SELECT COALESCE(MAX(id), 0) + 1 AS id FROM admins) n "
    "WHERE NOT EXISTS (SELECT 1 FROM admins WHERE login_id = :login_id)"
)


def _fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """util.mysql_connection.fetch_all 로 조회한다. 값은 반드시 params 로 넘긴다."""
    from util.mysql_connection import fetch_all

    return fetch_all(sql, params)


def _execute(sql: str, params: dict[str, Any] | None = None) -> int:
    """util.mysql_connection.execute 로 입력·수정을 한다. 영향받은 행 수를 반환한다."""
    from util.mysql_connection import execute

    return execute(sql, params)


def list_members() -> list[dict]:
    """회원을 등록 순서대로 돌려준다. 키: role(user·admin), id, login_id, name, dept, created_at."""
    return _fetch_all(LIST_SQL, {"admin_dept": ADMIN_DEPT_LABEL})


def list_departments() -> dict[str, int]:
    """부서 이름 -> id."""
    rows = _fetch_all("SELECT id, name FROM departments ORDER BY id")
    return {r["name"]: r["id"] for r in rows}


def login_id_taken(
    login_id: str, except_role: str | None = None, except_id: int | None = None
) -> bool:
    """users·admins 어느 쪽이든 같은 아이디가 있으면 True. except_* 는 수정 중인 본인 행이다."""
    params = {"login_id": login_id}
    for role, table in (("user", "users"), ("admin", "admins")):
        rows = _fetch_all(f"SELECT id FROM {table} WHERE login_id = :login_id", params)
        if any(not (role == except_role and r["id"] == except_id) for r in rows):
            return True
    return False


def _clean(role: str, login_id: str, name: str, dept_id: int | None) -> tuple[str, str]:
    """입력을 검사하고 앞뒤 공백을 뺀 (아이디, 이름)을 돌려준다."""
    login_id, name = (login_id or "").strip(), (name or "").strip()
    if role not in ROLES:
        raise ValidationError("권한을 확인해 주세요")
    if not login_id or not name:
        raise ValidationError("아이디와 이름을 입력해 주세요")
    if len(login_id) > MEMBER_MAX_LENGTH or len(name) > MEMBER_MAX_LENGTH:
        raise ValidationError(f"아이디와 이름은 {MEMBER_MAX_LENGTH}자 이하로 입력해 주세요")
    if role == "user" and dept_id is None:
        raise ValidationError("소속 부서를 선택해 주세요")
    return login_id, name


def create_member(
    role: str, login_id: str, name: str, dept_id: int | None, password: str
) -> None:
    """회원을 등록한다. 비밀번호는 argon2id 해시로만 저장한다."""
    login_id, name = _clean(role, login_id, name, dept_id)
    if not (password or "").strip():
        raise ValidationError("초기 비밀번호를 입력해 주세요")
    if login_id_taken(login_id):
        raise DuplicateError("이미 쓰고 있는 아이디예요")
    params = {"login_id": login_id, "hash": hash_password(password), "name": name}
    if role == "user":
        added = _execute(INSERT_USER, {**params, "dept": dept_id})
    else:
        added = _execute(INSERT_ADMIN, params)
    if not added:  # 조회와 입력 사이에 같은 아이디가 들어온 경우
        raise DuplicateError("이미 쓰고 있는 아이디예요")


def update_member(
    role: str, pk: int, login_id: str, name: str, dept_id: int | None, password: str = ""
) -> None:
    """회원 정보를 고친다. 비밀번호는 입력했을 때만 바꾼다. 권한(테이블)은 바꾸지 않는다."""
    login_id, name = _clean(role, login_id, name, dept_id)
    table = "users" if role == "user" else "admins"
    if not _fetch_all(f"SELECT id FROM {table} WHERE id = :id", {"id": pk}):
        raise NotFoundError("이미 없어진 회원이에요")
    if login_id_taken(login_id, except_role=role, except_id=pk):
        raise DuplicateError("이미 쓰고 있는 아이디예요")
    sets = ["login_id = :login_id", "name = :name", "updated_at = NOW()"]
    params: dict[str, Any] = {"id": pk, "login_id": login_id, "name": name}
    if role == "user":
        sets.append("department_id = :dept")
        params["dept"] = dept_id
    if (password or "").strip():
        sets.append("password_hash = :hash")
        params["hash"] = hash_password(password)
    _execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = :id", params)
