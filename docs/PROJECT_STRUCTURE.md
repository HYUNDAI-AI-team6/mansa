# MANSA 프로젝트 구조 설명서

## 1. 문서 개요

본 문서는 MANSA 프로젝트의 디렉터리 구조와 각 폴더 및 파일의 역할을 정의한다.

팀원들이 공통된 프로젝트 구조를 이해하고, 기능 개발 시 적절한 위치에 코드를 작성할 수 있도록 하는 것이 목적이다.

### 프로젝트 개발환경

| 구분 | 기술 |
|---|---|
| 개발 언어 | Python 3.11.9 |
| UI 프레임워크 | Gradio |
| 패키지 관리 | uv |
| 가상환경 | .venv (uv로 생성 및 관리) |
| 데이터베이스 | Railway MySQL |
| ORM | SQLAlchemy |
| DB 드라이버 | PyMySQL |
| 환경변수 관리 | python-dotenv |
| 버전 관리 | Git / GitHub |
| 개발 도구 | VS Code |
| 지원 운영체제 | macOS / Windows |

### 개발 대상 기능

현재 프로젝트에서는 다음 6가지 기능을 개발한다.

1. 로그인 및 사용자 인증
2. 문서 업로드 및 관리
3. PDF 청킹 및 전처리
4. LLM 호출 및 태그 생성
5. 임베딩 생성 및 벡터 검색
6. 대시보드

안전기술서 자동 생성 기능은 현재 개발 범위에 포함하지 않는다.

---

## 2. 전체 프로젝트 구조

```text
mansa/
│
├── .github/                         # GitHub 협업 설정
│   ├── ISSUE_TEMPLATE/
│   │   └── custom.md                # Issue 작성 템플릿
│   └── PULL_REQUEST_TEMPLATE.md     # PR 작성 템플릿
│
├── .venv/                           # Python 가상환경 (Git 관리 제외)
│
├── .vscode/                         # VS Code 공통 설정
│   └── settings.json                # 인코딩 및 줄바꿈 설정
│
├── core/                            # 공통 핵심 기능
│   ├── __init__.py
│   ├── db.py                        # Railway MySQL 연결
│   └── models/                      # DB 테이블 모델
│       └── __init__.py
│
├── docs/                            # 프로젝트 개발 문서
│   ├── AGENTS.md                    # AI 개발 도구 관련 지침
│   ├── dev-stack-python.md          # Python 개발환경 및 기술 스택
│   ├── GIT_CONVENTION.md            # Git 협업 규칙
│   └── PROJECT_STRUCTURE.md         # 프로젝트 구조 설명서 (현재 문서)
│
├── features/                        # 기능별 비즈니스 로직
│   ├── __init__.py
│   │
│   ├── auth/                        # 로그인 및 인증
│   │   └── __init__.py
│   │
│   ├── documents/                   # 문서 업로드 및 관리
│   │   └── __init__.py
│   │
│   ├── processing/                  # PDF 청킹 및 전처리
│   │   └── __init__.py
│   │
│   ├── llm/                         # LLM 호출 및 태그 생성
│   │   └── __init__.py
│   │
│   ├── retrieval/                   # 임베딩 및 벡터 검색
│   │   └── __init__.py
│   │
│   └── dashboard/                   # 대시보드 데이터 처리
│       └── __init__.py
│
├── tests/                           # 테스트 코드
│   └── __init__.py
│
├── ui/                              # Gradio 화면 구성
│   ├── __init__.py
│   ├── login.py                     # 로그인 화면
│   ├── documents.py                 # 문서 관리 화면
│   └── dashboard.py                 # 대시보드 화면
│
├── .env.example                     # 환경변수 작성 예시
├── .gitattributes                   # Git 줄바꿈 설정
├── .gitignore                       # Git 관리 제외 파일 설정
├── app.py                           # Gradio 애플리케이션 실행
├── config.py                        # 환경변수 및 공통 설정
├── pyproject.toml                   # 프로젝트 의존성 관리
├── README.md                        # 프로젝트 소개 및 실행 방법
└── uv.lock                          # 의존성 버전 잠금
```

