"""청크를 ChromaDB에 저장·삭제하고 저장 결과를 확인한다."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

# 문서 유형별 컬렉션. 기술 문서 tech_docs, 안전 문서 safety_docs로 확정됐다.
COLLECTIONS = {"tech": "tech_docs", "secure": "safety_docs"}
# 질의응답팀의 util/rag_query.py가 (source, page, chunk)로 정렬하고 출처를 만든다.
REQUIRED_KEYS = ("source", "page", "chunk", "document_id", "document_type")
SCALAR_TYPES = (str, int, float, bool)

Upload = Callable[[str, str, list[str], list[list[float]], list[str], list[dict]], int]
CountStored = Callable[[str, int], int]
DeleteDocument = Callable[[str, int], None]


class IndexingError(RuntimeError):
    """저장한 청크 수가 예상과 다르는 등 색인 결과가 올바르지 않을 때 발생한다."""


class ChunkLike(Protocol):
    """색인할 청크가 갖춰야 하는 값. 장영균의 Chunk가 확정되면 그 필드에 맞춰 바꾼다."""

    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Record:
    """ChromaDB에 넣을 청크 하나. id는 "{document_id}:p{page}:{chunk}" 형식이다."""

    id: str
    text: str
    metadata: dict[str, Any]


def _default_upload(
    doc_type: str, collection: str, ids: list[str], vectors: list[list[float]],
    texts: list[str], metadatas: list[dict],
) -> int:
    """기존 util.vector_upload.upload_embeddings로 저장한다. 서버 설정이 필요해 호출 때 불러온다."""
    from util.vector_upload import upload_embeddings

    return upload_embeddings(doc_type, collection, ids, vectors, texts, metadatas)


def _default_count_stored(doc_type: str, document_id: int) -> int:
    """document_id로 저장된 청크 수를 센다. 컬렉션이 없으면 0이다."""
    from util.vector_upload import get_collection

    try:
        collection = get_collection(doc_type, COLLECTIONS[doc_type])
    except ValueError:
        return 0
    return len(collection.get(where={"document_id": document_id}, include=[])["ids"])


def _default_delete_document(doc_type: str, document_id: int) -> None:
    """document_id가 같은 청크를 모두 지운다. 컬렉션이 없으면 지울 것이 없으므로 그냥 끝낸다."""
    from util.vector_upload import get_collection

    try:
        collection = get_collection(doc_type, COLLECTIONS[doc_type])
    except ValueError:
        return
    collection.delete(where={"document_id": document_id})


def _check_required(meta: dict[str, Any], document_id: int, doc_type: str, label: str) -> None:
    """필수 키의 존재와 자료형, 문서 ID·유형 일치를 확인한다. 어긋나면 ValueError를 발생시킨다."""
    missing = [key for key in REQUIRED_KEYS if meta.get(key) is None]
    if missing:
        raise ValueError(f"{label}: missing metadata {missing}")
    if not isinstance(meta["source"], str) or not meta["source"]:
        raise ValueError(f"{label}: source must be a non-empty str")
    for key, minimum in (("page", 1), ("chunk", 0)):
        value = meta[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{label}: {key} must be an int >= {minimum}")
    if meta["document_id"] != document_id or meta["document_type"] != doc_type:
        raise ValueError(f"{label}: document_id/document_type does not match the document")


def _clean_metadata(meta: dict[str, Any], document_id: int, doc_type: str, label: str) -> dict:
    """청크 메타데이터를 검사하고 ChromaDB가 받는 값만 남겨 새 dict로 반환한다.

    None과 빈 문자열(공백뿐인 문자열 포함)은 값이 없는 것이므로 키를 뺀다. 나머지 값은
    str·int·float·bool만 허용하며 리스트·dict 같은 다른 형식은 ValueError를 발생시킨다.
    부위·작업 태그(part, task)는 쉼표로 이은 문자열이라 값이 있으면 그대로 통과한다.
    필수 키는 먼저 검사하므로 비어 있으면 뺄 수 없고 오류가 난다. 입력 dict는 바꾸지 않는다.
    """
    _check_required(meta, document_id, doc_type, label)
    cleaned: dict[str, Any] = {}
    for key, value in meta.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        elif isinstance(value, SCALAR_TYPES):
            cleaned[key] = value
        else:
            raise ValueError(f"{label}: metadata {key!r} has unsupported type {type(value).__name__}")
    return cleaned


class Indexer:
    """청크의 ChromaDB 저장·삭제·검증을 맡는다. 외부 호출은 생성자에서 바꿔 끼울 수 있다."""

    def __init__(
        self,
        upload: Upload | None = None,
        count_stored: CountStored | None = None,
        delete_document: DeleteDocument | None = None,
    ) -> None:
        """지정하지 않은 호출은 util.vector_upload를 쓰는 기본 구현으로 채운다."""
        self._upload = upload or _default_upload
        self._count_stored = count_stored or _default_count_stored
        self._delete_document = delete_document or _default_delete_document

    def prepare(
        self, document_id: int, doc_type: str, chunks: Sequence[ChunkLike]
    ) -> list[Record]:
        """청크를 저장용 Record로 바꾼다. 임베딩 API를 부르기 전에 호출해 잘못된 입력을 먼저 거른다.

        문서 ID·유형이 다르거나 필수 메타데이터가 없거나 같은 (page, chunk)가 두 번 나오면
        ValueError를 발생시킨다. 청크 순서는 유지한다.
        """
        if doc_type not in COLLECTIONS:
            raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(COLLECTIONS)}")
        records: list[Record] = []
        seen: set[str] = set()
        for index, chunk in enumerate(chunks):
            label = f"chunk #{index}"
            if not isinstance(chunk.text, str) or not chunk.text.strip():
                raise ValueError(f"{label}: text must be a non-empty str")
            meta = _clean_metadata(chunk.metadata, document_id, doc_type, label)
            record_id = f"{document_id}:p{meta['page']}:{meta['chunk']}"
            if record_id in seen:
                raise ValueError(f"{label}: duplicate chunk id {record_id}")
            seen.add(record_id)
            records.append(Record(record_id, chunk.text, meta))
        return records

    def save(self, doc_type: str, records: Sequence[Record], vectors: list[list[float]]) -> int:
        """Record와 같은 순서의 벡터를 해당 컬렉션에 저장하고 저장한 개수를 반환한다.

        벡터 수가 Record 수와 다르거나 벡터 길이가 서로 다르면 ValueError를 발생시키며 저장하지 않는다.
        같은 id는 덮어쓴다(upsert). 서버 접속 실패는 그대로 전달된다.
        """
        if len(vectors) != len(records):
            raise ValueError(f"got {len(vectors)} vectors for {len(records)} records")
        if len({len(vector) for vector in vectors}) > 1:
            raise ValueError("vectors have different dimensions")
        return self._upload(
            doc_type, COLLECTIONS[doc_type], [r.id for r in records], vectors,
            [r.text for r in records], [r.metadata for r in records],
        )

    def verify(self, doc_type: str, document_id: int, expected: int) -> None:
        """document_id로 저장된 청크 수가 expected와 같은지 확인한다. 다르면 IndexingError를 발생시킨다."""
        stored = self._count_stored(doc_type, document_id)
        if stored != expected:
            raise IndexingError(f"stored {stored} chunks but expected {expected}")

    def remove_document(self, doc_type: str, document_id: int) -> None:
        """document_id가 같은 청크를 ChromaDB에서 모두 지운다. 지울 청크가 없어도 오류가 아니다."""
        if doc_type not in COLLECTIONS:
            raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(COLLECTIONS)}")
        self._delete_document(doc_type, document_id)
