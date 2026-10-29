"""문서 서비스가 던지는 예외. 사용자에게 보여줄 문구는 화면 쪽에서 만든다."""


class DuplicateDocumentError(Exception):
    """같은 파일 이름·문서 유형의 문서가 이미 등록되어 있다. document_id가 기존 문서의 ID다."""

    def __init__(self, document_id: int | None = None) -> None:
        super().__init__(f"document already exists (id={document_id})")
        self.document_id = document_id


class DocumentNotFoundError(Exception):
    """해당 ID의 문서가 없다."""

    def __init__(self, document_id: int) -> None:
        super().__init__(f"document not found (id={document_id})")
        self.document_id = document_id


class DocumentStorageError(Exception):
    """원본 PDF 파일을 저장하거나 지우지 못했다. 원인 예외는 __cause__에 남는다."""


class InvalidStatusTransition(Exception):
    """허용하지 않는 상태 변경이다. 처리 중에서만 완료·실패로 바꿀 수 있다."""

    def __init__(self, current: str, new: str) -> None:
        super().__init__(f"cannot change status from {current} to {new}")
        self.current = current
        self.new = new
