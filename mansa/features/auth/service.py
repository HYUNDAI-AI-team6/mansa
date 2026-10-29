"""로그인: 사용자는 users, 관리자는 admins 테이블의 계정으로만 인증한다."""

from collections.abc import Callable
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

FAIL_MESSAGE = "아이디 또는 비밀번호가 올바르지 않아요"
EMPTY_MESSAGE = "아이디와 비밀번호를 입력해 주세요"

_hasher = PasswordHasher()

# role -> (계정 조회 SQL, 마지막 로그인 갱신 SQL). 테이블명은 고정 값이라 외부 입력이 섞이지 않는다.
_QUERIES = {
    "user": (
        "SELECT u.id, u.login_id, u.password_hash, u.name, d.name AS dept FROM users u "
        "JOIN departments d ON d.id = u.department_id "
        "WHERE u.login_id = :login_id AND u.status = 'active'",
        "UPDATE users SET last_login_at = NOW() WHERE id = :id",
    ),
    "admin": (
        "SELECT id, login_id, password_hash, name, '관리자' AS dept FROM admins "
        "WHERE login_id = :login_id AND status = 'active'",
        "UPDATE admins SET last_login_at = NOW() WHERE id = :id",
    ),
}


def hash_password(password: str) -> str:
    """비밀번호를 argon2id 해시 문자열로 만든다. 솔트와 파라미터가 해시 안에 들어 있다."""
    return _hasher.hash(password)


class AuthService:
    """권한(user·admin)별 테이블에 있는 활성 계정과 비밀번호가 맞을 때만 로그인시킨다."""

    def __init__(
        self,
        fetch_all: Callable[..., list[dict[str, Any]]],
        execute: Callable[..., int],
    ) -> None:
        self._fetch_all = fetch_all
        self._execute = execute

    def login(self, role: str, login_id: str, password: str) -> tuple[dict | None, str]:
        """(회원 정보 또는 None, 오류 문구)를 반환한다. 아이디 없음·비밀번호 틀림은 같은 문구다."""
        login_id = login_id.strip()
        if not login_id or not password:
            return None, EMPTY_MESSAGE
        select, touch = _QUERIES[role]
        rows = self._fetch_all(select, {"login_id": login_id})
        if not rows or not self._matches(rows[0]["password_hash"], password):
            return None, FAIL_MESSAGE
        row = rows[0]
        self._execute(touch, {"id": row["id"]})
        return {"id": row["login_id"], "role": role, "name": row["name"], "dept": row["dept"]}, ""

    @staticmethod
    def _matches(password_hash: str, password: str) -> bool:
        """해시와 비밀번호가 맞으면 True. 형식이 깨진 해시도 로그인 실패로 처리한다."""
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
