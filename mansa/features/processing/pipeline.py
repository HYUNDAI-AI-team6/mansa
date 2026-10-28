"""PDF 문서를 추출 → 청킹 → 태그·임베딩 → ChromaDB 저장 순서로 처리하는 파이프라인."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from features.processing.indexer import Indexer, Record

logger = logging.getLogger(__name__)

# 파이프라인이 기록하는 처리 상태 값. 문서는 등록할 때 이미 '처리 중'이라 그 상태는 기록하지 않는다.
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

BATCH_SIZE = 100
MAX_ERROR_LENGTH = 300


class IngestError(RuntimeError):
    """스캔본이나 청크가 없는 문서처럼 처리를 계속할 수 없는 문서 문제일 때 발생한다.

    메시지는 문서 상태의 실패 원인에 그대로 기록되므로 사용자에게 보여도 되는 내용만 담는다.
    """


class AlreadyProcessingError(RuntimeError):
    """같은 문서가 이미 처리 중일 때 발생한다."""


class DocumentStore(Protocol):
    """DocumentService가 파이프라인에 제공해야 하는 기능."""

    def get_document(self, document_id: int) -> Any:
        """문서 기록을 반환한다. doc_type("tech"/"secure")과 file_path(원본 PDF 경로)가 필요하다."""

    def set_status(
        self,
        document_id: int,
        status: str,
        error: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        """처리 상태와 실패 원인을 기록한다. 완료할 때는 저장한 청크 수(chunk_count)도 함께 받는다."""


@dataclass
class IngestSteps:
    """장영균이 만드는 단계 함수 모음. 실제 PdfExtractor·Chunker·태그·임베딩을 여기에 연결한다."""

    # PDF 경로 -> 본문·표 통합 추출 결과(PdfContent). 스캔본·열 수 없는 PDF는 예외로 알리며,
    # 사용자에게 보여도 되는 문구는 IngestError로 바꿔 던진다(연결하는 쪽에서 변환한다).
    extract: Callable[[str], Any]
    chunk: Callable[[Any, Any], list]  # (문서, 추출 결과) -> 청크 목록
    tag: Callable[[list], list]  # 청크 목록을 받아 태그가 붙은 청크 목록을 반환
    embed: Callable[[list[str]], list[list[float]]]  # core.llm.embed


class IngestPipeline:
    """문서 한 건을 처리하고 진행 상태를 기록한다."""

    # 같은 문서의 동시 실행을 막는다. 프로세스 안에서만 유효하다.
    _active: set[int] = set()
    _lock = threading.Lock()

    def __init__(
        self,
        documents: DocumentStore,
        steps: IngestSteps,
        indexer: Indexer | None = None,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        """batch_size개씩 임베딩하고 저장한다. indexer를 주지 않으면 기본 Indexer를 쓴다."""
        self.documents = documents
        self.steps = steps
        self.indexer = indexer or Indexer()
        self.batch_size = batch_size

    def run(self, document_id: int) -> None:
        """문서를 처리하고 상태를 '완료'로 바꾼다. 문서는 등록할 때 이미 '처리 중'이다.

        처리 중 오류가 나면 이미 저장한 청크를 지우고 상태를 '실패'로 기록한 뒤 끝난다.
        이 경우 예외를 다시 던지지 않으므로 호출자는 상태로 결과를 확인한다.
        같은 문서가 이미 처리 중이면 AlreadyProcessingError를 발생시킨다.
        """
        with self._lock:
            if document_id in self._active:
                raise AlreadyProcessingError(f"document {document_id} is already being processed")
            self._active.add(document_id)
        try:
            self._run_guarded(document_id)
        finally:
            with self._lock:
                self._active.discard(document_id)

    def _run_guarded(self, document_id: int) -> None:
        """실행 경계: 어떤 오류든 기록하고 실패 처리로 넘긴다. 구현 결함도 로그에 남는다."""
        doc_type: str | None = None
        try:
            document = self.documents.get_document(document_id)
            doc_type = document.doc_type
            stored_count = self._process(document_id, doc_type, document)
            self.documents.set_status(document_id, STATUS_COMPLETED, chunk_count=stored_count)
        except Exception as exc:
            logger.exception("ingest failed: document_id=%s", document_id)
            self._fail(document_id, doc_type, exc)

    def _process(self, document_id: int, doc_type: str, document: Any) -> int:
        """추출 → 청킹 → 태그 → 저장용 변환 → 임베딩·저장 → 저장 개수 확인을 순서대로 하고 저장한 청크 수를 반환한다."""
        content = self.steps.extract(document.file_path)
        chunks = self._tag(self.steps.chunk(document, content))
        if not chunks:
            raise IngestError("no chunks were produced from the document")
        # 임베딩 요금이 들기 전에 메타데이터 오류를 먼저 거른다.
        records = self.indexer.prepare(document_id, doc_type, chunks)
        self._embed_and_save(doc_type, records)
        self.indexer.verify(doc_type, document_id, len(records))
        return len(records)

    def _tag(self, chunks: list) -> list:
        """태그를 붙인다. 태그 단계가 실패하거나 청크 수가 달라진 결과를 주면 태그 없이 계속한다.

        태그는 부가 정보라 문서 처리를 멈추지 않는다. 결과의 청크 수가 입력과 다르면 청크가
        빠지거나 어긋났을 수 있어, 그 결과를 쓰지 않고 원래 청크로 진행한다.
        """
        try:
            tagged = self.steps.tag(chunks)
            if len(tagged) == len(chunks):
                return tagged
        except Exception:
            logger.warning("tagging failed; continuing without tags", exc_info=True)
            return chunks
        logger.warning(
            "tagging returned %d chunks for %d; continuing without tags", len(tagged), len(chunks)
        )
        return chunks

    def _embed_and_save(self, doc_type: str, records: list[Record]) -> None:
        """batch_size개씩 임베딩하고 바로 저장한다. 중간에 실패하면 앞 배치는 이미 저장된 상태다."""
        for start in range(0, len(records), self.batch_size):
            batch = records[start : start + self.batch_size]
            vectors = self.steps.embed([record.text for record in batch])
            self.indexer.save(doc_type, batch, vectors)

    def _fail(self, document_id: int, doc_type: str | None, exc: Exception) -> None:
        """저장된 청크를 정리하고 상태를 '실패'로 기록한다. 이 단계의 오류는 로그만 남긴다."""
        if doc_type is not None:
            try:
                self.indexer.remove_document(doc_type, document_id)
            except Exception:
                logger.exception("cleanup failed: document_id=%s", document_id)
        try:
            self.documents.set_status(document_id, STATUS_FAILED, _error_text(exc))
        except Exception:
            logger.exception("could not record failure: document_id=%s", document_id)


def _error_text(exc: Exception) -> str:
    """문서 상태에 남길 실패 원인을 만든다.

    IngestError는 사용자에게 보여도 되는 메시지라 그대로 쓴다. 그 밖의 예외는 메시지에 외부 API
    응답이나 인증 정보가 섞일 수 있어 예외 이름만 남기고, 자세한 내용은 서버 로그에서 확인한다.
    """
    if isinstance(exc, IngestError):
        return str(exc)[:MAX_ERROR_LENGTH]
    return f"{type(exc).__name__} (see server log)"
