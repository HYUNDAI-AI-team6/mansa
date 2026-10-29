from collections.abc import Callable
from itertools import zip_longest
from typing import Any
from features.retrieval.bm25 import bm25_rank
from features.retrieval.rrf import rrf_merge
from core.schemas import Evidence, Intent, ScoredChunk
from config import (
    BM25_TOP_K,
    CORPUS_PAGE_SIZE,
    EVIDENCE_TOP_N,
    MANUAL_COLLECTION,
    MANUAL_DOC_TYPE,
    RESULT_TOP_K,
    SAFETY_COLLECTION,
    SAFETY_DOC_TYPE,
    TAG_KEYS,
    TAG_TOP_K,
    VECTOR_TOP_K,
)

# Intent를 받아 검색어에 덧붙일 단어 목록을 돌려주는 함수의 타입
TermExpander = Callable[[Intent], list[str]]
# util.rag_query.search_chunks와 같은 모양의 함수 타입
VectorSearch = Callable[..., list[dict[str, Any]]]
# util.rag_query.get_chunks와 같은 모양의 함수 타입
ChunkGetter = Callable[..., list[dict[str, Any]]]

# 문서 종류·컬렉션 이름·검색 개수·태그 키는 환경변수로 바꿀 수 있다(config.py 에서 읽는다).

def default_safety_terms(intent: Intent, lookup: Callable[[str], list[str]] | None = None) -> list[str]:
    """안전 문서 검색에 덧붙일 기본 단어로 작업 부위와 작업 내용을 반환한다.

    모델 ID는 넣지 않는다. 안전 문서는 특정 모델이 아니라 작업·위치 기준으로 쓰여 있어
    "CR-100" 같은 값을 붙이면 검색이 오히려 흐려진다.
    lookup(보통 TaxonomyService.expand_query_terms)을 주면 관계표의 작업 위치·위험 유형 단어를 뒤에 더한다.
    작업이 없으면 lookup을 부르지 않는다.
    """
    terms = [*intent.parts, *([intent.task] if intent.task else [])]
    if lookup and intent.task:
        terms += lookup(intent.task)
    return terms

def build_safety_query(
    question: str, intent: Intent, expand_terms: TermExpander = default_safety_terms
) -> str:
    """질문 뒤에 보강 단어를 붙여 안전 문서 검색어를 만든다.

    빈 단어, 질문에 이미 들어 있는 단어, 중복 단어는 붙이지 않는다.
    expand_terms를 바꿔 넣으면 기준정보의 관계표 보강 함수를 쓸 수 있다. intent는 바꾸지 않는다.
    """
    extra: list[str] = []
    for term in expand_terms(intent):
        term = term.strip()
        if term and term not in question and term not in extra:
            extra.append(term)
    return " ".join([question.strip(), *extra])

def search_vector(
    query: str, search: VectorSearch, doc_type: str, collection: str, top_k: int = VECTOR_TOP_K
) -> list[dict[str, Any]]:
    """doc_type 벡터 DB의 collection에서 검색어와 뜻이 가까운 청크를 top_k개 찾아 가까운 순서로 반환한다.

    각 항목은 {"id", "text", "metadata", "distance"}이며 distance가 작을수록 가깝다.
    search에는 보통 util.rag_query.search_chunks를 넘긴다. 이 함수는 유료 임베딩 API와
    Chroma를 호출한다. 빈 검색어나 없는 컬렉션은 search가 ValueError로 알리고,
    접속 실패와 함께 그대로 호출자에게 전달한다. 결과가 없으면 빈 리스트다.
    """
    return search(query, doc_type, collection, top_k=top_k)

def load_corpus(
    get: ChunkGetter, doc_type: str, collection: str, page_size: int = CORPUS_PAGE_SIZE
) -> list[dict[str, Any]]:
    """doc_type 벡터 DB의 collection에 있는 청크를 모두 읽어 {"id", "text", "metadata"} 목록으로 반환한다.

    get에는 보통 util.rag_query.get_chunks를 넘긴다. Chroma만 호출하고 임베딩 API는 부르지 않는다.
    page_size개씩 나눠 읽고, 받은 개수가 page_size보다 적으면 끝난 것으로 본다.
    질문마다 부르면 느리므로 한 번 읽어 두고 재사용한다. 문서가 새로 올라오면 다시 불러야 반영된다.
    없는 컬렉션은 get이 ValueError로 알리며 그대로 전달한다.
    """
    corpus: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = get(doc_type, collection, limit=page_size, offset=offset)
        corpus.extend(page)
        if len(page) < page_size:
            return corpus
        offset += page_size

