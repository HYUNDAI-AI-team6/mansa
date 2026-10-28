# MySQL 연동 사용법

Railway MySQL에 연결하고 SQL 쿼리를 보내는 함수의 사용법이다.
코드는 `mansa/util/mysql_connection.py`에 있고, 연결 엔진은 `mansa/core/db.py`의 공용 엔진을 쓴다.

## 준비

`mansa/.env.example`을 복사해 `mansa/.env`를 만들고 `DATABASE_URL`을 채운다.

```
DATABASE_URL=mysql+pymysql://사용자:비밀번호@호스트:포트/스키마
```

예: `mysql+pymysql://사용자:비밀번호@호스트:포트/스키마` (실제 값은 팀에서 공유받은 것을 `.env`에만 적는다)

- `호스트`와 `포트` 사이의 `host:` 같은 안내 문구를 남기지 않는다. 포트는 숫자여야 한다.
- 비밀번호에 `@`, `:`, `/`, `#`, `%`가 있으면 URL 인코딩한다(`@` → `%40`, `:` → `%3A`, `/` → `%2F`).
- `.env`는 Git에 올라가지 않는다. 비밀번호를 `.env.example`이나 코드에 적지 않는다.

```powershell
cd mansa
uv sync --locked
```

코드는 `mansa/` 폴더를 기준으로 import한다. `mansa/`에서 실행한다.

## 함수

```python
from util.mysql_connection import check_connection, fetch_all, execute
```

| 함수 | 용도 | 반환값 |
|---|---|---|
| `check_connection()` | 연결 확인(`SELECT 1`) | 성공하면 `True` |
| `fetch_all(sql, params=None)` | 조회(SELECT) | 컬럼명을 키로 한 `dict`의 리스트 |
| `execute(sql, params=None)` | 입력·수정·삭제(INSERT/UPDATE/DELETE), 테이블 생성·삭제 | 영향받은 행 수 |

세 함수 모두 마지막 인자 `engine`을 생략하면 `.env`의 `DATABASE_URL`로 만든 공용 엔진을 쓴다.

## 사용 예

```python
# 연결 확인
check_connection()  # True

# 입력
execute("INSERT INTO doc (id, name) VALUES (:id, :name)", {"id": 1, "name": "서버 점검 절차"})  # 1

# 조회
fetch_all("SELECT * FROM doc WHERE id = :id", {"id": 1})
# [{"id": 1, "name": "서버 점검 절차"}]

# 수정
execute("UPDATE doc SET name = :name WHERE id = :id", {"name": "서버 점검", "id": 1})  # 1

# 삭제
execute("DELETE FROM doc WHERE id = :id", {"id": 1})  # 1
```

## 규칙

- **값은 `:이름` 자리표시자와 `params`로 넘긴다.** 사용자 입력을 SQL 문자열에 직접 이어 붙이지 않는다. 이어 붙이면 SQL 인젝션이 생긴다.
  ```python
  fetch_all("SELECT * FROM doc WHERE name = :n", {"n": user_input})   # 올바름
  fetch_all(f"SELECT * FROM doc WHERE name = '{user_input}'")         # 금지
  ```
- 자리표시자는 값에만 쓸 수 있다. 테이블명이나 컬럼명은 자리표시자로 넘길 수 없으니, 외부 입력으로 만들지 않는다.
- `execute`는 쿼리 하나를 하나의 트랜잭션으로 실행한다. 성공하면 커밋하고, 예외가 나면 롤백한다. 여러 쿼리를 한 번에 커밋하는 기능은 없다.
- `execute`는 `WHERE` 없는 `UPDATE`/`DELETE`를 막지 않는다. 호출하는 쪽에서 조건을 반드시 넣는다.
- `fetch_all`은 조회만 하며 데이터를 바꾸지 않는다.

## 오류

접속이나 쿼리 실패는 값을 숨기지 않고 예외로 그대로 전달한다. 호출하는 쪽(UI, API)에서 잡아 사용자에게 안내한다.

| 오류 | 원인 |
|---|---|
| `RuntimeError: DATABASE_URL is not set` | `.env`에 `DATABASE_URL`이 없거나 비어 있음 |
| `ValueError: invalid literal for int() ...` | `DATABASE_URL`의 포트 자리가 숫자가 아님 |
| `Can't connect to MySQL server` | 호스트나 포트가 틀렸거나 Railway의 TCP 프록시가 꺼져 있음 |
| `Access denied for user` | 사용자나 비밀번호가 틀림 |
| `Unknown database` | 스키마 이름이 서버에 없음 |
| `IntegrityError` | 중복 키 등 제약 조건 위반. 롤백되어 기존 데이터는 그대로다 |

## 확인 방법

연결을 확인한다. `True`가 나오면 접속된 것이다.

```powershell
cd mansa
uv run --locked python -c "from util.mysql_connection import check_connection; print(check_connection())"
```

쿼리 함수의 동작은 단위 테스트로 확인한다. 실제 MySQL이 아니라 메모리 안의 SQLite로 실행하므로 서버가 없어도 된다.

```powershell
uv run --locked python -m unittest tests.test_mysql_connection -v
```

## 검증 범위

- 실서버(`testschema`)에서 연결 확인, 테이블 생성, 입력, 조회, 수정, 중복 키 오류와 롤백, 인젝션 문자열 처리, 한글 입출력을 확인했다.
- 테스트에 쓴 임시 테이블은 삭제했다.
- 수만 건 이상의 대량 입력, 동시 접속, 연결이 끊겼다 복구되는 경우는 확인하지 않았다.
- `core/models`의 ORM 모델은 아직 쓰지 않는다. 이 문서는 SQL을 직접 보내는 방식만 다룬다.