※ `.git/`은 Git 관리용 내부 디렉터리로, 위 구조에서는 생략했다.

※ `.venv/`는 각 팀원의 로컬 환경에 생성되며 GitHub에 업로드하지 않는다.

※ `features/` 하위 기능 폴더의 세부 파일은 개발 진행에 따라 추가한다.

---

## 3. 최상위 파일 설명

### 3.1 app.py

**역할: Gradio 애플리케이션 실행 진입점**

프로젝트 실행 시 가장 먼저 실행되는 Python 파일이다.

주요 역할은 다음과 같다.

- Gradio 애플리케이션 생성
- 사용자 화면 구성 요소 연결
- 애플리케이션 실행

실행 명령어:

```bash
uv run python app.py
```

`app.py`에는 복잡한 비즈니스 로직을 직접 작성하지 않는다.

실제 기능은 `features/`에서 구현하고, 화면 구성은 `ui/`에서 관리한다.

### 3.2 config.py

**역할: 프로젝트 공통 환경변수 관리**

`.env` 파일에 저장된 설정값을 읽어 Python 코드에서 사용할 수 있도록 한다.

관리 대상 예시:

- Railway MySQL 접속 정보
- LLM API 키
- LLM 모델 설정
- 기타 프로젝트 공통 환경변수

API 키나 DB 비밀번호를 Python 코드에 직접 작성하지 않는다.

### 3.3 pyproject.toml

**역할: Python 프로젝트 설정 및 의존성 관리**

다음 정보를 관리한다.

- 프로젝트 이름
- 프로젝트 버전
- Python 요구 버전
- 사용 패키지 목록

새로운 패키지가 필요하면 다음 명령어를 사용한다.

```bash
uv add 패키지명
```

`uv add`는 `pyproject.toml`과 `uv.lock`을 업데이트한다.

### 3.4 uv.lock

**역할: 패키지 의존성 버전 잠금**

팀원들이 일관된 패키지 환경을 구성할 수 있도록 의존성 해결 결과를 기록한다.

다음 명령어로 패키지 환경을 동기화한다.

```bash
uv sync --locked
```

`uv.lock`은 직접 수정하지 않고 uv 명령어로 관리한다.

### 3.5 .env.example

**역할: 환경변수 작성 양식 제공**

프로젝트 실행에 필요한 환경변수 목록과 형식을 안내한다.

예시:

```dotenv
DATABASE_URL=mysql+pymysql://username:password@host:port/database
LLM_API_KEY=your_api_key_here
```

실제 DB 비밀번호와 API 키는 `.env` 파일에 작성한다.

- `.env.example`: GitHub 업로드
- `.env`: GitHub 업로드 금지

### 3.6 .gitignore

**역할: Git 관리 대상에서 제외할 파일 지정**

주요 제외 대상:

- `.venv/`
- `.env`
- `__pycache__/`
- `*.pyc`
- 운영체제 및 개발 도구가 생성하는 임시 파일

### 3.7 .gitattributes

**역할: Git에서 텍스트 파일의 줄바꿈 규칙 관리**

macOS와 Windows의 줄바꿈 방식 차이로 발생하는 불필요한 변경을 줄인다.

텍스트 인코딩 자체를 변환하는 파일은 아니며, UTF-8 설정은 `.vscode/settings.json`에서 관리한다.

### 3.8 README.md

**역할: 프로젝트의 시작 안내 문서**

프로젝트를 처음 내려받은 팀원이 개발환경을 구성하고 프로그램을 실행할 수 있도록 안내한다.

프로젝트 소개, 설치 방법, 실행 방법 등을 작성한다.

---

## 4. core/ — 공통 핵심 기능

`core/`는 여러 기능에서 공통으로 사용하는 핵심 코드를 관리하는 폴더다.

특정 기능에만 사용되는 코드는 `core/`가 아닌 해당 `features/` 폴더에 작성하는 것을 원칙으로 한다.

### core/db.py

**역할: Railway MySQL 연결 관리**

SQLAlchemy와 PyMySQL을 사용해 Railway MySQL에 연결한다.

주요 역할:

