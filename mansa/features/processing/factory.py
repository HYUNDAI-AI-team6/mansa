"""문서 처리 파이프라인 조립. IngestPipeline에 실제 단계 함수를 끼워 만든다. 앱과 확인 스크립트가 함께 쓴다."""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from features.processing.adapters import extract_content
from features.processing.chunker import chunk
from features.processing.indexer import Indexer
from features.processing.pipeline import DocumentStore, IngestError, IngestPipeline, IngestSteps

logger = logging.getLogger(__name__)

ModelNames = Callable[[], Sequence[str]]


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


def keep_chunks(chunks: Sequence) -> list:
    """태그를 붙이지 않고 청크를 그대로 돌려준다. 태그 생성 함수가 들어오면 이것을 바꿔 끼운다."""
    return list(chunks)


def build_steps(model_names: ModelNames = registered_model_names, embed: Any = None) -> IngestSteps:
    """실제 단계 함수 모음을 만든다. embed를 주지 않으면 core.llm.embed(OpenAI, 유료)를 쓴다."""
    if embed is None:
        from core import llm

        embed = llm.embed
    return IngestSteps(
        extract=extract_content,
        chunk=make_chunk_step(model_names),
        tag=keep_chunks,
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
