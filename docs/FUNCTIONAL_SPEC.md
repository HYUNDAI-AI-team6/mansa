# MANSA 문서관리 기능명세서

> 기준일: 2026-10-28 / 기준 브랜치: `feat/pdf-extraction`
> 문서관리 영역과 다른 영역(질의응답·DB·화면)이 만나는 지점만 다룬다.
> 확정된 내용과 아직 확정되지 않은 내용을 구분해서 적었다. **"미확정"으로 표시된 항목은 추측해서 구현하지 않는다.**

## 0. 이 문서를 읽는 방법 (팀원·에이전트용)

- 문서관리 기능이나 그 연결 지점을 구현·수정하기 전에 이 문서를 먼저 읽는다.
- 이 문서와 실제 코드가 다르면 코드를 먼저 확인하고, 다른 점을 담당자에게 알린다. 문서에 맞추려고 코드를 임의로 바꾸지 않는다.
- 다른 담당자의 파일과 공용 DB 설정은 요청 없이 수정하지 않는다(§9).
- `AGENTS.md`, `docs/PROJECT_STRUCTURE.md`, `docs/dev-stack-python.md`의 규칙도 함께 따른다.

## 1. 범위

문서관리는 **PDF를 검색 가능한 데이터로 변환해 저장하는 데까지**를 맡는다.
사용자 질문 기반 검색, 근거 연결, RAG 답변 생성은 질의응답팀 담당이다.

```
문서관리: PDF 등록 → 텍스트·표 추출 → 청킹 → 메타데이터·태그 생성 → 임베딩 생성 → ChromaDB 저장 → 조회·삭제
질의응답: 질문 분석 → 질문 임베딩 → 벡터·태그·BM25 검색 → 통합 → 근거 검증 → GPT-4o-mini 답변 → 출처 표시
```

BM25는 질의응답팀이 ChromaDB에서 청크 원문을 읽어 검색 시점에 점수를 계산한다. 문서관리는 BM25 색인을 만들지 않는다.

## 2. 역할 분담

| 담당 | 문서관리 영역의 책임 |
|---|---|
| 장영균 | PDF 텍스트·표 추출, 청킹, `PageText`·`TableBlock`·`Chunk` 구조, 청크 메타데이터, `part`·`task` 태그 배치 생성, 임베딩 생성 함수(`core.llm.embed`), 문서 등록·중복 확인, 목록·현황·상태 조회, `DocumentService.set_status()`, 원본 PDF·MySQL 기록 삭제 함수, 단위 테스트 |
| 박정환 | `IngestPipeline.run()`, 전처리 함수 연결, ChromaDB 저장·삭제 연동(`Indexer`), 처리 상태 기록, 전체 삭제 흐름, 화면 연결(`ui/upload.py`, `ui/documents.py`, `ui/doc_view.py`, `ui/master.py`), 기준 차이 비교, 통합 테스트 |
| 질의응답팀 (이세림·강병훈) | 질문 분석, 질문 임베딩, 벡터·태그·BM25 검색(`util/rag_query.py`, `features/retrieval/`), 답변 생성, 출처 표시, 챗봇 UI. 청크 메타데이터를 읽어서 쓴다 |
| DB 담당 | MySQL·ChromaDB 서버, 스키마·컬렉션, 문서 ID·저장 규칙, 접근 방식 |

Gradio 화면 연결과 ChromaDB 저장 파이프라인은 장영균 담당이 아니다. 장영균은 화면과 파이프라인에서 호출할 수 있는 서비스·단계 함수까지 제공한다.

## 3. 확정된 정책

### 3.1 문서 유형

| 값 | 의미 |
|---|---|
| `tech` | 기술사양서 |
| `secure` | 안전기준 문서 |

`SPEC`, `SAFETY`, 한글 표기 등 다른 내부 값을 쓰지 않는다. 화면에는 "기술 문서"/"안전 문서"로 보이므로 서비스 경계에서 `tech`/`secure`로 변환한다. DB의 `documents.doc_type`이 삭제·저장 대상 ChromaDB 서버를 정한다.

