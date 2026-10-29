"""PDF 한 개를 문서 처리 파이프라인으로 확인한다. 기본은 외부 서비스를 부르지 않고 추출·청킹·검사만 한다.

사용: cd mansa && PYTHONPATH=. uv run --locked python -m scripts.ingest_check <pdf 경로> --type tech|secure [--apply] [--keep]

--apply를 주면 임베딩 API(유료)를 호출하고 실제 ChromaDB에 임시 문서 ID로 저장해 개수를 확인한 뒤 지운다.
--keep을 같이 주면 지우지 않는다. 임시 문서 ID(--document-id)에 이미 청크가 있으면 아무것도 하지 않고 멈춘다.
"""

import argparse
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from features.processing.factory import (
    ModelNames,
    Tagger,
    build_ingest_pipeline,
    build_steps,
    registered_model_names,
)
from features.processing.indexer import IndexingError, Indexer
from features.processing.pipeline import STATUS_COMPLETED, IngestError, IngestSteps

# 실제 문서 ID와 겹치지 않도록 큰 값을 쓴다. 이 ID의 청크만 저장하고 지운다.
DEFAULT_DOCUMENT_ID = 999_999_999
PREVIEW_CHARS = 120
PREVIEW_COUNT = 3
Embed = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class LocalDocument:
    """DocumentService 없이 PDF 파일 하나로 만드는 문서. 파이프라인이 읽는 값만 가진다."""

    id: int
    title: str
    filename: str
    doc_type: str
    file_path: str


class LocalStore:
    """DocumentStore 대역. 문서 하나를 돌려주고 기록된 상태를 모아 둔다. DB에는 쓰지 않는다."""

    def __init__(self, document: LocalDocument) -> None:
        """확인할 문서 하나를 받는다."""
        self.document = document
        self.statuses: list[tuple[str, str | None, int | None]] = []

    def get_document(self, document_id: int) -> LocalDocument:
        """항상 같은 문서를 돌려준다."""
        return self.document

    def set_status(
        self, document_id: int, status: str, error: str | None = None, chunk_count: int | None = None
    ) -> None:
        """(상태, 오류 문구, 청크 수)를 기록해 둔다."""
        self.statuses.append((status, error, chunk_count))


def make_document(path: Path, doc_type: str, document_id: int) -> LocalDocument:
    """PDF 경로로 문서를 만든다. 제목은 확장자를 뺀 파일명이고 filename은 제목 + ".pdf"다."""
    return LocalDocument(document_id, path.stem, f"{path.stem}.pdf", doc_type, str(path))


def summarize(chunks: list) -> list[str]:
    """청크 수, 길이, 모델별 개수와 앞부분 미리보기를 한 줄씩 만든다."""
    lengths = [len(chunk.text) for chunk in chunks]
    models = Counter(chunk.metadata.get("model") for chunk in chunks)
    lines = [f"chunks: {len(chunks)} (length {min(lengths)}~{max(lengths)} chars)"]
    if any(models):
        counts = {name or "(no model)": count for name, count in models.items()}
        lines.append(f"models: {counts}")
    for chunk in chunks[:PREVIEW_COUNT]:
        meta = chunk.metadata
        preview = " ".join(chunk.text.split())[:PREVIEW_CHARS]
        lines.append(f"  p{meta['page']}#{meta['chunk']} {preview}")
    return lines


def _no_embed(texts: list[str]) -> list[list[float]]:
    """확인만 할 때 쓰는 자리 채움. 임베딩 API를 부르지 않는다."""
    raise RuntimeError("dry-run must not call the embedding API")


