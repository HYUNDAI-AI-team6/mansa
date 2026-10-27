import csv
from collections.abc import Callable
from pathlib import Path
from typing import get_args

from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from config import LLM_API_KEY
from util.vector_upload import DocType, upload_embeddings

EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
# 임베딩 API 호출과 Chroma 업로드를 이 개수씩 나눠 처리한다.
BATCH_SIZE = 100

Embedder = Callable[[list[str]], list[list[float]]]
Unit = tuple[str, dict]  # (원문 텍스트, 출처 메타데이터)


def test_load_pdf(path: Path) -> list[Unit]:
    """PDF를 페이지 단위로 읽어 (텍스트, {"source", "page"}) 목록을 반환한다.

    텍스트가 없는 페이지는 건너뛴다. 스캔본처럼 추출 가능한 텍스트가 전혀 없으면 OCR을
    지원하지 않으므로 ValueError를 발생시킨다. page는 1부터 시작한다.
    """
    units = [
        (text, {"source": path.name, "page": number})
        for number, page in enumerate(PdfReader(path).pages, start=1)
        if (text := (page.extract_text() or "").strip())
    ]
    if not units:
        raise ValueError(f"no extractable text in {path.name} (scanned PDF is not supported)")
    return units


def test_load_csv(path: Path) -> list[Unit]:
    """CSV를 행 단위로 읽어 ("컬럼: 값" 줄 목록, {"source", "row"}) 목록을 반환한다.

    첫 줄을 헤더로 보고 값이 모두 빈 행은 건너뛴다. row는 헤더를 제외한 1부터의 번호다.
    UTF-8(BOM 포함)로 읽고, 실패하면 엑셀 한글 CSV에 흔한 CP949로 다시 읽는다.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp949")
    units = []
    for number, row in enumerate(csv.DictReader(text.splitlines()), start=1):
        lines = [f"{key}: {value}" for key, value in row.items() if key and value and value.strip()]
        if lines:
            units.append(("\n".join(lines), {"source": path.name, "row": number}))
    if not units:
        raise ValueError(f"no data rows in {path.name}")
    return units


def test_chunk_units(units: list[Unit]) -> list[tuple[str, str, dict]]:
    """읽은 단위를 청크로 나눠 (id, 텍스트, 메타데이터) 목록을 반환한다.

    id는 "파일명:p페이지:청크번호" 또는 "파일명:r행:청크번호"라서 같은 파일을 다시 올리면
    같은 id를 덮어쓴다. 다만 파일이 줄어들어 청크 수가 줄면 남는 옛 청크는 지워지지 않는다.
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = []
    for text, meta in units:
        key = f"p{meta['page']}" if "page" in meta else f"r{meta['row']}"
        for index, piece in enumerate(splitter.split_text(text)):
            chunks.append((f"{meta['source']}:{key}:{index}", piece, {**meta, "chunk": index}))
    return chunks


def test_embed_with_openai(texts: list[str]) -> list[list[float]]:
    """OpenAI 임베딩 API로 텍스트 목록을 벡터로 바꾼다. 유료 외부 API를 호출한다.

    LLM_API_KEY가 없으면 RuntimeError를 발생시킨다. API 실패는 그대로 전달된다.
    """
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not set; check mansa/.env")
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=LLM_API_KEY).embed_documents(texts)

def test_ingest_file(
    path: str | Path,
    doc_type: DocType,
    collection_name: str,
    embed: Embedder = test_embed_with_openai,
) -> int:
    """PDF 또는 CSV를 읽어 청킹·임베딩한 뒤 doc_type에 맞는 벡터 DB에 올리고 올린 청크 수를 반환한다.

    확장자가 .pdf/.csv가 아니거나 doc_type이 잘못되면 임베딩 API를 부르기 전에 ValueError를
    발생시킨다. BATCH_SIZE개씩 나눠 보내므로 중간에 실패하면 앞 배치는 이미 저장된 상태이며,
    같은 파일을 다시 올리면 같은 id를 덮어써서 복구된다. embed로 임베딩 함수를 바꿀 수 있다.
    """
    path = Path(path)
    loaders = {".pdf": test_load_pdf, ".csv": test_load_csv}
    if path.suffix.lower() not in loaders:
        raise ValueError(f"unsupported file type: {path.suffix!r}, expected one of {list(loaders)}")
    if doc_type not in get_args(DocType):
        raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(get_args(DocType))}")

    chunks = test_chunk_units(loaders[path.suffix.lower()](path))
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        texts = [text for _, text, _ in batch]
        upload_embeddings(
            doc_type, collection_name, [id_ for id_, _, _ in batch], embed(texts), texts,
            [meta for _, _, meta in batch],
        )
    return len(chunks)