### 3.2 문서 등록과 중복

- 버전 관리, 기존 문서 갱신, 별도 재처리 기능은 구현하지 않는다.
- 중복 판정 키는 `documents.title_hash`(UNIQUE)다. `title`(확장자를 뺀 원래 파일명)의 해시이고, **PDF 내용의 해시가 아니다.** 파일 내용 해시(SHA-256)는 쓰지 않는다.
- 해시 입력의 정확한 규칙(`doc_type` 포함 여부, 소문자 변환, 유니코드 NFC 정규화)은 DB 담당과 확정한다(§8). 서비스에서는 해시를 만드는 코드를 한 곳에만 두고, 규칙이 바뀌어도 그곳만 고친다.
- `register_document()` 규칙:
  1. 파일명에서 `title`과 해시를 만들어 기존 문서를 확인한다.
  2. 중복이면 PDF 저장과 MySQL 신규 등록 **전에** 거절한다.
  3. 중복된 기존 문서의 ID를 반환한다.
  4. 기존 문서는 자동 삭제하지 않는다.
  5. 사용자가 문서관리 화면에서 직접 삭제한 뒤 다시 업로드한다.
- 같은 이름에 내용이 다른 파일을 올리면 중복으로 거절된다. 이름이 다르고 내용이 같은 파일은 중복으로 잡지 못한다.
- 업로드 화면의 중복 안내는 박정환 담당이다.

### 3.3 처리 상태

- 서비스 인터페이스에서는 `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`를 쓴다.
- DB(`documents.status`, VARCHAR(10))에는 한글로 저장한다: `처리 중`, `완료`, `실패`. 서비스가 변환한다(PENDING·PROCESSING → `처리 중`, COMPLETED → `완료`, FAILED → `실패`). DB에서는 PENDING과 PROCESSING을 구분하지 않으므로 읽을 때는 `PROCESSING`으로 돌려준다. 화면 표시는 DB 값을 그대로 쓴다.
- 허용 전이(제안): `처리 중` → `완료`|`실패`. `완료`·`실패`는 끝 상태다. 이 외의 전이는 `InvalidStatusTransition`이다.
- `set_status(document_id, status, error=None, chunk_count=None)`: `COMPLETED`일 때 `chunk_count`(저장한 청크 수)를 `documents.chunk_count`에 기록한다.
- **실패 사유:** 현재 `documents` 테이블에는 사유를 저장할 컬럼이 없다. `error_message` 컬럼 추가를 DB 담당에게 요청한다(`mansa/migrations/`에 새 번호 파일). 추가되기 전에는 `error`를 저장하지 않고 서버 로그에만 남긴다. `error`는 1,000자로 자르고 API 키나 스택 트레이스는 담지 않는다.

### 3.4 삭제

실행과 연동은 박정환 담당이다. 순서는 아래와 같고, 중간에 실패하면 MySQL 기록을 남겨 재시도할 수 있게 한다. 각 단계는 재시도해도 안전해야 한다.

1. ChromaDB 청크·벡터 삭제 (박정환): `where={"document_id": id}`로 문서 단위 삭제
2. 원본 PDF 파일 삭제 (장영균이 함수 제공)
3. MySQL 문서 기록 삭제 (장영균이 함수 제공)

### 3.5 태그 생성 (`part`, `task`)

기존 `tags` 리스트 방식은 폐기했다.

- 모델 `gpt-4o-mini`(`config.LLM_MODEL`)로 여러 청크를 배치로 분석해 두 종류를 생성한다.
  - `part`: 설비 부위 (예: 브레이크, 캘리퍼)
  - `task`: 작업 종류 (예: 교체, 점검)