def run(
    path: Path,
    doc_type: str,
    apply: bool = False,
    keep: bool = False,
    document_id: int = DEFAULT_DOCUMENT_ID,
    model_names: ModelNames = registered_model_names,
    embed: Embed | None = None,
    indexer: Indexer | None = None,
    tagger: Tagger | None = None,
) -> list[str]:
    """PDF 한 개를 확인하고 결과를 한 줄씩 돌려준다. apply가 아니면 외부 서비스를 부르지 않는다."""
    document = make_document(path, doc_type, document_id)
    steps = build_steps(model_names, embed=embed if apply else _no_embed, tagger=tagger)
    indexer = indexer or Indexer()

    try:
        content = steps.extract(document.file_path)
        chunks = steps.chunk(document, content)
        if not chunks:
            return ["failed: no chunks were produced from the document"]
        records = indexer.prepare(document_id, doc_type, chunks)
    except IngestError as exc:
        return [f"failed: {exc}"]
    except ValueError as exc:
        return [f"failed: chunks do not pass the metadata check ({exc})"]

    low_text = [page.page_no for page in content.pages if page.is_low_text]
    lines = [f"pages: {content.page_count} (low-text pages: {low_text or 'none'})"]
    lines += summarize(chunks)
    lines.append(f"records ready for ChromaDB: {len(records)}")
    if not apply:
        lines.append("[dry-run] 외부 서비스는 부르지 않았어요. 저장까지 확인하려면 --apply를 주세요")
        return lines
    return lines + _apply(document, steps, indexer, keep)


def _tag_summary(chunks: list) -> str:
    """태그가 붙은 청크 수를 한 줄로 만든다. 태그는 일부 청크에만 붙는 것이 정상이다."""
    parts = sum(1 for chunk in chunks if chunk.metadata.get("part"))
    tasks = sum(1 for chunk in chunks if chunk.metadata.get("task"))
    return f"tags: part on {parts} of {len(chunks)} chunks, task on {tasks}"


def _has_chunks(indexer: Indexer, doc_type: str, document_id: int) -> bool:
    """이 문서 ID로 저장된 청크가 있는지 확인한다. Indexer.verify의 기대 개수 0으로 확인한다."""
    try:
        indexer.verify(doc_type, document_id, 0)
    except IndexingError:
        return True
    return False


def _apply(document: LocalDocument, steps: IngestSteps, indexer: Indexer, keep: bool) -> list[str]:
    """임시 문서 ID로 실제 저장을 돌려 보고 개수를 확인한 뒤(keep이 아니면) 지운다."""
    if _has_chunks(indexer, document.doc_type, document.id):
        return [f"stopped: document id {document.id} already has chunks in ChromaDB; nothing was changed"]
    store = LocalStore(document)
    tagged: list = []

    def watch_tags(chunks):
        """태그 단계의 결과를 보관해 둔다. 몇 개에 태그가 붙었는지 보여 주기 위해서다."""
        tagged[:] = steps.tag(chunks)
        return tagged

    build_ingest_pipeline(store, indexer, replace(steps, tag=watch_tags)).run(document.id)
    status, error, chunk_count = store.statuses[-1]
    if status != STATUS_COMPLETED:
        return [f"pipeline status: {status} ({error})"]
    lines = [f"pipeline status: {status} (chunk_count: {chunk_count})"]
    lines.append(_tag_summary(tagged))
    indexer.verify(document.doc_type, document.id, chunk_count)
    lines.append(f"stored in ChromaDB and counted: {chunk_count}")
    if keep:
        lines.append(f"kept in ChromaDB under document id {document.id}")
        return lines
    indexer.remove_document(document.doc_type, document.id)
    left = _has_chunks(indexer, document.doc_type, document.id)
    lines.append("removed test chunks" if not left else "WARNING: some test chunks are still in ChromaDB")
    return lines


def main() -> None:
    """명령줄에서 실행한다. --apply가 없으면 외부 서비스를 부르지 않는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="확인할 PDF 파일")
    parser.add_argument("--type", dest="doc_type", choices=["tech", "secure"], required=True)
    parser.add_argument("--apply", action="store_true", help="임베딩·저장까지 실제로 실행한다")
    parser.add_argument("--keep", action="store_true", help="저장한 청크를 지우지 않는다")
    parser.add_argument("--document-id", type=int, default=DEFAULT_DOCUMENT_ID)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    for line in run(args.pdf, args.doc_type, args.apply, args.keep, args.document_id):
        print(line)


if __name__ == "__main__":
    main()
