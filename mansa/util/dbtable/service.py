from util.mysql_connection import execute, fetch_all

# departments.name, departments.description 컬럼이 varchar(50)이다.
MAX_LENGTH = 50


class DepartmentExistsError(ValueError):
    """같은 이름의 부서가 이미 등록되어 있을 때 발생한다."""


def register_department(name: str, description: str) -> None:
    """부서를 departments 테이블에 등록한다. 등록일자(created_at)는 DB 현재 시각이다.

    이름과 설명의 앞뒤 공백을 지운 뒤 저장한다. 이름이 비었거나 이름·설명이 50자를 넘으면
    ValueError, 같은 이름이 이미 있으면 DepartmentExistsError를 발생시키며 DB에는 쓰지 않는다.
    설명은 비어 있어도 되고 빈 문자열로 저장한다(컬럼이 NOT NULL).
    DB 접속·쿼리 실패는 그대로 전달된다. 이름 중복은 조회 후 입력하는 방식이라
    동시에 같은 이름을 등록하면 둘 다 저장될 수 있다(테이블에 이름 UNIQUE 제약이 없다).
    """
    name, description = name.strip(), description.strip()
    if not name:
        raise ValueError("name must not be empty")
    if len(name) > MAX_LENGTH or len(description) > MAX_LENGTH:
        raise ValueError(f"name and description must be at most {MAX_LENGTH} characters")
    if fetch_all("SELECT 1 FROM departments WHERE name = :name", {"name": name}):
        raise DepartmentExistsError(name)
    execute(
        "INSERT INTO departments (name, created_at, description) VALUES (:name, NOW(), :description)",
        {"name": name, "description": description},
    )
