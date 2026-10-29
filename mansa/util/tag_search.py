from util.rag_ingest import Embedder, test_embed_with_openai
from util.rag_query import Chunk, search_chunks
from util.vector_upload import DocType


def build_tag_where(parts: list[str], task: str | None) -> dict | None:
    """부위·작업 태그로 Chroma where 조건을 만든다. 태그가 하나도 없으면 None(전체 검색)이다.

    부위끼리는 OR, 부위와 작업은 AND로 묶는다. 청크 메타데이터의 part·task는 문자열 리스트여야 하며
    $contains는 리스트 원소와 정확히 같은 값만 맞는다(copy 서버 1.0.0에서 확인, "로프"로 "메인 로프"는 안 걸림).
    쉼표 문자열로 저장된 태그는 걸리지 않는다. $or·$and는 조건이 2개 이상일 때만 만든다(chromadb 검증 규칙).
    """
    conditions = []
    if parts:
        part_conditions = [{"part": {"$contains": part}} for part in parts]
        conditions.append(part_conditions[0] if len(part_conditions) == 1 else {"$or": part_conditions})
    if task:
        conditions.append({"task": {"$contains": task}})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def search_tagged_chunks(
    query: str,
    doc_type: DocType,
    collection_name: str,
    parts: list[str],
    task: str | None,
    top_k: int = 5,
    embed: Embedder = test_embed_with_openai,
    search=search_chunks,
) -> list[Chunk]:
    """부위·작업 태그로 범위를 좁힌 뒤 질문과 의미가 가까운 청크를 top_k개 찾아 가까운 순서로 반환한다.

    각 항목은 search_chunks와 같은 {"id", "text", "metadata", "distance"}다.
    부위와 작업이 모두 있고 결과가 0건이면 작업 조건을 빼고 부위 조건만으로 한 번 더 찾는다.
    그래도 0건이면 빈 리스트다. 태그가 있는데 필터 없는 전체 검색으로 넘어가지는 않는다.
    부위·작업이 모두 없으면 필터 없이 컬렉션 전체에서 찾는다.

    질문 임베딩은 한 번만 만들어(유료 OpenAI API) 다시 찾을 때도 재사용하므로, Chroma는 최대 2번 호출한다.
    빈 질문과 top_k < 1은 임베딩 전에 ValueError를 낸다. 잘못된 doc_type·없는 컬렉션은 search가
    ValueError로 알리지만 임베딩을 만든 뒤라 API 호출 1회는 이미 쓴 상태다. search는 테스트용으로 바꿔 넣는다.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    vector = embed([query])

    def reuse(_texts: list[str]) -> list[list[float]]:
        """이미 만든 질문 임베딩을 그대로 돌려준다. 단계마다 임베딩 API를 다시 부르지 않기 위해 쓴다."""
        return vector

    wheres = [build_tag_where(parts, task)]
    if parts and task:
        wheres.append(build_tag_where(parts, None))
    for where in wheres:
        chunks = search(query, doc_type, collection_name, top_k=top_k, where=where, embed=reuse)
        if chunks:
            return chunks
    return []
