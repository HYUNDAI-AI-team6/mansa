"""문서 삭제 흐름: ChromaDB 청크 → 원본 PDF → MySQL 기록 순서로 지운다.

기록(MySQL 행)을 맨 마지막에 지우는 이유는, 중간에 실패해도 문서 목록에 문서가 남아 있어
사용자가 다시 삭제를 시도할 수 있게 하려는 것이다. 각 단계는 이미 지워진 상태에서 다시
실행해도 안전해야 한다(청크 삭제는 없는 것을 지워도 되고, PDF·기록 삭제는 없으면 False).
실제 삭제 함수(Indexer.remove_document, DocumentService.delete_pdf·delete_document_record)는
밖에서 주입한다.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class DeletionError(RuntimeError):
    """삭제하지 못했을 때 발생한다. 메시지는 사용자에게 보여도 되는 내용만 담는다.

    실패한 단계는 이미 지운 것을 되돌리지 않으므로 같은 문서를 다시 삭제하면 이어서 지운다.
    """


class DocumentBusyError(DeletionError):
    """문서가 처리 중이거나 이미 삭제 중이어서 지금은 삭제할 수 없을 때 발생한다."""


class DocumentLookup(Protocol):
    """DocumentService가 삭제 흐름에 제공해야 하는 기능."""

    def get_document(self, document_id: int) -> Any:
        """문서 기록을 반환한다. doc_type("tech"/"secure")과 filename이 필요하다."""


@dataclass
class DeletionSteps:
    """실제로 지우는 함수 모음. 순서대로 불린다."""

    remove_chunks: Callable[[str, int], None]  # (doc_type, document_id): ChromaDB 청크 삭제
    delete_pdf: Callable[[int], bool]  # 원본 PDF 삭제. 이미 없으면 False
    delete_record: Callable[[int], bool]  # MySQL 기록 삭제. 이미 없으면 False


@dataclass(frozen=True)
class DeletionResult:
    """삭제 결과. PDF나 기록이 이미 없었는지(이전 시도에서 지워졌는지)를 알려 준다."""

    document_id: int
    filename: str
    pdf_existed: bool
    record_existed: bool


class DocumentDeleter:
    """문서 한 건을 지운다."""

    # 같은 문서를 동시에 두 번 지우지 못하게 한다. 프로세스 안에서만 유효하다.
    _active: set[int] = set()
    _lock = threading.Lock()

    def __init__(
        self,
        documents: DocumentLookup,
        steps: DeletionSteps,
        is_processing: Callable[[int], bool] | None = None,
    ) -> None:
        """is_processing(document_id)이 True인 문서는 지우지 않는다.

        파이프라인이 지금 이 프로세스에서 처리 중인지를 알려 주는 함수다. 주지 않으면 처리 중
        검사를 하지 않는다. 상태 값(처리 중)이 아니라 실제 실행 여부로 판단하는 이유는, 앱이
        중간에 꺼져 상태만 '처리 중'으로 남은 문서도 삭제할 수 있어야 하기 때문이다.
        """
        self.documents = documents
        self.steps = steps
        self.is_processing = is_processing or (lambda document_id: False)

    def delete(self, document_id: int) -> DeletionResult:
        """청크 → PDF → 기록 순서로 지우고 결과를 반환한다.

        문서가 없으면 documents.get_document의 예외가 그대로 전달된다. 처리 중이거나 이미 삭제
        중이면 아무것도 지우지 않고 DocumentBusyError, 어느 단계든 실패하면 그 뒤 단계는
        실행하지 않고 DeletionError를 발생시킨다.
        """
        with self._lock:
            if document_id in self._active:
                raise DocumentBusyError("이미 삭제 중인 문서예요")
            self._active.add(document_id)
        try:
            return self._delete(document_id)
        finally:
            with self._lock:
                self._active.discard(document_id)

    def _delete(self, document_id: int) -> DeletionResult:
        """처리 중인지 확인한 뒤 세 단계를 순서대로 실행한다."""
        document = self.documents.get_document(document_id)
        if self.is_processing(document_id):
            raise DocumentBusyError("처리 중인 문서는 삭제할 수 없어요. 처리가 끝난 뒤 다시 시도해 주세요")
        self._step(
            "chunks", document_id, "검색 데이터를 지우지 못했어요. 잠시 후 다시 시도해 주세요",
            lambda: self.steps.remove_chunks(document.doc_type, document_id),
        )
        pdf_existed = self._step(
            "pdf", document_id, "원본 파일을 지우지 못했어요. 잠시 후 다시 시도해 주세요",
            lambda: self.steps.delete_pdf(document_id),
        )
        record_existed = self._step(
            "record", document_id, "문서 기록을 지우지 못했어요. 잠시 후 다시 시도해 주세요",
            lambda: self.steps.delete_record(document_id),
        )
        return DeletionResult(
            document_id, document.filename, bool(pdf_existed), bool(record_existed)
        )

    @staticmethod
    def _step(name: str, document_id: int, message: str, action: Callable[[], Any]) -> Any:
        """한 단계를 실행한다. 실패하면 원인은 서버 로그에만 남기고 사용자용 메시지로 바꿔 던진다."""
        try:
            return action()
        except Exception as exc:
            logger.exception("delete failed at %s: document_id=%s", name, document_id)
            raise DeletionError(message) from exc