- 질의응답팀은 분류표의 부위·작업 표준 태그를 기준으로 읽는다. **분류표 목록을 받기 전에는 LLM이 본문에서 용어를 자유롭게 생성하고, 목록을 받으면 그 목록 안에서만 고르도록 확장한다**(`tag(chunks, vocabulary)`). 목록에 없는 용어는 태그에서 뺀다(§8).
- ChromaDB에는 쉼표로 구분한 문자열로 저장한다: `{"part": "브레이크, 캘리퍼", "task": "교체, 점검"}`. 구분자는 `", "`이고, 태그 안에는 쉼표를 넣지 않는다.
- 배치 결과는 **청크 ID로만** 대응시킨다. 모르는 ID, 중복 ID, 누락된 ID의 결과는 버린다.
- 문자열만 남기고 앞뒤 공백·빈 값·중복을 제거한다. 결과가 비면 해당 키를 **생략**한다. 빈 문자열은 저장하지 않는다.
- 원문에 근거한 태그만 생성한다. 임의로 만들어 넣지 않는다.
- 배치 하나가 실패해도 문서 처리는 중단하지 않고, 그 배치의 청크는 태그 없이 둔다. 함수 전체도 예외를 내지 않는다.

### 3.6 임베딩

- 모델 `text-embedding-3-large`, 차원 3072. 문서 청크와 질문 임베딩은 **같은 모델**이어야 한다.
- 공통 함수는 `core.llm.embed(texts: list[str]) -> list[list[float]]`이다(**아직 없음**). 입력과 같은 순서로 3072차원 벡터를 돌려준다. QA의 `Embedder` 타입(`Callable[[list[str]], list[list[float]]]`)과 같아서 `search_chunks(..., embed=embed)`에 그대로 넘길 수 있다.
- `LLM_API_KEY`가 없으면 `RuntimeError`, 빈 문자열이 있으면 `ValueError`, 빈 목록이면 `[]`, 응답 차원이 3072가 아니면 예외다. API 실패는 예외로 전달한다(임베딩 없이는 저장할 수 없다).
- `core/llm.py`와 `config.py`는 QA와 공유하는 파일이다. `embed`는 파일 끝에 추가하는 최소 변경으로 하고, 추가 전에 QA와 합의한다.
- **병합 시점 주의:** QA의 `util/rag_ingest.py`·`rag_query.py` 기본 임베딩은 `text-embedding-3-small`(1536차원)이다. 3072차원 컬렉션에 1536차원으로 질문하면 차원 불일치 오류가 난다. QA 쪽 기본값을 `core.llm.embed`로 바꾸는 시점을 QA와 맞춘다.
- 컬렉션은 처음 저장할 때 차원이 고정된다. 기존 `rag_ingest` 테스트 데이터(1536차원)가 남은 컬렉션에는 저장하지 않는다.

### 3.7 청킹 원칙

- 기술사양서는 **모델 단위**로 청크를 나눈다. 청크 하나에는 `model`을 하나만 둔다. 한 표에 여러 모델이 있으면 모델별로 나눈다. 모델에 속하지 않는 공통 본문은 `model` 키를 생략한다.
- 안전기준은 조항·절 구조를 보존해 나눈다.
- 표는 값과 헤더의 연결 관계가 유지되도록 텍스트로 바꾼다.
- **청크 본문에 모델명과 조항 번호를 포함한다.** QA의 BM25는 본문 텍스트만 보고, 메타데이터는 보지 않는다.
- 청크 한 건이 임베딩 입력 한도(8,191토큰)를 넘지 않게 길이를 제한한다.
- 본문 청크와 표 청크는 한 페이지 안에서 하나의 `chunk` 순번으로 이어서 매긴다.
- 신뢰도 낮은 표(`TableBlock.is_reliable=False`)를 청크로 만들지는 미확정이다.

## 4. 청크 메타데이터 계약

### 4.1 키

