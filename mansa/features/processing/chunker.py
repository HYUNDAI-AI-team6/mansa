"""문서 유형에 따라 안전기준·기술사양서 청커로 나누는 진입점. IngestSteps.chunk에 연결한다."""

from collections.abc import Sequence

from features.processing.chunker_secure import chunk_secure
from features.processing.chunker_tech import chunk_tech
from features.processing.models import Chunk, DocumentLike
from features.processing.pdf_content import PdfContent


def chunk(document: DocumentLike, content: PdfContent, models: Sequence[str] | None = None) -> list[Chunk]:
    """추출 결과를 문서 유형(document.doc_type)에 맞는 청커로 나눠 청크 목록을 돌려준다.

    "secure"는 조항 단위로, "tech"는 모델·표 단위로 나눈다. models는 기술사양서의 모델 이름 목록이며
    안전기준에서는 쓰지 않는다. 파이프라인이 (문서, 추출 결과) 두 인자만 넘기므로, 목록은
    functools.partial(chunk, models=목록)으로 미리 묶어서 IngestSteps.chunk에 연결한다.
    알 수 없는 문서 유형이면 청킹을 시작하기 전에 ValueError를 발생시킨다.
    """
    if document.doc_type == "secure":
        return chunk_secure(document, content)
    if document.doc_type == "tech":
        return chunk_tech(document, content, models)
    raise ValueError(f"unknown doc_type: {document.doc_type!r}, expected 'tech' or 'secure'")