- DB 엔진 생성
- DB 세션 관리
- DB 연결에 필요한 공통 설정 제공

로그인, 문서관리, 대시보드 등 DB를 사용하는 기능은 공통 DB 연결 코드를 재사용한다.

### core/models/

**역할: 데이터베이스 테이블 모델 정의**

SQLAlchemy ORM을 이용해 MySQL 테이블과 대응하는 Python 모델을 관리한다.

예상 모델 예시:

- 사용자 정보
- 업로드 문서 정보
- 문서 청크 정보
- 문서 태그 정보

위 항목은 예시이며 실제 테이블 구조는 DB 설계 과정에서 확정한다.

테이블 모델은 기능별로 파일을 분리할 수 있다.

### __init__.py

Python 패키지 구조를 구성하기 위한 파일이다.

현재는 빈 파일로 유지해도 되며, 필요한 경우 공통으로 사용할 객체를 노출하는 용도로 활용할 수 있다.

---

## 5. features/ — 기능별 비즈니스 로직

`features/`는 MANSA 프로젝트의 실제 기능을 구현하는 폴더다.

각 기능은 독립된 하위 폴더에서 개발한다.

### 5.1 features/auth/

**기능: 로그인 및 사용자 인증**

담당 역할:

- 사용자 로그인
- 사용자 인증
- 로그인 상태 확인
- 사용자 권한 확인

화면 코드는 `ui/login.py`에서 작성하고, 인증 처리 로직은 `features/auth/`에서 구현한다.

### 5.2 features/documents/

**기능: 문서 업로드 및 관리**

담당 역할:

- PDF 문서 업로드 처리
- 문서 정보 등록
- 업로드 문서 조회
- 문서 정보 수정 및 삭제

PDF 파일의 실제 저장 위치 및 저장 방식은 별도 설계에 따라 결정한다.

문서관리 기능은 PDF 전처리 기능과 연결될 수 있다.

### 5.3 features/processing/

**기능: PDF 청킹 및 전처리**

담당 역할:

- PDF 텍스트 추출
- 텍스트 정제
- 문서 청킹
- 청크 메타데이터 구성

PDF 문서를 LLM 및 임베딩 처리에 활용할 수 있도록 가공한다.

청크 크기, 오버랩, 추출 라이브러리 등은 개발 과정에서 결정한다.

### 5.4 features/llm/

**기능: LLM 호출 및 태그 생성**

담당 역할:

- LLM API 호출
- 프롬프트 구성
- 문서 및 청크 내용 분석
- 태그 생성
- LLM 응답 처리

API 키 등 민감한 설정값은 `config.py`를 통해 가져온다.

LLM 호출 로직은 다른 기능에서도 재사용할 수 있도록 구성한다.

### 5.5 features/retrieval/

**기능: 임베딩 및 벡터 검색**

담당 역할:

- 문서 청크 임베딩 생성
- 임베딩 데이터 관리
- 사용자 검색어 임베딩 생성
- 벡터 유사도 계산
- 관련 청크 검색

현재 공용 DB는 Railway MySQL을 사용한다.

임베딩 벡터의 저장 방식과 유사도 검색 방식은 추후 결정한다.

MySQL을 사용한다고 해서 별도 설계 없이 PostgreSQL의 pgvector를 사용할 수 있는 것은 아니다.

### 5.6 features/dashboard/

**기능: 대시보드 데이터 처리**

담당 역할:

- 대시보드에 필요한 데이터 조회
- 통계 데이터 계산
- 데이터 집계 및 가공
- UI에 전달할 결과 구성

대시보드 화면은 `ui/dashboard.py`에서 구현한다.

실제 표시할 통계 항목은 기능명세서와 개발 진행 상황에 따라 확정한다.

---

## 6. ui/ — Gradio 사용자 인터페이스

`ui/`는 Gradio를 이용한 화면 구성 코드를 관리한다.

화면 구성과 실제 데이터 처리 로직을 분리하는 것을 원칙으로 한다.

| 파일 | 역할 | 연결 기능 |
|---|---|---|
| `login.py` | 로그인 화면 | `features/auth/` |
| `documents.py` | 문서 업로드 및 관리 화면 | `features/documents/` |
| `dashboard.py` | 대시보드 화면 | `features/dashboard/` |

