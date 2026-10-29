"""기술 Q&A 서비스 조립. QAService에 실제 부품을 끼워 만든다. 앱과 확인 스크립트가 함께 쓴다."""

from collections.abc import Callable
from functools import partial

from config import MANUAL_COLLECTION, MANUAL_DOC_TYPE, SAFETY_COLLECTION, SAFETY_DOC_TYPE
from core import llm
from features.history.service import HistoryService
from features.history.store import MemoryHistoryStore
from features.master.equipment import EquipmentModelService
from features.master.taxonomy import TaxonomyService
from features.qa.answer_generator import AnswerGenerator
from features.qa.question_analyzer import QuestionAnalyzer
from features.qa.clarify_policy import RuleClarifyPolicy
from features.qa.service import QAService
from features.qa.source_service import SourceService
from features.retrieval.retriever import (
    ChunkGetter,
    HybridRetriever,
    VectorSearch,
    default_safety_terms,
    load_corpus,
)
from util.rag_query import get_chunks, search_chunks

def build_qa_service(
        search: VectorSearch = search_chunks,
        get: ChunkGetter = get_chunks,
        complete: Callable[..., dict] = llm.complete,
        history: HistoryService | None = None,
) -> QAService:
    """실제 부품으로 QAService를 만든다. 앱을 시작할 때 한 번만 부른다.

    생성할 때 Chroma에서 매뉴얼·안전 문서 청크를 모두 읽으므로(HybridRetriever) 시간이 걸리고,
    컬렉션이 없거나 서버에 접속할 수 없으면 예외가 그대로 전달된다.
    search·get은 보통 util.rag_query 함수를 쓰고, 확인용으로 로컬 Chroma 함수를 넣을 수 있다.
    complete는 질문 분석과 답변 생성이 함께 쓰는 LLM 호출 함수다.
    history를 주면 그 대화 기록에 저장하고(질문 기록 화면과 공유), 없으면 새 메모리 기록을 만든다.
    대화 기록은 메모리에 저장하므로 앱을 다시 켜면 사라진다.
    """
    taxonomy = TaxonomyService.from_directory()
    # 안전 문서 검색어에 관계표의 작업 위치·위험 유형 단어를 더한다
    expand_terms = partial(default_safety_terms, lookup=taxonomy.expand_query_terms)
    return QAService(
        analyzer=QuestionAnalyzer(EquipmentModelService(), taxonomy, complete),
        clarify_policy=RuleClarifyPolicy(taxonomy),
        retriever=HybridRetriever(search, get, expand_terms),
        generator=AnswerGenerator(complete),
        history=history or HistoryService(MemoryHistoryStore()),
    )


def build_source_service(get: ChunkGetter = get_chunks) -> SourceService:
    """근거 원문 창용 SourceService를 만든다. 매뉴얼·안전 문서 청크를 Chroma에서 모두 읽는다.
    
    컬렉션이 없거나 서버에 접속할 수 없으면 예외가 그대로 전달된다.
    """
    # shortcut: HybridRetriever와 별도로 Chroma를 한 번 더 읽는다, 청크가 많아져 시작이 느려지면 retriever의 청크를 공유한다
    chunks = [
        *load_corpus(get, MANUAL_DOC_TYPE, MANUAL_COLLECTION),
        *load_corpus(get, SAFETY_DOC_TYPE, SAFETY_COLLECTION)
    ]
    return SourceService(chunks)