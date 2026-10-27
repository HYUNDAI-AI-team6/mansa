from collections.abc import Callable
from typing import Any
from features.retrieval.bm25 import bm25_rank
from features.retrieval.rrf import rrf_merge
from core.schemas import Evidence, Intent, ScoredChunk

# Intent를 받아 검색어에 덧붙일 단어 목록을 돌려주는 함수의 타입
TermExpander = Callable[[Intent], list[str]]


def default_safety_terms(intent: Intent) -> list[str]:
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
VECTOR_TOP_K = 20

# util.rag_query.search_chunks와 같은 모양의 함수 타입
VectorSearch = Callable[..., list[dict[str, Any]]]


def search_safety_vector(
    query: str, search: VectorSearch, top_k: int = VECTOR_TOP_K
) -> list[dict[str, Any]]:
    """안전 문서 컬렉션에서 검색어와 뜻이 가까운 청크를 top_k개 찾아 가까운 순서로 반환한다.

    각 항목은 {"id", "text", "metadata", "distance"}이며 distance가 작을수록 가깝다.
    search에는 보통 util.rag_query.search_chunks를 넘긴다. 이 함수는 유료 임베딩 API와
    Chroma를 호출한다. 빈 검색어나 없는 컬렉션은 search가 ValueError로 알리고,
    접속 실패와 함께 그대로 호출자에게 전달한다. 결과가 없으면 빈 리스트다.
    """
    return search(query, SAFETY_DOC_TYPE, SAFETY_COLLECTION, top_k=top_k)

BM25_TOP_K = 20
CORPUS_PAGE_SIZE = 500

# util.rag_query.get_chunks와 같은 모양의 함수 타입
ChunkGetter = Callable[..., list[dict[str, Any]]]


def load_safety_corpus(
    get: ChunkGetter, page_size: int = CORPUS_PAGE_SIZE
) -> list[tuple[str, str]]:
    """안전 문서 컬렉션의 청크를 모두 읽어 (청크 ID, 본문) 목록으로 반환한다.

    get에는 보통 util.rag_query.get_chunks를 넘긴다. Chroma만 호출하고 임베딩 API는 부르지 않는다.
    page_size개씩 나눠 읽고, 받은 개수가 page_size보다 적으면 끝난 것으로 본다.
    질문마다 부르면 느리므로 한 번 읽어 두고 재사용한다. 문서가 새로 올라오면 다시 불러야 반영된다.
    없는 컬렉션은 get이 ValueError로 알리며 그대로 전달한다.
    """
    corpus: list[tuple[str, str]] = []
    offset = 0
    while True:
        page = get(SAFETY_DOC_TYPE, SAFETY_COLLECTION, limit=page_size, offset=offset)
        corpus.extend((chunk["id"], chunk["text"]) for chunk in page)
        if len(page) < page_size:
            return corpus
        offset += page_size


def search_safety_bm25(
    query: str, corpus: list[tuple[str, str]], top_k: int = BM25_TOP_K
) -> list[tuple[str, float]]:
    """검색어 단어가 들어간 안전 문서 청크를 BM25 점수가 높은 순으로 top_k개 반환한다.

    항목은 (청크 ID, BM25 점수)다. 점수는 순서용이라 범위가 없으므로 ScoredChunk.score에 쓰지 않는다.
    검색어 단어가 하나도 없는 청크는 빠지며, corpus가 비어 있으면 빈 리스트다. 외부 호출은 없다.
    """
    return bm25_rank(query, corpus)[:top_k]

def rank_safety_ids(
    vector_hits: list[dict[str, Any]], bm25_hits: list[tuple[str, float]]
) -> list[str]:
    """벡터 검색과 BM25 결과의 순위를 RRF로 합쳐 청크 ID를 최종 순서대로 반환한다.

    양쪽 모두에서 순위가 높은 청크가 앞에 온다. RRF 점수는 순서를 정할 때만 쓰고 버린다.
    점수가 같으면 벡터 결과에 먼저 나온 청크가 앞선다. 두 결과가 모두 비면 빈 리스트다.
    """
    rankings = [[hit["id"] for hit in vector_hits], [chunk_id for chunk_id, _ in bm25_hits]]
    return [chunk_id for chunk_id, _ in rrf_merge(rankings)]



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