| 키 | 타입 | 대상 | 설명 |
|---|---|---|---|
| `source` | str | 전체 | PDF 파일명. `documents.title + ".pdf"`로 만든다 |
| `page` | int | 전체 | PDF 페이지 번호 (1부터) |
| `chunk` | int | 전체 | 해당 페이지 안에서의 청크 순번 (**0부터**, 임시 결정) |
| `document_id` | int | 전체 | MySQL `documents.id` |
| `document_type` | str | 전체 | `tech` 또는 `secure` |
| `doc_name` | str | 전체 | 출처에 표시할 문서명. **파일명에서 확장자를 뺀 값** = `documents.title` (예: `안전기준`) |
| `model` | str | `tech` | 차종·모델명. 청크당 하나. PDF 표기를 그대로 쓴다(§8) |
| `clause` | str | `secure` | 조항·절 번호 (예: `6.6.4.1.2`) |
| `section_title` | str | `secure` | 조항·절 제목. 선택 항목 |
| `part` | str | 태그 있을 때 | 부위 태그, 쉼표 구분 (§3.5) |
| `task` | str | 태그 있을 때 | 작업 태그, 쉼표 구분 (§3.5) |

- `source`, `page`, `chunk`의 키 이름과 자료형은 바꾸지 않는다. QA가 `(source, page, chunk)`로 정렬하고 출처를 구성한다.
- **값이 없는 키는 생략한다.** ChromaDB 메타데이터는 `None`을 저장할 수 없다. 값은 `str`, `int`, `float`, `bool`만 가능하고 리스트·dict는 저장할 수 없다.
- `department_id`는 ChromaDB 메타데이터에 넣지 않는다. 부서 정보는 MySQL(`documents.dept_id`)에서 `document_id`로 찾는다.
- 예전 키는 폐기했다: `product_model` → `model`, `section_number` → `clause`, `tags` → `part`·`task`.

### 4.2 청크 ID

벡터 ID는 `{document_id}:p{page}:{chunk}`다(예: `12:p51:0`). 같은 입력이면 같은 ID라서 다시 저장해도 덮어쓴다(upsert). `Chunk.chunk_id` 속성이 이 형식을 한 곳에서 만든다. 같은 문서의 `(page, chunk)`는 겹치지 않아야 한다.

## 5. 현재 구현 상태

위치는 모두 `mansa/features/processing/`이다. 테스트는 `mansa/`에서 아래 명령으로 실행한다.

```powershell
uv run --locked python -B -m unittest discover -s tests -v
```

| 기능 | 상태 | 비고 |
|---|---|---|
| 페이지별 텍스트 추출, 스캔본 판별 | 완료 | `pdf_text.py` |
| 표 추출, 숫자 복원, 표 신뢰도 표시 | 완료 | `pdf_tables.py` |
| 본문·표 통합 추출, 표 영역 중복 제거 | 완료 | `pdf_content.py` |
| 청킹(기술사양서·안전기준), `Chunk` 구조 | 미구현 | |
| 태그 생성 (`part`, `task`) | 미구현 | |
| 임베딩 생성 (`core.llm.embed`) | 미구현 | QA와 합의 후 |
| 문서 등록·중복 확인, 목록·상태·삭제 서비스 | 미구현 | `features/documents/`는 비어 있음 |

### 5.1 데이터 구조 (실제 코드 기준)

```text
PageText(page_no, text, char_count, image_count, is_low_text)           # pdf_text.py
PdfText(file_name, page_count, pages)

TableBlock(page_no, table_index, bbox, rows, row_count, col_count,
           empty_ratio, is_reliable)                                    # pdf_tables.py
PdfTables(file_name, page_count, tables, failed_pages)

PageContent(page_no, body_text, tables, is_low_text, image_count)       # pdf_content.py
PdfContent(file_name, page_count, pages, failed_table_pages)
```

`Chunk`는 아직 정의되지 않았다. 확정된 형태는 `.text`(str), `.metadata`(dict), `.chunk_id`(속성)이다. 메타데이터는 §4를 따른다.

### 5.2 호출할 함수

