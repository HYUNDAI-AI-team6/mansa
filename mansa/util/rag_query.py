from typing import Any

from util.rag_ingest import Embedder, test_embed_with_openai
from util.vector_upload import DocType, get_collection

Chunk = dict[str, Any]


def search_chunks(
    query: str,
    doc_type: DocType,
    collection_name: str,
    top_k: int = 5,
    where: dict | None = None,
    embed: Embedder = test_embed_with_openai,
) -> list[Chunk]:
    """질문과 의미가 가까운 청크를 top_k개 찾아 가까운 순서로 반환한다.

    각 항목은 {"id", "text", "metadata", "distance"}이고 distance가 작을수록 가깝다.
    질문은 적재할 때와 같은 임베딩 모델로 변환해야 하며 기본 embed는 유료 OpenAI API를 호출한다.
    where는 메타데이터 조건이다. 예: {"source": "safety_guide.pdf"}.
    빈 질문, top_k < 1, 잘못된 doc_type, 없는 컬렉션은 임베딩 API를 부르기 전에 ValueError를 낸다.
    컬렉션이 비어 있거나 조건에 맞는 청크가 없으면 빈 리스트를 반환한다.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    collection = get_collection(doc_type, collection_name)
    result = collection.query(
        query_embeddings=embed([query]),
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return [
        {"id": id_, "text": text, "metadata": meta, "distance": distance}
        for id_, text, meta, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]


def get_chunks(
    doc_type: DocType,
    collection_name: str,
    where: dict | None = None,
    ids: list[str] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[Chunk]:
    """조건에 맞는 청크를 임베딩 호출 없이 그대로 가져온다. 각 항목은 {"id", "text", "metadata"}이다.

    where는 메타데이터 조건(예: {"source": "a.pdf"}, 여러 조건은 {"$and": [{...}, {...}]}),
    ids는 정확한 청크 id 목록이다. 결과는 파일명, 페이지 또는 행, 청크 번호 순으로 정렬한다.
    정렬은 가져온 limit개 안에서만 하므로 limit보다 많은 청크가 있으면 offset으로 나눠 읽는다.
    잘못된 doc_type, 없는 컬렉션, limit < 1, offset < 0은 ValueError를 낸다.
    """
    if limit < 1 or offset < 0:
        raise ValueError("limit must be at least 1 and offset must not be negative")
    collection = get_collection(doc_type, collection_name)
    result = collection.get(
        ids=ids, where=where, limit=limit, offset=offset, include=["documents", "metadatas"]
    )
    chunks = [
        {"id": id_, "text": text, "metadata": meta}
        for id_, text, meta in zip(result["ids"], result["documents"], result["metadatas"])
    ]
    return sorted(chunks, key=lambda c: _position(c["metadata"]))


def _position(meta: dict) -> tuple[str, int, int]:
    """청크 메타데이터를 (파일명, 페이지 또는 행 번호, 청크 번호) 정렬 키로 바꾼다."""
    return meta.get("source", ""), meta.get("page", meta.get("row", 0)), meta.get("chunk", 0)
