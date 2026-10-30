"""문서 처리 파이프라인 조립. IngestPipeline에 실제 단계 함수(추출·청킹·태그·임베딩)를 끼워 만든다. 앱과 확인 스크립트가 함께 쓴다."""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from features.processing.adapters import extract_content
from features.processing.chunker import chunk
from features.processing.indexer import Indexer
from features.processing.pipeline import DocumentStore, IngestError, IngestPipeline, IngestSteps

logger = logging.getLogger(__name__)

ModelNames = Callable[[], Sequence[str]]
Vocabularies = Callable[[], Any]
Tagger = Callable[[Sequence[Any], Any], list]


def registered_model_names() -> list[str]:
    """기준정보(설비 모델 CSV)에 등록된 모델 이름을 읽는다. 부를 때마다 파일을 새로 읽는다."""
    from features.master.equipment import EquipmentModelService

    return [model.name for model in EquipmentModelService().list_models()]


def make_chunk_step(model_names: ModelNames = registered_model_names) -> Callable[[Any, Any], list]:
    """(문서, 추출 결과)를 받는 청킹 단계를 만든다. 기술 문서일 때만 처리할 때마다 모델 목록을 읽는다.

    앱을 켤 때 목록을 고정하지 않아서 CSV를 고치면 다음 문서부터 반영된다. 안전 문서는 모델을 쓰지
    않으므로 목록을 읽지 않고, 그래서 CSV에 문제가 있어도 안전 문서 처리는 영향이 없다.
    목록을 읽을 수 없으면 model 없이 저장하지 않고 실패로 처리한다(조용히 모델 필터에 안 걸리는
    청크가 쌓이는 것을 막는다). 목록이 비어 있으면 처리는 계속하되 경고를 남긴다.
    """

    def chunk_step(document: Any, content: Any) -> list:
        if document.doc_type != "tech":
            return chunk(document, content)
        try:
            names = list(model_names())
        except Exception as exc:
            logger.exception("could not read the equipment model list")
            raise IngestError("기준정보의 설비 모델 목록을 읽을 수 없어요") from exc
        if not names:
            logger.warning("no equipment models registered; tech chunks will have no model")
        return chunk(document, content, names)

    return chunk_step


def build_vocabulary():
    """태그로 쓸 수 있는 표준 이름 사전을 분류표 파일에서 새로 읽어 만든다. 분류표는 읽기만 한다."""
    from features.master.taxonomy import TaxonomyService
    from features.processing.tagger import Vocabulary

    return Vocabulary.from_taxonomy(TaxonomyService.from_directory())


def make_tag_step(vocabulary: Vocabularies = build_vocabulary, tagger: Tagger | None = None) -> Callable[[list], list]:
    """청크 목록에 부위·작업 태그를 붙이는 단계를 만든다.

    사전은 호출할 때마다 읽어서, 관리자가 분류표를 고치면 다음 업로드부터 반영된다. 사전을 읽지 못하거나
    태그 생성이 실패하면 예외가 파이프라인에 전달되고, 파이프라인은 태그 없이 계속 진행한다.
    tagger는 테스트에서 바꿔 끼우며, 기본은 features.processing.tagger.tag(LLM을 부르는 유료 호출)이다.
    """

    def tag_step(chunks: list) -> list:
        run = tagger
        if run is None:
            from features.processing.tagger import tag as run
        return run(chunks, vocabulary())

    return tag_step


def build_steps(
    model_names: ModelNames = registered_model_names,
    embed=None,
    vocabulary: Vocabularies = build_vocabulary,
    tagger: Tagger | None = None,
) -> IngestSteps:
    """실제 단계 함수를 모은 IngestSteps를 만든다. embed를 주지 않으면 core.llm.embed를 쓴다."""
    if embed is None:
        from core import llm

        embed = llm.embed
    return IngestSteps(
        extract=extract_content,
        chunk=make_chunk_step(model_names),
        tag=make_tag_step(vocabulary, tagger),
        embed=embed,
    )


def build_ingest_pipeline(
    documents: DocumentStore, indexer: Indexer | None = None, steps: IngestSteps | None = None
) -> IngestPipeline:
    """실제 부품으로 IngestPipeline을 만든다.

    documents는 DocumentService처럼 get_document·set_status를 가진 객체다. indexer를 주지 않으면
    실제 ChromaDB를 쓰는 기본 Indexer이고, steps를 주지 않으면 build_steps()의 실제 단계다.
    """
    return IngestPipeline(documents, steps or build_steps(), indexer)