| 함수 | 반환 | 설명 |
|---|---|---|
| `extract_pdf_content(path)` | `PdfContent` | 본문과 표를 함께 추출한다. 파이프라인은 이 함수를 쓴다 |
| `extract_pdf_text(path)` | `PdfText` | 페이지별 원문 텍스트만 필요할 때 |
| `extract_pdf_tables(path)` | `PdfTables` | 표만 필요할 때 |

예외 메시지는 영어다.

| 예외 | 의미 |
|---|---|
| `PdfExtractionError` | 파일 없음, PDF가 아님, 손상, 암호화 |
| `ScannedPdfError` (`PdfExtractionError`의 하위) | 텍스트 페이지 비율이 30% 미만인 스캔 PDF. 지원하지 않는다 |

`ScannedPdfError`를 먼저 잡고 `PdfExtractionError`를 잡는다. 사용자용 문구는 박정환의 어댑터에서 만든다.

### 5.3 추출 결과의 성질

- 텍스트가 50자 미만인 페이지는 `is_low_text=True`다. 이미지·도면 위주 페이지일 수 있다.
- `TableBlock.is_reliable=False`인 표(빈 셀 비율 50% 초과 또는 행·열이 모두 2 이하)는 구조가 틀렸을 수 있다. 이 표의 영역은 `body_text`에서 지우지 않고, **신뢰할 수 있는 표만** 본문에서 뺀다.
- 표 셀의 분리된 숫자(`'0 37\n.'`)는 페이지 글자 좌표로 `0.37`처럼 복원한다. 본문에서는 같은 문제가 발견되지 않았다.
- 표 값과 헤더를 연결한 텍스트화, 병합 헤더·병합 셀의 빈 칸 처리는 아직 하지 않았다.

## 6. PDF 추출의 알려진 한계

OCR과 Vision LLM 기반 도면·이미지 해석은 구현 범위에서 제외한다. 읽을 수 없는 스캔본·도면의 내용을 임의로 만들어내지 않는다. 테스트 PDF 3개(LUXEN/NEW YZER 카탈로그, 엘트론 기술사양서, 안전기준 KC 2050-51:2022)로 확인한 한계는 아래와 같다.

- **안전기준 수식:** 수식 본체가 텍스트로 나오지 않는다(예: 11p, 181~182p). 변수 설명만 추출된다.
- **그림·도면:** 안전기준 그림 안의 치수, 엘트론의 도면 기호, LUXEN의 사진과 아이콘 속 글자는 추출되지 않는다. 그림 캡션과 기호 설명은 텍스트로 나온다.
- **제조사명:** 엘트론 문서에서는 로고 이미지에만 있어서 텍스트로 나오지 않는다.
- **표:** `find_tables()`가 놓친 표는 알 수 없고, 구조가 틀린 표가 신뢰도 높음으로 분류될 수 있다. 확인된 실패 사례는 LUXEN 26·27p다.
- 위 항목은 일부 페이지를 직접 보고 정리한 것이라, 확인하지 않은 페이지에는 다른 누락이 있을 수 있다.

챗봇이 수식이나 도면에 관한 질문에 답하지 못할 수 있다. 질의응답 쪽에서 근거가 없으면 답을 만들어내지 않도록 처리해야 한다.

## 7. 연결 지점별 인터페이스

### 7.1 문서관리 → 박정환 (`IngestPipeline`)

합의한 파이프라인 단계 함수는 아래와 같다. `is_scanned`, `extract_text`, `extract_tables`는 주입하지 않는다.

| 단계 | 시그니처 | 상태 |
|---|---|---|
| 추출 | `extract_pdf_content(path) -> PdfContent` | 완료 |
| 청킹 | `chunk(document: Document, content: PdfContent) -> list[Chunk]` | 미구현 |
| 태그 | `tag(chunks: Sequence[Chunk]) -> list[Chunk]` | 미구현 |
| 임베딩 | `embed(texts: list[str]) -> list[list[float]]` | 미구현 |