PDF 전처리, LLM, 임베딩 기능은 현재 별도 화면 파일을 생성하지 않는다.

해당 기능은 문서관리 등 다른 기능에서 호출하는 방식으로 연동할 수 있다.

### UI와 기능 로직의 분리

예를 들어 로그인 기능은 다음과 같이 구성한다.

```text
ui/login.py
    │
    │ 로그인 요청
    ▼
features/auth/
    │
    │ 사용자 정보 조회
    ▼
core/db.py
    │
    ▼
Railway MySQL
```

`ui/`에는 Gradio 컴포넌트 및 이벤트 연결 코드를 작성하고, 인증 및 데이터 처리 로직은 `features/`에서 구현한다.

---

## 7. docs/ — 프로젝트 문서

`docs/`는 팀원들이 공유하는 개발 관련 문서를 관리하는 폴더다.

| 파일 | 역할 |
|---|---|
| `AGENTS.md` | AI 개발 도구 사용 관련 지침 |
| `dev-stack-python.md` | Python 개발환경 및 기술 스택 안내 |
| `GIT_CONVENTION.md` | Git 브랜치, 커밋, PR 등 협업 규칙 |
| `PROJECT_STRUCTURE.md` | 프로젝트 디렉터리 구조 및 역할 설명 |

문서별 역할을 구분해 중복 작성을 최소화한다.

프로젝트 구조가 변경되면 `PROJECT_STRUCTURE.md`도 함께 수정한다.

---

## 8. tests/ — 테스트 코드

`tests/`는 프로젝트 기능의 정상 동작 여부를 검증하는 테스트 코드를 관리한다.

개발이 진행되면 다음과 같은 테스트를 추가할 수 있다.

- 로그인 및 인증 테스트
- 문서 업로드 테스트
- PDF 청킹 테스트
- LLM 응답 처리 테스트
- 임베딩 및 검색 테스트
- DB 연결 테스트

테스트 파일은 기능에 따라 분리한다.

실제 Railway DB나 유료 LLM API를 호출하는 테스트는 외부 서비스 의존성을 고려해 별도로 관리한다.

---

## 9. .github/ — GitHub 협업 설정

`.github/`는 GitHub에서 사용하는 협업 템플릿과 설정을 관리한다.

### ISSUE_TEMPLATE/

Issue 작성 시 사용할 템플릿을 관리한다.

기능 개발, 버그 수정, 개선 요청 등을 일정한 형식으로 등록할 수 있다.

### PULL_REQUEST_TEMPLATE.md

Pull Request 작성 시 사용할 템플릿이다.

코드 변경 내용과 테스트 결과 등을 팀원들이 일정한 형식으로 공유할 수 있도록 한다.

Git 브랜치 및 커밋 관련 세부 규칙은 `docs/GIT_CONVENTION.md`를 따른다.

---

## 10. 주요 기능 간 데이터 흐름

### 10.1 문서 등록 및 처리 흐름

아래는 현재 계획된 기능을 기준으로 작성한 개념적인 처리 흐름이다.

```text
[사용자]
    │
    ▼
[Gradio 문서 업로드 화면]
ui/documents.py
    │
    ▼
[문서 업로드 처리]
features/documents/
    │
    ▼
[PDF 텍스트 추출 및 청킹]
features/processing/
    │
    ├────────────────────┐
    ▼                    ▼
[LLM 태그 생성]      [임베딩 생성]
features/llm/        features/retrieval/
    │                    │
    └─────────┬──────────┘
              ▼
      [데이터 저장 처리]
          core/db.py
              │
              ▼
       [Railway MySQL]
```

실제 처리 순서와 저장 대상은 기능 구현 및 DB 설계에 따라 변경될 수 있다.

### 10.2 문서 검색 흐름

```text
[사용자 검색 요청]
        │
        ▼
[검색 요청 처리]
features/retrieval/
        │
        ▼
[검색어 임베딩 생성]
        │
        ▼
[벡터 유사도 검색]
        │
        ▼
[관련 문서 청크 조회]
        │
        ▼
[검색 결과 반환]
```