def search_bm25(
    query: str, corpus: list[dict[str, Any]], top_k: int = BM25_TOP_K
) -> list[tuple[str, float]]:
    """검색어 단어가 들어간 청크를 BM25 점수가 높은 순으로 top_k개 반환한다.

    항목은 (청크 ID, BM25 점수)다. 점수는 순서용이라 범위가 없으므로 ScoredChunk.score에 쓰지 않는다.
    검색어 단어가 하나도 없는 청크는 빠지며, corpus가 비어 있으면 빈 리스트다. 외부 호출은 없다.
    """
    return bm25_rank(query, [(chunk["id"], chunk["text"]) for chunk in corpus])[:top_k]

def chunk_tags(metadata: dict[str, Any]) -> set[str]:
    """청크 메타데이터의 태그 값을 모아 집합으로 반환한다. 태그가 없으면 빈 집합이다.
    
    part·task 값은 문자열 리스트나 쉼표로 구분한 문자열이다. 그 밖의 값과 빈 태그는 무시한다."""
    tags: set[str] =set()
    for key in TAG_KEYS:
        value = metadata.get(key)
        # 쉼표 문자열은 리스트 형식으로 바뀌기 전에 색인된 청크를 위해 남겨 둔다.
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            tags.update(tag.strip() for tag in value if isinstance(tag, str) and tag.strip())
    return tags

def rank_by_tags(
    intent: Intent, corpus: list[dict[str, Any]], top_k: int = TAG_TOP_K
) -> list[str]:
    """Intent의 부위·작업과 겹치는 태그가 많은 청크 ID를 순서대로 top_k개 반환한다.

    겹치는 태그가 하나도 없는 청크는 빠진다. 개수가 같으면 corpus 순서를 따른다.
    Intent에 부위·작업이 없으면 빈 리스트다. 외부 호출은 없다.
    """
    # 모델은 태그 비교가 아니라 where 필터로 거를 예정이라 부위·작업만 비교한다
    wanted = {*intent.parts, *([intent.task] if intent.task else [])}
    if not wanted:
        return []
    counts = [(chunk["id"], len(wanted & chunk_tags(chunk.get("metadata",{})))) for chunk in corpus]
    # 겹침 0개를 빼지 않으면 관계없는 청크도 RRF에서 순위 점수를 받는다
    ranked = sorted((item for item in counts if item[1] > 0), key=lambda item: item[1], reverse=True)
    return [chunk_id for chunk_id, _ in ranked[:top_k]]

def rank_ids(
    vector_hits: list[dict[str, Any]],
    bm25_hits: list[tuple[str, float]],
    tag_ids: list[str] | None = None,
) -> list[str]:
    """벡터 검색·BM25·태그 일치 결과의 순위를 RRF로 합쳐 청크 ID를 최종 순서대로 반환한다.

    여러 결과에서 순위가 높은 청크가 앞에 온다. RRF 점수는 순서를 정할 때만 쓰고 버린다.
    점수가 같으면 벡터 결과에 먼저 나온 청크가 앞선다. 결과가 모두 비면 빈 리스트다.
    tag_ids를 주지 않으면 벡터와 BM25만 합친다.
    """
    rankings = [[hit["id"] for hit in vector_hits], [chunk_id for chunk_id, _ in bm25_hits]]
    if tag_ids:
        rankings.append(tag_ids)
    return [chunk_id for chunk_id, _ in rrf_merge(rankings)]

def distance_to_similarity(distance: float) -> float:
    """Chroma 거리를 0~1 유사도로 바꾼다. 클수록 비슷하다."""
    # shortcut: OpenAI 임베딩은 길이가 1이라 제곱 L2 거리 d에서 코사인 유사도 = 1 - d/2로 계산한다, 실서버 값으로 확인한 뒤 확정한다
    return max(0.0, min(1.0, 1 - distance / 2))

