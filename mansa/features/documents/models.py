"""문서 서비스가 돌려주는 값. documents_info 테이블의 행을 화면·파이프라인이 쓰기 좋게 담는다."""

from dataclasses import dataclass, field
from datetime import datetime

DOC_TYPES = ("tech", "secure")
STATUS_PROCESSING = "PROCESSING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUSES = (STATUS_PROCESSING, STATUS_COMPLETED, STATUS_FAILED)


def title_of(filename: str) -> str:
    """파일 이름에서 확장자(.pdf)를 뺀 문서 이름을 돌려준다. 확장자가 없으면 그대로다. 대소문자는 구분하지 않는다."""
    return filename[:-4] if filename.lower().endswith(".pdf") else filename


@dataclass(frozen=True)
class DocumentRow:
    """목록에 보이는 문서 한 줄. 원본 PDF 경로는 담지 않는다(화면에 노출하지 않는다).

    filename은 확장자를 포함한 원래 파일 이름이고, title은 확장자를 뺀 이름(청크 doc_name)이다.
    chunk_count는 완료 때 기록되며 그 전이거나 DB에 컬럼이 없으면 None이다.
    """

    id: int
    title: str
    filename: str
    doc_type: str
    department_id: int | None
    department_name: str | None
    status: str
    chunk_count: int | None
    upload_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Document(DocumentRow):
    """파이프라인이 읽는 문서. file_path는 문서 ID로 계산한 원본 PDF 경로(문자열)이며 파일이 없을 수도 있다."""

    file_path: str


@dataclass(frozen=True)
class DocumentStatus:
    """처리 상태 조회 결과."""

    status: str
    chunk_count: int | None
    updated_at: datetime


@dataclass(frozen=True)
class DocumentSummary:
    """문서 현황. by_status와 by_type은 문서가 없어도 모든 키를 0으로 가진다."""

    total: int
    by_status: dict[str, int] = field(default_factory=lambda: dict.fromkeys(STATUSES, 0))
    by_type: dict[str, int] = field(default_factory=lambda: dict.fromkeys(DOC_TYPES, 0))
