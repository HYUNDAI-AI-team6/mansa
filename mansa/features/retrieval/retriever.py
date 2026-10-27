from collections.abc import Callable
from typing import Any
from features.retrieval.bm25 import bm25_rank
from features.retrieval.rrf import rrf_merge
from core.schemas import Evidence, Intent, ScoredChunk

# Intent를 받아 검색어에 덧붙일 단어 목록을 돌려주는 함수의 타입
TermExpander = Callable[[Intent], list[str]]


def default_safety_terms(intent: Intent) -> list[str]: # 정환님의 expand_query_terms가 생긴다면 바꾸기
    """안전 문서 검색에 덧붙일 기본 단어로 작업 부위와 작업 내용을 반환한다.

    모델 ID는 넣지 않는다. 안전 문서는 특정 모델이 아니라 작업·위치 기준으로 쓰여 있어
    "CR-100" 같은 값을 붙이면 검색이 오히려 흐려진다.
    shortcut: 위험 단어(넘어짐·끼임 등) 보강이 없다, 기준정보의 expand_query_terms가 생기면 그 함수로 바꾼다.
    """
    return [*intent.parts, *([intent.task] if intent.task else [])]


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

SAFETY_DOC_TYPE = "secure"
SAFETY_COLLECTION = "safety_docs"
MANUAL_DOC_TYPE = "tech"
# shortcut: 매뉴얼 컬렉션 이름이 정해지지 않아 임시 이름을 쓴다, 올린 컬렉션 이름을 받으면 바꾼다
MANUAL_COLLECTION = "manual_docs"
VECTOR_TOP_K = 20

# util.rag_query.search_chunks와 같은 모양의 함수 타입
VectorSearch = Callable[..., list[dict[str, Any]]]


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

BM25_TOP_K = 20
CORPUS_PAGE_SIZE = 500

# util.rag_query.get_chunks와 같은 모양의 함수 타입
ChunkGetter = Callable[..., list[dict[str, Any]]]


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

def rank_ids(
    vector_hits: list[dict[str, Any]], bm25_hits: list[tuple[str, float]]
) -> list[str]:
    """벡터 검색과 BM25 결과의 순위를 RRF로 합쳐 청크 ID를 최종 순서대로 반환한다.

    양쪽 모두에서 순위가 높은 청크가 앞에 온다. RRF 점수는 순서를 정할 때만 쓰고 버린다.
    점수가 같으면 벡터 결과에 먼저 나온 청크가 앞선다. 두 결과가 모두 비면 빈 리스트다.
    """
    rankings = [[hit["id"] for hit in vector_hits], [chunk_id for chunk_id, _ in bm25_hits]]
    return [chunk_id for chunk_id, _ in rrf_merge(rankings)]

RESULT_TOP_K =20

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
    by_id.update({hit["id"]: hit for hit in vector_hits})
    similarity = {hit["id"]: distance_to_similarity(hit["distance"]) for hit in vector_hits}
    return [
        ScoredChunk(
            chunk_id= chunk_id,
            text= by_id[chunk_id]["text"],
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
    intent는 아직 쓰지 않는다.
    """
    # shortcut: 청크 메타데이터에 모델 ID가 없어 모델 필터 없이 찾는다, 색안에 모델 ID가 들어가면 where로 거른다
    vector_hits = search_vector(question, search, MANUAL_DOC_TYPE, MANUAL_COLLECTION)
    bm25_hits = search_bm25(question, corpus)
    return to_scored_chunks(rank_ids(vector_hits, bm25_hits), vector_hits, corpus, MANUAL_DOC_TYPE)

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
    return to_scored_chunks(rank_ids(vector_hits, bm25_hits), vector_hits, corpus, SAFETY_DOC_TYPE)


EVIDENCE_TOP_N = 8

def merge_evidence(
    manual: list[ScoredChunk], safety: list[ScoredChunk], top_n: int = EVIDENCE_TOP_N
) -> Evidence:
    """매뉴얼·안전 문서 검색 결과를 합쳐 점수가 높은 순으로 상위 top_n개를 고른다.

    같은 chunk_id가 여러 번 나오면 점수가 가장 높은 것 하나만 남긴다.
    점수가 같으면 manual, safety 순서로 먼저 들어온 청크가 앞선다. 입력 리스트는 바꾸지 않는다.
    """
    best: dict[str, ScoredChunk] = {}
    for chunk in [*manual, *safety]:
        kept = best.get(chunk.chunk_id)
        if kept is None or chunk.score > kept.score:
            best[chunk.chunk_id] = chunk
    ranked = sorted(best.values(), key=lambda c: c.score, reverse=True)
    return Evidence(chunks=ranked[:top_n])