- `tag`는 입력과 같은 순서·길이로 돌려주고, 태그가 있는 청크만 `metadata`에 `part`·`task`를 추가한 새 `Chunk`를 돌려준다.
- 현재 `features/processing/pipeline.py`(feat/50-ingest-pipeline)의 `IngestSteps`는 옛 시그니처(`is_scanned`, `extract_text`, `extract_tables`, `chunk(document, pages, tables)`)라서 위 합의에 맞게 박정환이 수정할 예정이다.
- `Indexer.prepare()`가 청크에서 검사하는 조건: `text`는 공백이 아닌 문자열, `source`는 비어 있지 않은 `str`, `page`는 1 이상 `int`, `chunk`는 0 이상 `int`, `document_id`·`document_type`은 문서와 같은 값, 값은 `str/int/float/bool`만, 같은 `(page, chunk)`는 한 번만. 이 조건을 어기면 `ValueError`다.
- 스캔본은 `ScannedPdfError`로 오고, `pipeline._error_text`는 `IngestError` 외 예외를 "예외이름 (see server log)"로만 기록한다. 박정환의 어댑터가 사용자용 문구로 바꾼다.
- 완료할 때 `set_status(id, "COMPLETED", chunk_count=저장한 청크 수)`로 청크 수를 넘긴다.

### 7.2 문서관리 → 박정환 (`DocumentService`)

이름과 입출력은 합의했고 아직 구현하지 않았다. 아래는 DB 담당이 만든 `documents` 테이블(§7.4)을 기준으로 한다.

```python
register_document(source_path, filename, doc_type, department_id) -> int        # 새 문서 ID
list_documents(doc_type=None, department_id=None, status=None, keyword=None) -> list[DocumentRow]
get_document(document_id) -> Document
get_status(document_id) -> DocumentStatus        # status, chunk_count, updated_at
set_status(document_id, status, error=None, chunk_count=None) -> None
summary() -> DocumentSummary                     # total, by_status, by_type{tech,secure}
delete_pdf(document_id) -> bool                  # 파일이 이미 없으면 False. 재시도 가능
delete_document_record(document_id) -> bool      # MySQL 행만 삭제. 반드시 마지막에 호출
```

- `Document`: `id`, `title`(= `doc_name`), `filename`(= `title + ".pdf"`, `source`용), `doc_type`, `department_id`, `department_name`, `status`, `chunk_count`, `created_at`, `updated_at`, `file_path`. `file_path`는 컬럼이 아니라 서비스가 계산한 저장소 안의 절대 `Path`다. 화면에 노출하지 않는다. `DocumentRow`는 `file_path`를 뺀 것이다.
- `department_id`는 기술·안전 문서 모두 필수다(`dept_id NOT NULL`).
- 예외: `DuplicateDocumentError`(`.document_id`에 기존 문서 ID), `DocumentNotFoundError`, `DocumentStorageError`, `InvalidStatusTransition`, `ValueError`(유형·파일 형식·파일명·부서 오류).
- `filename`은 원본 파일명이고, 서비스가 NFC로 정규화한 뒤 확장자를 빼서 `title`을 만든다.
- 등록 순서: 입력 검증(`%PDF-` 헤더, 크기) → `title`·해시 계산 → 중복 조회(중복이면 거절) → 임시 파일로 저장 → `INSERT`(상태 `처리 중`) → 임시 파일을 `{저장소}/{doc_type}/{id}.pdf`로 이름 변경. 실패하면 행과 파일을 정리한다. `execute`가 `lastrowid`를 주지 않으므로 새 ID는 `title_hash`로 다시 조회해서 얻는다. 사용자 파일명은 경로에 쓰지 않는다.
- 저장소 기준 폴더는 환경변수로 관리하며, 위치는 미확정이다(§8).
- 책임 구분: DocumentService는 MySQL 행과 원본 PDF 파일만 다루고 ChromaDB와 파이프라인을 호출하지 않는다. 파이프라인은 MySQL에 직접 접근하지 않고 `set_status`만 호출한다.

