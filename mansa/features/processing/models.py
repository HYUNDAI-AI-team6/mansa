from dataclasses import dataclass
from typing import Any, Protocol


class DocumentLike(Protocol):
    """청킹이 문서에서 읽는 값. DocumentService의 Document가 이 속성을 가진다.

    title은 확장자를 뺀 파일명(doc_name), filename은 title + ".pdf"(source), doc_type은 "tech"/"secure"다.
    """

    id: int
    title: str
    filename: str
    doc_type: str


@dataclass(frozen=True)
class Chunk:
    """ChromaDB에 저장할 청크 하나. metadata는 str·int·float·bool 값만 갖고 값이 없는 키는 두지 않는다."""

    text: str
    metadata: dict[str, Any]

    @property
    def chunk_id(self) -> str:
        """벡터 ID "{document_id}:p{page}:{chunk}"를 만든다. 예: "12:p51:0"."""
        meta = self.metadata
        return f"{meta['document_id']}:p{meta['page']}:{meta['chunk']}"


def base_metadata(document: DocumentLike, page: int, chunk: int) -> dict[str, Any]:
    """모든 청크가 가지는 필수 메타데이터를 만든다.

    page는 PDF 페이지 번호(1부터), chunk는 그 페이지 안의 순번(0부터)이다.
    """
    return {
        "source": document.filename,
        "page": page,
        "chunk": chunk,
        "document_id": document.id,
        "document_type": document.doc_type,
        "doc_name": document.title,
    }
