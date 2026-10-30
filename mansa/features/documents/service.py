"""문서 등록·조회·상태·삭제 함수. documents_info 테이블의 행과 원본 PDF 파일만 다룬다.

ChromaDB와 파이프라인은 부르지 않는다(삭제 흐름과 처리 연결은 박정환 담당이다). SQL은 util.mysql_connection의
fetch_all, execute로만 보내고 값은 항상 :이름 자리표시자로 넘긴다. execute가 새 행의 ID를 주지 않아서,
등록은 INSERT 뒤에 (파일 이름, 문서 유형)으로 ID를 다시 조회한다. 여러 문장을 한 트랜잭션으로 묶을 수 없으므로
중간에 실패하면 행과 파일을 직접 정리한다.
"""

import logging
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from features.documents.errors import (
    DocumentNotFoundError,
    DocumentStorageError,
    DuplicateDocumentError,
    InvalidStatusTransition,
)
from features.documents.models import (
    DOC_TYPES,
    STATUS_PROCESSING,
    STATUSES,
    Document,
    DocumentRow,
    DocumentStatus,
    DocumentSummary,
    title_of,
)
from features.documents.storage import PdfStorage

logger = logging.getLogger(__name__)

# 화면(ui/upload.py의 MAX_MB)과 같은 한도다. 화면 값을 바꾸면 여기도 같이 바꾼다.
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_FILENAME_CHARS = 255  # documents_info.filename은 varchar(255)다
MAX_ERROR_CHARS = 1000  # 실패 사유의 최대 길이(error_message는 varchar(1000)이다)
PDF_HEADER = b"%PDF-"
MYSQL_DUPLICATE_ENTRY = 1062
MYSQL_FOREIGN_KEY_FAILS = 1452
LIKE_ESCAPE = "!"

Fetch = Callable[[str, dict | None], list[dict]]
Run = Callable[[str, dict | None], int]

_SELECT = (
    "SELECT d.id, d.filename, d.document_type, d.department_id, p.name AS department_name, "
    "d.status, d.chunk_count, d.error_message, d.upload_at, d.updated_at "
    "FROM documents_info d LEFT JOIN departments p ON p.id = d.department_id"
)
_BY_NAME = "SELECT id FROM documents_info WHERE filename = :filename AND document_type = :doc_type"


def _fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    """util.mysql_connection.fetch_all로 조회한다. DB 연결이 필요해서 부를 때 불러온다."""
    from util.mysql_connection import fetch_all

    return fetch_all(sql, params)


def _execute(sql: str, params: dict | None = None) -> int:
    """util.mysql_connection.execute로 입력·수정·삭제한다. 영향받은 행 수를 돌려준다."""
    from util.mysql_connection import execute

    return execute(sql, params)


def normalize_filename(filename: str) -> str:
    """파일 이름을 NFC로 정규화하고 확장자를 소문자 .pdf로 맞춘 저장용 이름을 돌려준다.

    PDF가 아니거나, 경로 구분자·제어 문자가 들어 있거나, 이름이 비거나, 255자를 넘으면 ValueError를 발생시킨다.
    macOS에서 올린 한글(NFD)과 다른 곳에서 올린 같은 이름(NFC)이 다른 문서로 등록되지 않게 하려는 것이다.
    """
    if not isinstance(filename, str):
        raise ValueError("filename must be a str")
    name = unicodedata.normalize("NFC", filename).strip()
    if any(ch in name for ch in "/\\") or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ValueError("filename must not contain path separators or control characters")
    if not name.lower().endswith(".pdf"):
        raise ValueError("only PDF files can be registered")
    title = title_of(name).strip()
    if not title:
        raise ValueError("filename must not be empty")
    normalized = f"{title}.pdf"
    if len(normalized) > MAX_FILENAME_CHARS:
        raise ValueError(f"filename must be at most {MAX_FILENAME_CHARS} characters")
    return normalized