### 7.3 문서관리 → ChromaDB (`util/vector_upload.py`, 이미 있음)

```python
from util.vector_upload import upload_embeddings

n = upload_embeddings(doc_type, collection_name, ids, embeddings, documents, metadatas)
```

- `doc_type`은 `"tech"` 또는 `"secure"`이고, 유형마다 접속하는 서버가 다르다. 컬렉션 이름은 인자로 받는다.
- **컬렉션은 기술 `tech_docs`, 안전 `safety_docs`로 확정**됐다(박정환 전달). QA의 `retriever.py`는 기술 문서 컬렉션을 임시 이름 `manual_docs`로 쓰고 있어 `tech_docs`로 바꿔야 한다.
- `ids`, `embeddings`, `documents`, `metadatas`는 같은 길이여야 하고, 같은 id를 다시 보내면 덮어쓴다(upsert).
- 컬렉션은 처음 저장할 때 임베딩 차원이 고정된다. 다른 차원은 저장하지 않는다.
- **거리 방식은 L2(Chroma 기본값)로 둔다.** QA의 `distance_to_similarity`가 `1 - d/2`로 L2를 가정하므로, cosine 컬렉션을 만들면 유사도가 틀려진다. 바꾸려면 QA와 먼저 합의한다.
- 두 서버에는 현재 인증이 없다. 자세한 사용법은 `docs/VectorDBConnector.md`를 따른다.

### 7.4 문서관리 → MySQL

- `util/mysql_connection.py`의 `fetch_all(sql, params)`, `execute(sql, params)`로 SQL을 직접 보낸다. 값은 `:이름` 자리표시자로 넘기고 SQL 문자열에 이어 붙이지 않는다. `execute`는 영향 행 수만 반환하고 `lastrowid`는 주지 않는다. 자세한 사용법은 `docs/MySqlConnector.md`를 따른다.
- `core/models/`는 비어 있고 ORM 모델은 쓰지 않는다. raw SQL 방식을 따른다.
- DB 담당이 만든 `documents` 테이블(`mansa/migrations/0001_create_documents.sql`, 수동 실행. 이후 변경은 기존 파일을 고치지 않고 새 번호 파일로 추가):

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | INT PK AUTO_INCREMENT | 문서 ID. ChromaDB `document_id`로 사용 |
| `title` | VARCHAR(255) NOT NULL | 원래 파일 이름(확장자 제외, 소문자 변환 전) |
| `title_hash` | CHAR(64) NOT NULL UNIQUE | 중복 판정 키 |
| `doc_type` | ENUM('tech','secure') NOT NULL | 삭제·저장할 DB를 정한다 |
| `dept_id` | 부서 PK와 같은 타입, NOT NULL | FK → 부서 테이블 PK, ON DELETE RESTRICT |
| `status` | VARCHAR(10) NOT NULL | `처리 중` / `완료` / `실패` |
| `chunk_count` | INT NULL | 완료 시 기록 |
| `created_at` | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | |

- 이 테이블에는 **원본 PDF 경로 컬럼과 실패 사유 컬럼이 없다.** 경로는 문서 ID로 계산하고, 실패 사유 컬럼은 추가를 요청한다(§3.3).
- 부서 삭제는 RESTRICT라서 문서가 있는 부서는 삭제할 수 없다. 기준정보 화면의 부서 삭제는 이 오류를 처리해야 한다.
- 이 파일은 아직 저장소에서 확인하지 못했다. 컬럼명은 DB 담당이 전달한 표를 기준으로 한다.

### 7.5 문서관리 → 질의응답 (`util/rag_query.py`, `features/retrieval/`)

문서관리가 질의응답에 넘기는 것은 ChromaDB에 저장된 청크(텍스트·임베딩·§4 메타데이터)뿐이다. 함수를 직접 호출하는 연결은 없다. 문서관리가 알아야 할 QA의 동작은 아래와 같다.