검색 결과를 어느 화면에서 제공할지는 UI 설계 과정에서 결정한다.

---

## 11. 팀원 개발 규칙

### 11.1 기능별 코드 작성 위치

새로운 기능을 구현할 때는 해당 기능의 `features/` 폴더에 코드를 작성한다.

예시:

- 로그인 인증 처리 → `features/auth/`
- PDF 텍스트 추출 → `features/processing/`
- LLM 태그 생성 → `features/llm/`
- 임베딩 생성 → `features/retrieval/`

### 11.2 공통 코드 관리

여러 기능에서 사용하는 코드는 공통 모듈로 관리한다.

예시:

- DB 연결 → `core/db.py`
- DB 모델 → `core/models/`
- 환경변수 → `config.py`

단, 특정 기능에서만 사용하는 코드를 불필요하게 `core/`로 이동하지 않는다.

### 11.3 UI와 비즈니스 로직 분리

Gradio 화면 코드는 `ui/`에 작성한다.

실제 기능 처리 코드는 `features/`에 작성한다.

`app.py`는 애플리케이션 실행 및 화면 연결 역할에 집중한다.

### 11.4 패키지 관리

새로운 패키지는 uv를 통해 추가한다.

```bash
uv add 패키지명
```

패키지를 추가하거나 변경한 경우 `pyproject.toml`과 `uv.lock`을 함께 커밋한다.

다른 팀원은 다음 명령어로 환경을 동기화한다.

```bash
uv sync --locked
```

### 11.5 환경변수 및 보안

다음 정보는 GitHub에 업로드하지 않는다.

- Railway MySQL 실제 접속 비밀번호
- LLM API 키
- 기타 인증 토큰 및 비밀정보

환경변수 이름이 추가되거나 변경되면 `.env.example`도 함께 수정한다.

### 11.6 새로운 파일 및 폴더 생성

개발 중 새로운 Python 파일이 필요하면 기존 기능 폴더 내부에 생성한다.

새로운 최상위 폴더가 필요한 경우에는 팀원들과 구조 변경 사항을 공유한 후 추가한다.

프로젝트 구조가 변경되면 본 문서도 함께 업데이트한다.

---

## 12. 폴더별 책임 요약

| 경로 | 주요 책임 |
|---|---|
| `app.py` | Gradio 실행 |
| `config.py` | 공통 환경설정 |
| `core/` | DB 연결 및 공통 핵심 기능 |
| `core/models/` | DB 테이블 모델 |
| `features/auth/` | 로그인 및 인증 |
| `features/documents/` | 문서 업로드 및 관리 |
| `features/processing/` | PDF 청킹 및 전처리 |
| `features/llm/` | LLM 호출 및 태그 생성 |
| `features/retrieval/` | 임베딩 및 벡터 검색 |
| `features/dashboard/` | 대시보드 데이터 처리 |
| `ui/` | Gradio 화면 |
| `tests/` | 테스트 코드 |
| `docs/` | 프로젝트 개발 문서 |
| `.github/` | GitHub 협업 설정 |

---

## 13. 프로젝트 구조 관리 원칙

MANSA 프로젝트는 다음 원칙을 기준으로 개발한다.

**1. 기능별 분리**

각 기능의 코드는 해당 `features/` 폴더에서 관리한다.

**2. 공통 코드 재사용**

DB 연결 및 공통 설정은 중복 작성하지 않고 재사용한다.

**3. UI와 기능 로직 분리**

Gradio 화면과 실제 데이터 처리 로직을 분리한다.

**4. 개발환경 통일**

Python 3.11.9와 uv를 사용해 일관된 개발환경을 유지한다.

**5. 확장 가능한 구조 유지**

새로운 기능은 기존 구조를 최대한 활용하면서 추가한다.

**6. 문서 최신화**

폴더 구조와 파일 역할이 변경되면 본 문서를 함께 수정한다.

---

본 문서는 프로젝트 초기 구조를 기준으로 작성되었으며, 개발 진행에 따라 수정될 수 있다.