def check_pdf(path: str | Path) -> None:
    """업로드된 파일이 읽을 수 있고, 비어 있지 않고, %PDF- 로 시작하고, MAX_PDF_BYTES 이하인지 확인한다. 아니면 ValueError다."""
    file = Path(path)
    try:
        size = file.stat().st_size
        with file.open("rb") as handle:
            header = handle.read(len(PDF_HEADER))
    except OSError as exc:
        raise ValueError("cannot read the uploaded file") from exc
    if size == 0 or header != PDF_HEADER:
        raise ValueError("the uploaded file is not a PDF")
    if size > MAX_PDF_BYTES:
        raise ValueError(f"the uploaded file is larger than {MAX_PDF_BYTES // (1024 * 1024)}MB")


def _db_errno(exc: IntegrityError) -> int | None:
    """DB 드라이버가 준 MySQL 오류 번호를 꺼낸다. 알 수 없으면 None이다."""
    args = getattr(exc.orig, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def _check_id(document_id: int) -> None:
    """문서 ID가 1 이상의 정수가 아니면 ValueError를 발생시킨다."""
    if isinstance(document_id, bool) or not isinstance(document_id, int) or document_id < 1:
        raise ValueError(f"document_id must be an int >= 1, got {document_id!r}")


def _row_values(row: dict[str, Any]) -> dict[str, Any]:
    """조회한 행을 DocumentRow 필드 값으로 바꾼다. chunk_count·error_message가 NULL이면 None이다."""
    return {
        "id": int(row["id"]),
        "title": title_of(row["filename"]),
        "filename": row["filename"],
        "doc_type": row["document_type"],
        "department_id": row["department_id"],
        "department_name": row["department_name"],
        "status": row["status"],
        "chunk_count": row.get("chunk_count"),
        "upload_at": row["upload_at"],
        "updated_at": row["updated_at"],
        "error_message": row.get("error_message"),
    }


def _like(keyword: str) -> str:
    """검색어를 LIKE 패턴으로 만든다. 검색어의 %와 _는 글자 그대로 찾는다."""
    escaped = keyword.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", f"{LIKE_ESCAPE}%").replace("_", f"{LIKE_ESCAPE}_")
    return f"%{escaped}%"


class DocumentService:
    """documents_info의 행과 원본 PDF 파일을 다룬다. DB 호출과 저장소는 테스트에서 바꿔 끼울 수 있다."""

    def __init__(self, fetch: Fetch = _fetch_all, run: Run = _execute, storage: PdfStorage | None = None) -> None:
        """DB 조회·실행 함수와 파일 저장소를 받는다. 저장소를 주지 않으면 config.PDF_STORAGE_DIR를 쓴다."""
        self._fetch = fetch
        self._run = run
        self._storage = storage or PdfStorage()

    def register_document(self, source_path: str | Path, filename: str, doc_type: str, department_id: int) -> int:
        """업로드된 PDF를 등록하고 새 문서 ID를 돌려준다. 상태는 처리 중(PROCESSING)으로 시작한다.

        순서: 입력 검증 → 중복 조회 → 임시 파일 저장 → INSERT → 새 ID 조회 → 임시 파일을 {id}.pdf로 이름 변경.
        어느 단계에서 실패해도 행과 파일을 정리해서 반쯤 등록된 문서가 남지 않게 한다.
        유형·파일 형식·파일 이름·부서가 잘못되었거나 없는 부서면 ValueError, 같은 이름·유형의 문서가 있으면
        DuplicateDocumentError(기존 문서 ID 포함), 파일을 저장하지 못하면 DocumentStorageError를 발생시킨다.
        """
        if doc_type not in DOC_TYPES:
            raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(DOC_TYPES)}")
        name = normalize_filename(filename)
        if isinstance(department_id, bool) or not isinstance(department_id, int) or department_id < 1:
            raise ValueError("department_id is required and must be an int >= 1")
        check_pdf(source_path)

        params = {"filename": name, "doc_type": doc_type}
        existing = self._fetch(_BY_NAME, params)
        if existing:
            raise DuplicateDocumentError(int(existing[0]["id"]))

        temp = self._storage.save_temp(source_path, doc_type)
        try:
            document_id = self._insert(name, doc_type, department_id)
            try:
                self._storage.commit(temp, document_id, doc_type)
            except DocumentStorageError:
                self._remove_row(document_id)
                raise
        except BaseException:
            self._storage.discard(temp)
            raise
        return document_id

    def _insert(self, name: str, doc_type: str, department_id: int) -> int:
        """행을 넣고 새 ID를 돌려준다. 중복(UNIQUE)은 DuplicateDocumentError, 없는 부서(FK)는 ValueError로 바꾼다."""
        params = {"filename": name, "doc_type": doc_type}
        try:
            self._run(
                "INSERT INTO documents_info (filename, document_type, department_id, status) "
                "VALUES (:filename, :doc_type, :department_id, :status)",
                {**params, "department_id": department_id, "status": STATUS_PROCESSING},
            )
        except IntegrityError as exc:
            errno = _db_errno(exc)
            if errno == MYSQL_DUPLICATE_ENTRY:
                found = self._fetch(_BY_NAME, params)
                raise DuplicateDocumentError(int(found[0]["id"]) if found else None) from exc
            if errno == MYSQL_FOREIGN_KEY_FAILS:
                raise ValueError(f"unknown department: {department_id}") from exc
            raise
        rows = self._fetch(_BY_NAME, params)
        if not rows:
            raise RuntimeError("the inserted document could not be found")
        return int(rows[0]["id"])

    def _remove_row(self, document_id: int) -> None:
        """등록하다 실패한 행을 지운다. 지우지 못해도 원래 오류를 가리지 않도록 로그만 남긴다."""
        try:
            self._run("DELETE FROM documents_info WHERE id = :id", {"id": document_id})
        except Exception:
            logger.exception("could not remove the half-registered document %s", document_id)

    def _get_row(self, document_id: int) -> dict[str, Any]:
        """ID로 행을 조회한다. ID가 잘못되면 ValueError, 없으면 DocumentNotFoundError를 발생시킨다."""
        _check_id(document_id)
        rows = self._fetch(f"{_SELECT} WHERE d.id = :id", {"id": document_id})
        if not rows:
            raise DocumentNotFoundError(document_id)
        return rows[0]

    def get_document(self, document_id: int) -> Document:
        """파이프라인이 읽는 문서를 돌려준다. file_path는 문서 ID로 계산한 경로이며 파일이 없을 수도 있다."""
        values = _row_values(self._get_row(document_id))
        file_path = str(self._storage.path_for(values["id"], values["doc_type"]))
        return Document(**values, file_path=file_path)

    def get_status(self, document_id: int) -> DocumentStatus:
        """문서의 처리 상태, 청크 수, 마지막 변경 시각, 실패 사유를 돌려준다. 청크 수와 사유는 없으면 None이다."""
        values = _row_values(self._get_row(document_id))
        return DocumentStatus(values["status"], values["chunk_count"], values["updated_at"], values["error_message"])

    def list_documents(
        self,
        doc_type: str | None = None,
        department_id: int | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[DocumentRow]:
        """조건에 맞는 문서를 최근 올린 순서로 돌려준다. 조건을 주지 않으면 전체다.

        keyword는 파일 이름에 들어 있는 글자를 대소문자·악센트 구분 없이 찾는다(%와 _도 글자 그대로 찾는다).
        알 수 없는 문서 유형이나 상태는 ValueError를 발생시킨다.
        """
        if doc_type is not None and doc_type not in DOC_TYPES:
            raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(DOC_TYPES)}")
        if status is not None and status not in STATUSES:
            raise ValueError(f"unknown status: {status!r}, expected one of {list(STATUSES)}")
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if doc_type is not None:
            conditions.append("d.document_type = :doc_type")
            params["doc_type"] = doc_type
        if department_id is not None:
            conditions.append("d.department_id = :department_id")
            params["department_id"] = department_id
        if status is not None:
            conditions.append("d.status = :status")
            params["status"] = status
        if keyword and keyword.strip():
            conditions.append(
                f"d.filename COLLATE utf8mb4_0900_ai_ci LIKE :keyword ESCAPE '{LIKE_ESCAPE}'"
            )
            params["keyword"] = _like(keyword.strip())
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._fetch(f"{_SELECT}{where} ORDER BY d.upload_at DESC, d.id DESC", params)
        return [DocumentRow(**_row_values(row)) for row in rows]

    def summary(self) -> DocumentSummary:
        """전체·상태별·문서 유형별 문서 수를 돌려준다. 문서가 없는 상태·유형도 0으로 들어 있다."""
        rows = self._fetch(
            "SELECT document_type, status, COUNT(*) AS n FROM documents_info GROUP BY document_type, status", None
        )
        by_status = dict.fromkeys(STATUSES, 0)
        by_type = dict.fromkeys(DOC_TYPES, 0)
        for row in rows:
            count = int(row["n"])
            by_status[row["status"]] = by_status.get(row["status"], 0) + count
            by_type[row["document_type"]] = by_type.get(row["document_type"], 0) + count
        return DocumentSummary(total=sum(by_status.values()), by_status=by_status, by_type=by_type)

    def set_status(
        self, document_id: int, status: str, error: str | None = None, chunk_count: int | None = None
    ) -> None:
        """문서의 처리 상태를 바꾼다. 처리 중(PROCESSING)에서 완료·실패로만 바꿀 수 있다.

        이미 같은 상태이면 아무것도 바꾸지 않고 끝난다(결과를 다시 알려도 안전하다). 완료·실패에서 다른 상태로 바꾸려
        하면 InvalidStatusTransition을 발생시킨다. 상태는 UPDATE에 현재 상태 조건을 걸어 바꾸므로, 두 곳에서
        동시에 바꿔도 먼저 끝난 상태가 덮어써지지 않는다. 없는 문서는 DocumentNotFoundError, 알 수 없는 상태나
        잘못된 chunk_count·error는 ValueError다.

        chunk_count(완료 때 저장한 청크 수)와 error(실패 사유)는 documents_info에 컬럼이 생길 때까지 DB에 쓰지 않고
        로그에만 남긴다. error는 MAX_ERROR_CHARS까지만 남긴다.
        """
        _check_id(document_id)
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status!r}, expected one of {list(STATUSES)}")
        if chunk_count is not None and (isinstance(chunk_count, bool) or not isinstance(chunk_count, int) or chunk_count < 0):
            raise ValueError("chunk_count must be an int >= 0")
        if error is not None and not isinstance(error, str):
            raise ValueError("error must be a str")

        current = self._get_row(document_id)["status"]
        if current == status:
            return
        if current != STATUS_PROCESSING:
            raise InvalidStatusTransition(current, status)
        changed = self._run(
            "UPDATE documents_info SET status = :status WHERE id = :id AND status = :current",
            {"status": status, "id": document_id, "current": STATUS_PROCESSING},
        )
        if not changed:  # 읽은 뒤 다른 곳에서 먼저 바꿨다. 지금 상태로 판단한다.
            now = self._get_row(document_id)["status"]
            if now != status:
                raise InvalidStatusTransition(now, status)
            return
        logger.info(
            "document %s -> %s (chunk_count=%s, error=%s)",
            document_id, status, chunk_count, (error or "")[:MAX_ERROR_CHARS] or None,
        )

    def delete_pdf(self, document_id: int) -> bool:
        """문서의 원본 PDF를 지운다. 지웠으면 True, 이미 없으면 False다. DB 행이 이미 없어도 지울 수 있고 재시도해도 안전하다."""
        return self._storage.delete(document_id)

    def delete_document_record(self, document_id: int) -> bool:
        """documents_info의 행만 지운다. 지웠으면 True, 이미 없으면 False다.

        삭제 흐름의 마지막에 불러야 한다(ChromaDB 청크와 원본 PDF를 먼저 지운다). 행을 먼저 지우면 문서 ID를 잃어서
        나머지를 다시 시도할 수 없다.
        """
        _check_id(document_id)
        return self._run("DELETE FROM documents_info WHERE id = :id", {"id": document_id}) > 0