- `search_chunks()`, `get_chunks()`의 결과는 `{"id", "text", "metadata", "distance"}`(`get_chunks`는 `distance` 없음) 형식이다. 검색 로직은 QA 담당이라 수정하지 않는다.
- `retriever.py`는 `part`·`task`를 쉼표로 쪼개 질문의 `Intent` 부위·작업과 겹치는 개수로 순위를 정한다. 문자열이 아니거나 비어 있으면 태그가 없는 것으로 본다.
- `Intent`의 모델·부위는 기준정보에 **등록된 값만** 남긴다. 모델은 `where` 필터로 거를 예정이라, 청크의 `model`이 등록된 모델 ID와 철자가 같아야 한다.
- BM25는 `get_chunks`로 읽은 청크 원문(`text`)만 사용한다. 메타데이터는 BM25에 쓰이지 않는다.
- 청크를 `(source, page, chunk)`로 정렬한다. 키가 없으면 빈 문자열이나 0으로 취급한다.

## 8. 미확정·확인 필요

| 항목 | 확인할 곳 |
|---|---|
| `title_hash`의 입력 규칙(`doc_type` 포함 여부, 소문자 변환, NFC 정규화) | DB 담당 |
| `documents`에 `error_message` 컬럼 추가, `status` 한글 3값 확정, 마이그레이션 파일 위치·실행 시점 | DB 담당 |
| 원본 PDF 저장 위치·방식(영속 볼륨 여부), 기준 폴더 환경변수 | DB 담당·박정환 |
| 남아 있는 ChromaDB 테스트 데이터의 차원(1536 vs 3072) 정리 | DB 담당 |
| 분류표의 **부위·작업 표준 태그 목록**. 받기 전에는 자유 생성, 받으면 목록 안에서만 선택 | QA·기준정보 담당 |
| 기준정보의 **모델 ID 목록**. 받기 전에는 PDF 표기(예: `LUXEN`, `NEW YZER`)를 그대로 `model`에 넣는다 | QA·기준정보 담당 |
| `chunk`를 0부터 시작하는 것, `model`·`clause` 같은 키가 없는 청크의 처리 | QA |
| `core.llm.embed` 추가, QA의 `embed` 기본값 교체 시점, QA `retriever.py`의 `manual_docs` → `tech_docs` 변경 | QA |
| `IngestSteps`·`Indexer`를 합의한 시그니처로 바꾸는 시점, 상태 전이 검증 수용 여부, `chunk_count` 전달, 삭제 중간 실패 처리 | 박정환 |
| 신뢰도 낮은 표를 청크로 만들지 여부 | 장영균 |
| 수식·도면 페이지에 OCR/Vision을 나중에 추가할지 | 팀 합의 |

## 9. 작업 규칙

1. 실제 저장소에서 확인하지 못한 파일, 함수, DB 필드를 있다고 가정하지 않는다. 필요한 정보가 없으면 보고하고 요청한다.
2. 담당이 아닌 파일은 요청 없이 수정하지 않는다. 특히 박정환의 화면·파이프라인·`Indexer` 파일, QA의 `util/rag_*.py`와 `features/retrieval/`, 공용 DB 설정, `core/llm.py`는 담당자와 합의한 뒤에 바꾼다.
3. ChromaDB 데이터 구조, 컬렉션 이름, MySQL 스키마를 독자적으로 정하거나 바꾸지 않는다. 기존 마이그레이션 파일을 고치지 않고 새 번호 파일로 추가한다.
4. 문서 유형은 `tech`/`secure`, 메타데이터 키 `source`/`page`/`chunk`는 이름과 타입을 유지한다.
5. 비밀값(API 키, DB 접속 정보)은 환경변수로만 다루고 코드·로그·커밋에 남기지 않는다.
6. 구현 후에는 단위 테스트를 실행하고, 실행한 결과만 성공으로 보고한다.
7. `main` 직접 푸시 금지. 커밋·푸시·PR은 요청이 있을 때만 한다. 커밋 메시지는 Conventional Commits 형식이다.
