"""화면이 쓰는 문서 업로드·삭제 흐름. 등록 → 백그라운드 처리 시작, 삭제 순서 실행을 한 곳에 묶는다.

업로드는 문서를 등록해 ID를 바로 돌려주고, 처리(추출·청킹·태그·임베딩·저장)는 별도 스레드에서 한다. 처리가
몇 분 걸릴 수 있어서 화면을 붙잡아 두지 않는다. 결과는 문서 상태(PROCESSING → COMPLETED/FAILED)로 확인한다.
앱이 처리 도중 꺼지면 상태가 PROCESSING으로 남지만, 처리 중 검사는 이 프로세스의 실제 실행 여부를 보므로
그런 문서는 삭제할 수 있다.
"""

import logging
import threading
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Protocol

from features.processing.deletion import DeletionResult, DocumentDeleter

logger = logging.getLogger(__name__)

Spawn = Callable[[Callable[[], None]], None]


class Registrar(Protocol):
    """DocumentService가 업로드 흐름에 제공해야 하는 기능."""

    def register_document(self, source_path: str | Path, filename: str, doc_type: str, department_id: int) -> int:
        """PDF를 등록하고 새 문서 ID를 돌려준다."""


class Runner(Protocol):
    """IngestPipeline이 업로드 흐름에 제공해야 하는 기능."""

    def run(self, document_id: int) -> None:
        """문서 한 건을 처리한다. 실패는 문서 상태로 기록되고 예외로 나오지 않는다."""


def spawn_thread(task: Callable[[], None]) -> None:
    """작업을 백그라운드 스레드에서 실행한다. 앱이 꺼질 때 처리가 끝나기를 기다리지 않는다."""
    threading.Thread(target=task, name="ingest", daemon=True).start()


class DocumentWorkflow:
    """문서 업로드와 삭제. 실제 부품은 밖에서 주입한다."""

    def __init__(
        self, documents: Registrar, pipeline: Runner, deleter: DocumentDeleter, spawn: Spawn = spawn_thread
    ) -> None:
        """documents는 등록, pipeline은 처리, deleter는 삭제를 맡는다. spawn은 테스트에서 바꿔 끼운다."""
        self.documents = documents
        self.pipeline = pipeline
        self.deleter = deleter
        self._spawn = spawn

    def upload(self, source_path: str | Path, filename: str, doc_type: str, department_id: int) -> int:
        """PDF를 등록하고 처리를 시작한 뒤 문서 ID를 돌려준다. 처리 결과는 기다리지 않는다.

        등록 단계의 오류(DuplicateDocumentError, ValueError, DocumentStorageError)는 그대로 전달되고,
        이 경우 처리는 시작하지 않는다.
        """
        document_id = self.documents.register_document(source_path, filename, doc_type, department_id)
        self._spawn(lambda: self._process(document_id))
        return document_id

    def _process(self, document_id: int) -> None:
        """파이프라인을 실행한다. 스레드 안이라 어떤 예외도 밖으로 내보내지 않고 로그만 남긴다."""
        try:
            self.pipeline.run(document_id)
        except Exception:
            logger.exception("ingest could not run: document_id=%s", document_id)

    def delete(self, document_id: int) -> DeletionResult:
        """청크 → 원본 PDF → 문서 기록 순서로 지운다. 예외는 DocumentDeleter.delete와 같다."""
        return self.deleter.delete(document_id)


def build_workflow() -> DocumentWorkflow:
    """실제 부품(DocumentService, ChromaDB, 파이프라인)으로 업로드·삭제 흐름을 만든다. DB·외부 서비스에 연결하지는 않는다."""
    from features.documents.service import DocumentService
    from features.processing.deletion import DeletionSteps
    from features.processing.factory import build_ingest_pipeline
    from features.processing.indexer import Indexer
    from features.processing.pipeline import IngestPipeline

    documents = DocumentService()
    indexer = Indexer()
    deleter = DocumentDeleter(
        documents,
        DeletionSteps(indexer.remove_document, documents.delete_pdf, documents.delete_document_record),
        is_processing=IngestPipeline.is_active,
    )
    return DocumentWorkflow(documents, build_ingest_pipeline(documents, indexer), deleter)


@cache
def default_workflow() -> DocumentWorkflow:
    """앱 전체가 함께 쓰는 흐름. 처음 부를 때 한 번만 만든다."""
    return build_workflow()


__all__ = ["DocumentWorkflow", "build_workflow", "default_workflow", "spawn_thread"]
