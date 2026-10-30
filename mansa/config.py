import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

# 저장소 루트(이 파일이 mansa/ 안에 있으므로 한 단계 위). 상대 경로 환경변수의 기준이다.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _env_str(name: str, default: str) -> str:
    """환경변수 name 의 문자열 값을 돌려준다. 없거나 공백뿐이면 default 를 쓴다."""
    value = (os.getenv(name) or "").strip()
    return value or default


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    """환경변수 name 을 읽되 choices 안의 값만 허용한다. 오타를 켤 때 바로 잡으려는 것이다."""
    value = _env_str(name, default)
    if value not in choices:
        raise ValueError(f"{name} must be one of {list(choices)}, got {value!r}")
    return value


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """환경변수 name 을 쉼표로 나눈 문자열 묶음으로 읽는다(예: "part,task"). 없으면 default 를 쓴다."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    items = tuple(part.strip() for part in raw.split(","))
    if not all(items):
        raise ValueError(f"{name} must be comma-separated non-empty names, got {raw!r}")
    return items


def _env_int(
    name: str, default: int, minimum: int | None = None, maximum: int | None = None
) -> int:
    """환경변수 name 을 정수로 읽는다. 없거나 비어 있으면 default 를 쓴다.

    정수가 아니거나 minimum~maximum 범위를 벗어나면, 어느 변수가 문제인지 이름을 넣어 ValueError 를 낸다.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    too_small = minimum is not None and value < minimum
    too_big = maximum is not None and value > maximum
    if too_small or too_big:
        limit = (
            f"at least {minimum}" if maximum is None
            else f"at most {maximum}" if minimum is None
            else f"between {minimum} and {maximum}"
        )
        raise ValueError(f"{name} must be {limit}, got {value}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """환경변수 name 을 실수로 읽는다. 없으면 default 를 쓰고, 숫자가 아니거나 범위 밖이면 ValueError 를 낸다."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def _env_path(name: str, default: Path) -> Path:
    """환경변수 name 을 경로로 읽는다. 없으면 default 를 쓰고, 상대 경로는 저장소 루트 기준으로 바꾼다."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


DATABASE_URL = os.getenv("DATABASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "text-embedding-3-large"

# LLM 응답을 기다리는 최대 시간(초)과, 형식 오류·시간 초과 때 다시 시도할 횟수
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT") or 30)
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES") or 2)


TECH_CHROMA_HOST = os.getenv("TECH_CHROMA_HOST")
SECURE_CHROMA_HOST = os.getenv("SECURE_CHROMA_HOST")
# Railway 공개 도메인은 8000이 아니라 HTTPS(포트)로 접속한다. (8000은 컨테이너 내부 포트)
CHROMA_PORT = int(os.getenv("CHROMA_PORT"))

# ---- 아래는 환경마다 바꿀 수 있는 설정값이다. .env 에 없으면 오른쪽의 기본값을 쓴다. ----

# 문서 임베딩·청킹. 임베딩 모델을 바꾸면 벡터 차원이 달라져서(small 1536, large 3072) 이미 만든
# 컬렉션에는 넣거나 검색할 수 없다. 올리는 쪽과 검색하는 쪽이 같은 모델을 쓰므로 한 곳에서만 정한다.
EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "text-embedding-3-large")
CHUNK_SIZE = _env_int("CHUNK_SIZE", 800, minimum=1)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 100, minimum=0)
if CHUNK_OVERLAP >= CHUNK_SIZE:  # 겹침이 청크보다 크면 분할이 끝나지 않는다
    raise ValueError(
        f"CHUNK_OVERLAP ({CHUNK_OVERLAP}) must be smaller than CHUNK_SIZE ({CHUNK_SIZE})"
    )
BATCH_SIZE = _env_int("BATCH_SIZE", 100, minimum=1)

# 검색. 문서 종류(DOC_TYPE)는 어느 벡터 DB 를 쓸지 정한다(tech = 기술 DB, secure = 안전 DB).
# 컬렉션 이름은 문서를 올릴 때(rag_ingest 에 넘기는 이름)와 같아야 검색 결과가 나온다.
SAFETY_DOC_TYPE = _env_choice("SAFETY_DOC_TYPE", "secure", ("tech", "secure"))
SAFETY_COLLECTION = _env_str("SAFETY_COLLECTION", "safety_docs")
MANUAL_DOC_TYPE = _env_choice("MANUAL_DOC_TYPE", "tech", ("tech", "secure"))
MANUAL_COLLECTION = _env_str("MANUAL_COLLECTION", "tech_docs")
CORPUS_PAGE_SIZE = _env_int("CORPUS_PAGE_SIZE", 500, minimum=1)  # 말뭉치를 한 번에 읽는 크기
VECTOR_TOP_K = _env_int("VECTOR_TOP_K", 50, minimum=1) # BM25·태그 순위를 매길 후보 수
BM25_TOP_K = _env_int("BM25_TOP_K", 20, minimum=1)
RESULT_TOP_K = _env_int("RESULT_TOP_K", 20, minimum=1)
TAG_TOP_K = _env_int("TAG_TOP_K", 20, minimum=1)
EVIDENCE_TOP_N = _env_int("EVIDENCE_TOP_N", 12, minimum=1)  # 답변에 쓸 근거 청크 개수
# 청크 메타데이터에서 태그 값을 꺼낼 때 쓰는 키 이름(쉼표로 구분). 문서를 올릴 때 넣은 키와 같아야 태그 순위가 동작한다.
# 없는 키여도 오류는 없고 그 청크에 태그가 없는 것으로 본다.
TAG_KEYS = _env_tuple("TAG_KEYS", ("part", "task"))

# 답변 품질 기준
MAX_REGENERATIONS = _env_int("MAX_REGENERATIONS", 2, minimum=0)  # 근거 검사 실패 시 다시 생성하는 횟수
MIN_EVIDENCE_SCORE = _env_float("MIN_EVIDENCE_SCORE", 0.3, minimum=0.0, maximum=1.0)
DEFAULT_CONTACT = _env_str("DEFAULT_CONTACT", "안전관리팀")

# 회원 관리. 아이디·이름 칸은 users·admins 테이블의 varchar(50)이라 50보다 크게 잡을 수 없다.
MEMBER_MAX_LENGTH = _env_int("MEMBER_MAX_LENGTH", 50, minimum=1, maximum=50)
ADMIN_DEPT_LABEL = _env_str("ADMIN_DEPT_LABEL", "관리자")  # admins 테이블에는 부서가 없어 목록에 이 이름으로 보인다

# 평가 파일 위치. 기본은 저장소 루트의 eval/ 이고 실행 위치(cwd)와 상관없다.
# 상대 경로로 적으면 저장소 루트 기준이다. TESTSET_PATH, SAVE_DIR 는 따로 적지 않으면 EVAL_ROOT 를 따라간다.
EVAL_ROOT = _env_path("EVAL_ROOT", REPO_ROOT / "eval")
TESTSET_PATH = _env_path("TESTSET_PATH", EVAL_ROOT / "testsets" / "tech_qa.json")
SAVE_DIR = _env_path("SAVE_DIR", EVAL_ROOT / "save")

# 업로드한 원본 PDF를 두는 폴더. {PDF_STORAGE_DIR}/{doc_type}/{문서 id}.pdf 로 저장한다. 상대 경로는 저장소 루트 기준이다.
# 서버를 다시 시작할 때 이 폴더가 지워지는 환경이면 원본 PDF가 사라진다. 컴퓨터마다 따로 저장된다.
PDF_STORAGE_DIR = _env_path("PDF_STORAGE_DIR", REPO_ROOT / "mansa" / "data" / "documents")