def to_scored_chunks(
    ids: list[str],
    vector_hits: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    doc_type: str,
    top_k: int = RESULT_TOP_K,
)-> list[ScoredChunk]:
    """순서가 정해진 청크 ID를 앞에서 top_k개까지 ScoredChunk로 바꾼다.

    score는 벡터 유사도(0~1)이고, BM25로만 찾은 청크는 유사도를 모르므로 0.0이다.
    본문·메타데이터는 벡터 결과에 있으면 그것을, 없으면 corpus에서 가져온다.
    """
    by_id = {chunk["id"]: chunk for chunk in corpus}
    # corpus를 읽은 뒤 새로 올라온 청크는 벡터 결과에만 있어서 함께 넣는다
    by_id.update({hit["id"]: hit for hit in vector_hits})
    similarity = {hit["id"]: distance_to_similarity(hit["distance"]) for hit in vector_hits}
    return [
        ScoredChunk(
            chunk_id= chunk_id,
            text= by_id[chunk_id]["text"],
            # BM25·태그로만 찾은 청크는 0.0이라 is_sufficient 기준을 못 넘지만 merge_evidence는 순위대로 남긴다.
            score=similarity.get(chunk_id, 0.0),
            doc_type=doc_type,
            metadata=by_id[chunk_id].get("metadata", {}),
        )
        for chunk_id in ids[:top_k]
    ]

def search_manual(
        question: str, intent: Intent, search: VectorSearch, corpus: list[dict[str, Any]]
) -> list[ScoredChunk]:
    """매뉴얼·사양서 청크를 벡터 검색과 BM25로 찾아 RRF 순서의 ScoredChunk 목록으로 반환한다.

    corpus는 load_corpus(get, MANUAL_DOC_TYPE, MANUAL_COLLECTION)로 미리 읽어 둔 매뉴얼 청크다.
    search는 유료 임베딩 API와 Chroma를 호출하며 실패는 그대로 전달한다.
    intent의 부위·작업은 태그 일치 순위에 쓴다.
    """
    # shortcut: 청크 메타데이터에 모델 ID가 없어 모델 필터 없이 찾는다, 색인에 모델 ID가 들어가면 where로 거른다
    vector_hits = search_vector(question, search, MANUAL_DOC_TYPE, MANUAL_COLLECTION)
    bm25_hits = search_bm25(question, corpus)
    tag_ids = rank_by_tags(intent, corpus)
    ids = rank_ids(vector_hits, bm25_hits, tag_ids)
    return to_scored_chunks(ids, vector_hits, corpus, MANUAL_DOC_TYPE)

def search_safety(
    question: str,
    intent: Intent,
    search: VectorSearch,
    corpus: list[dict[str, Any]],
    expand_terms: TermExpander = default_safety_terms,
) -> list[ScoredChunk]:
    """안전 문서 청크를 보강한 검색어로 벡터 검색과 BM25로 찾아 RRF 순서의 ScoredChunk 목록으로 반환한다.

    검색어는 build_safety_query로 질문 뒤에 부위·작업 단어를 붙여 만든다.
    corpus는 load_corpus(get, SAFETY_DOC_TYPE, SAFETY_COLLECTION)로 미리 읽어 둔 안전 문서 청크다.
    search는 유료 임베딩 API와 Chroma를 호출하며 실패는 그대로 전달한다.
    """
    query = build_safety_query(question, intent, expand_terms)
    vector_hits = search_vector(query, search, SAFETY_DOC_TYPE, SAFETY_COLLECTION)
    bm25_hits = search_bm25(query, corpus)
    tag_ids = rank_by_tags(intent, corpus)
    ids = rank_ids(vector_hits, bm25_hits, tag_ids)
    return to_scored_chunks(ids, vector_hits, corpus, SAFETY_DOC_TYPE)

def merge_evidence(
    manual: list[ScoredChunk], safety: list[ScoredChunk], top_n: int = EVIDENCE_TOP_N
) -> Evidence:
    """매뉴얼·안전 문서 검색 결과를 각자의 순위(RRF) 그대로 번갈아 뽑아 상위 top_n개를 고른다.

    점수로 다시 정렬하지 않으므로 BM25·태그로만 찾은 청크(score 0.0)도 순위대로 남고,
    매뉴얼·안전 근거가 함께 들어간다. 한쪽이 모자라면 다른 쪽으로 채운다.
    같은 chunk_id는 먼저 나온 것 하나만 남긴다. 입력 리스트는 바꾸지 않는다.
    """
    picked: dict[str, ScoredChunk] = {}
    for pair in zip_longest(manual, safety):
        for chunk in pair:
            if chunk is not None and chunk.chunk_id not in picked:
                picked[chunk.chunk_id] = chunk
    return Evidence(chunks=list(picked.values())[:top_n])
