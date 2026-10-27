# MANSA 문서관리 기능명세서

> 기준일: 2026-10-27 / 기준 브랜치: `feat/pdf-extraction`
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

BM25는 질의응답팀이 ChromaDB에서 청크를 읽어 검색 시점에 점수를 계산한다. 문서관리는 BM25 색인을 만들지 않는다.

## 2. 역할 분담

| 담당 | 문서관리 영역의 책임 |
|---|---|
| 장영균 | PDF 텍스트·표 추출, 청킹, `PageText`·`TableBlock`·`Chunk` 구조, 청크 메타데이터, 태그 배치 생성, 임베딩 생성 함수, 문서 등록·중복 확인, 목록·현황·상태 조회, `DocumentService.set_status()`, 원본 PDF·MySQL 기록 삭제 함수, 단위 테스트 |
| 박정환 | `IngestPipeline.run()`, 전처리 함수 연결, ChromaDB 저장·삭제 연동, 처리 상태 기록, 전체 삭제 흐름, 화면 연결(`ui/upload.py`, `ui/documents.py`, `ui/doc_view.py`, `ui/master.py`), 기준 차이 비교, 통합 테스트 |
| 질의응답팀 (이세림·강병훈) | 질문 분석, 질문 임베딩, 벡터·태그·BM25 검색, 답변 생성, 출처 표시, 챗봇 UI. 청크 메타데이터를 읽어서 쓴다 |
| DB 담당 | MySQL·ChromaDB 서버, 스키마·컬렉션, 문서 ID·저장 규칙, 접근 방식 |

Gradio 화면 연결과 ChromaDB 저장 파이프라인은 장영균 담당이 아니다. 장영균은 화면에서 호출할 수 있는 서비스 함수까지 제공한다.

## 3. 확정된 정책

### 3.1 문서 유형

| 값 | 의미 |
|---|---|
| `tech` | 기술사양서 |
| `secure` | 안전기준 문서 |

`SPEC`, `SAFETY`, 한글 표기 등 다른 내부 값을 쓰지 않는다. 화면에는 "기술 문서"/"안전 문서"로 보이므로 서비스 경계에서 `tech`/`secure`로 변환한다.

### 3.2 문서 등록과 중복

- 버전 관리, 기존 문서 갱신, 별도 재처리 기능은 구현하지 않는다.
- 중복 기준은 **파일명 + 문서 유형**이다. 파일 해시(SHA-256)와 해시 컬럼은 쓰지 않는다.
- `register_document()` 규칙:
  1. 파일명과 문서 유형으로 기존 문서를 확인한다.
  2. 중복이면 PDF 저장과 MySQL 신규 등록 **전에** 거절한다.
  3. 중복된 기존 문서의 ID를 반환한다.
  4. 기존 문서는 자동 삭제하지 않는다.
  5. 사용자가 문서관리 화면에서 직접 삭제한 뒤 다시 업로드한다.
- 업로드 화면의 중복 안내는 박정환 담당이다.

### 3.3 처리 상태

- `DocumentService.set_status(document_id, status, error=None)`로 상태와 실패 사유를 기록한다. 박정환의 파이프라인이 호출한다.
- 협의 중인 상태: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`. `PENDING`은 화면에서 "처리 중"으로 표시한다.
- **실제 MySQL의 상태값과 컬럼명은 미확정이다**(§8). 확인되기 전에는 새 값을 만들지 않는다.

### 3.4 삭제

실행과 연동은 박정환 담당이다. 순서는 아래와 같고, 중간에 실패하면 MySQL 기록을 남겨 재시도할 수 있게 한다.

1. ChromaDB 청크·벡터 삭제 (박정환)
2. 원본 PDF 파일 삭제 (장영균이 함수 제공)
3. MySQL 문서 기록 삭제 (장영균이 함수 제공)

### 3.5 태그 생성

- 모델 `gpt-4o-mini`, 여러 청크를 묶어 배치 호출하고 청크별로 태그를 구분한다.
- 태그 값은 모두 문자열이고, 중복은 정리한다.
- LLM 호출이 실패해도 문서 전체 처리는 계속한다.
- 태그 생성에 실패했거나 결과가 없으면 메타데이터에서 `tags` 키를 **생략**한다. `tags=[]`는 저장하지 않는다.
- ChromaDB 1.5.9에서 문자열 리스트 메타데이터 저장이 가능한지는 박정환이 실서버로 확인할 예정이다. 결과가 나오기 전에는 지원 형식을 단정하지 않는다.

### 3.6 임베딩

- 모델 `text-embedding-3-large`, 차원 3072.
- 공통 함수는 `core.llm.embed()`로 제안되어 있다(**아직 없음**). 질의응답팀이 질문 임베딩에도 재사용할 수 있게 설계한다. `core/llm.py`는 공용 파일이므로 추가 전에 질의응답팀과 합의한다.
- 청크 임베딩 생성은 문서관리, 질문 임베딩과 검색은 질의응답, ChromaDB에 실제 저장하는 일은 박정환 담당이다.
- 기존 `tech_docs`/`safety_docs`의 임베딩 모델·차원과 다르면 무리하게 저장하지 않는다.

## 4. 청크 메타데이터 계약

질의응답팀의 `util/rag_query.py`가 아래 세 키를 사용한다. **키 이름과 자료형을 바꾸지 않는다.**

| 키 | 타입 | 설명 |
|---|---|---|
| `source` | str | PDF 파일명 |
| `page` | int | PDF 페이지 번호(1부터) |
| `chunk` | int | 해당 페이지 안에서의 청크 순번 |

질의응답팀은 `(source, page, chunk)`로 정렬해서 출처를 구성한다. 한 페이지에 청크가 여러 개면 `chunk`는 페이지별 순번이다.

필요한 범위에서 추가하는 메타데이터:

| 키 | 설명 |
|---|---|
| `document_id` | 문서 삭제용 공통 식별자 |
| `document_type` | `tech` 또는 `secure` |
| `department_id` | 소속 부서 |
| `product_model` | 기술사양서 모델 |
| `section_number` | 안전기준 조항·절 번호 |
| `section_title` | 조항·절 제목 |
| `tags` | LLM 태그 (§3.5) |

ChromaDB 메타데이터는 실제 DB 규칙과 호환되어야 한다. `util/rag_query.py`는 저장소에 아직 올라와 있지 않아 이 문서에서는 위 세 키만 계약으로 본다.

## 5. 현재 구현 상태

위치는 모두 `mansa/features/processing/`이다. 테스트는 `mansa/`에서 아래 명령으로 실행한다.

```powershell
uv run --locked python -B -m unittest discover -s tests -v
```

| 기능 | 상태 | 비고 |
|---|---|---|
| 페이지별 텍스트 추출, 스캔본 판별 | 완료 | `pdf_text.py` |
| 표 추출, 숫자 복원, 표 신뢰도 표시 | 구현됨(커밋 전) | `pdf_tables.py` |
| 본문·표 통합 추출, 표 영역 중복 제거 | 구현됨(커밋 전) | `pdf_content.py` |
| 청킹(기술사양서·안전기준), `Chunk` 구조 | 미구현 | |
| 태그 생성 | 미구현 | |
| 임베딩 생성 | 미구현 | |
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

`Chunk`는 아직 정의되지 않았다. 필드는 §4의 메타데이터 계약을 만족하도록 청킹 이슈에서 정한다.

### 5.2 호출할 함수

| 함수 | 반환 | 설명 |
|---|---|---|
| `extract_pdf_content(path)` | `PdfContent` | 본문과 표를 함께 추출한다. 파이프라인은 이 함수를 쓰면 된다 |
| `extract_pdf_text(path)` | `PdfText` | 페이지별 원문 텍스트만 필요할 때 |
| `extract_pdf_tables(path)` | `PdfTables` | 표만 필요할 때 |

예외는 모두 영어 메시지다.

| 예외 | 의미 |
|---|---|
| `PdfExtractionError` | 파일 없음, PDF가 아님, 손상, 암호화 |
| `ScannedPdfError` (`PdfExtractionError`의 하위) | 텍스트 페이지 비율이 30% 미만인 스캔 PDF. 지원하지 않는다 |

### 5.3 추출 결과의 성질

- 텍스트가 50자 미만인 페이지는 `is_low_text=True`다. 이미지·도면 위주 페이지일 수 있다.
- `TableBlock.is_reliable=False`인 표(빈 셀 비율 50% 초과 또는 행·열이 모두 2 이하)는 구조가 틀렸을 수 있다. 이 표의 영역은 `body_text`에서 지우지 않고, **신뢰할 수 있는 표만** 본문에서 뺀다. 신뢰도 낮은 표를 청킹에서 어떻게 쓸지는 미확정이다.
- 표 셀의 분리된 숫자(`'0 37\n.'`)는 `0.37`처럼 복원한다. 본문에서는 같은 문제가 발견되지 않았다.
- 표 값과 헤더를 연결한 텍스트화, 병합 헤더·병합 셀의 빈 칸 처리는 아직 하지 않았다.

## 6. PDF 추출의 알려진 한계

OCR과 Vision LLM 기반 도면·이미지 해석은 구현 범위에서 제외한다. 읽을 수 없는 스캔본·도면의 내용을 임의로 만들어내지 않는다. 테스트 PDF 3개(LUXEN/NEW YZER 카탈로그, 엘트론 기술사양서, 안전기준 KC 2050-51:2022)로 확인한 한계는 아래와 같다.

- **안전기준 수식:** 수식 본체가 텍스트로 나오지 않는다(예: 11p, 181~182p). 변수 설명만 추출된다.
- **그림·도면:** 안전기준 그림 안의 치수, 엘트론의 도면 기호, LUXEN의 사진과 아이콘 속 글자는 추출되지 않는다. 그림 캡션과 기호 설명은 텍스트로 나온다.
- **제조사명:** 엘트론 문서에서는 로고 이미지에만 있어서 텍스트로 나오지 않는다. 문서 제목은 파일명이나 입력값으로 정한다.
- **표:** `find_tables()`가 놓친 표는 알 수 없고, 구조가 틀린 표가 신뢰도 높음으로 분류될 수 있다. 확인된 실패 사례는 LUXEN 26·27p다.
- 위 항목은 일부 페이지를 직접 보고 정리한 것이라, 확인하지 않은 페이지에는 다른 누락이 있을 수 있다.

챗봇이 수식이나 도면에 관한 질문에 답하지 못할 수 있다. 질의응답 쪽에서 근거가 없으면 답을 만들어내지 않도록 처리해야 한다.

## 7. 연결 지점별 인터페이스

### 7.1 문서관리 → 박정환 (`IngestPipeline.run()`)

| 항목 | 상태 |
|---|---|
| 추출 함수 `extract_pdf_content(path)` | 제공됨 |
| 청킹·태그·임베딩 함수 | 미구현. 시그니처는 청킹 이슈에서 협의 |
| `DocumentService.set_status(document_id, status, error=None)` | 미구현. 반환값과 실패 시 동작 협의 필요 |
| `register_document()` 중복 시 반환 형식(예외인지 값인지) | 협의 필요 |
| `ids`/`documents`/`metadatas`를 만드는 주체 | 협의 필요 |

### 7.2 문서관리 → ChromaDB (`util/vector_upload.py`, 이미 있음)

```python
from util.vector_upload import upload_embeddings

n = upload_embeddings(doc_type, collection_name, ids, embeddings, documents, metadatas)
```

- `doc_type`은 `"tech"` 또는 `"secure"`이고, 컬렉션은 각각 `tech_docs`, `safety_docs`다.
- `ids`, `embeddings`, `documents`, `metadatas`는 같은 길이여야 하고, 같은 id를 다시 보내면 덮어쓴다(upsert).
- 컬렉션은 처음 저장할 때 임베딩 차원이 고정된다. 다른 차원은 저장하지 않는다.
- 두 서버에는 현재 인증이 없다. 자세한 사용법은 `docs/VectorDBConnector.md`를 따른다.

### 7.3 문서관리 → MySQL

- `util/mysql_connection.py`의 `fetch_all(sql, params)`, `execute(sql, params)`로 SQL을 직접 보낸다. 값은 `:이름` 자리표시자로 넘기고 SQL 문자열에 이어 붙이지 않는다. 자세한 사용법은 `docs/MySqlConnector.md`를 따른다.
- `core/models/`는 비어 있고 ORM 모델은 아직 쓰지 않는다.
- **문서 테이블의 스키마가 확인되지 않았다**(§8).

### 7.4 문서관리 → 질의응답

문서관리가 질의응답에 넘기는 것은 ChromaDB에 저장된 청크(텍스트·임베딩·§4 메타데이터)뿐이다. 함수를 직접 호출하는 연결은 없다.

## 8. 미확정·확인 필요

| 항목 | 확인할 곳 |
|---|---|
| MySQL 문서 테이블 스키마(테이블명, 컬럼명, 상태값, 부서·문서 유형 컬럼) | DB 담당 |
| `tech_docs`/`safety_docs`의 기존 임베딩 모델과 차원 | DB 담당 |
| 원본 PDF 저장 위치와 방식 | DB 담당·박정환 |
| 문자열 리스트 메타데이터(`tags`)의 ChromaDB 실서버 저장 가능 여부 | 박정환 |
| `IngestPipeline.run()` 호출 규약, `set_status` 사용 방식 | 박정환 |
| `util/rag_query.py` 위치와 `source`/`page`/`chunk` 사용 방식 | 질의응답팀 |
| `core.llm.embed()` 추가와 임베딩 모델명 설정(`config.py`에는 `LLM_API_KEY`, `LLM_MODEL`만 있음) | 질의응답팀 |
| 신뢰도 낮은 표를 청크로 만들지 여부 | 장영균 |
| 수식·도면 페이지에 OCR/Vision을 나중에 추가할지 | 팀 합의 |

## 9. 작업 규칙

1. 실제 저장소에서 확인하지 못한 파일, 함수, DB 필드를 있다고 가정하지 않는다. 필요한 정보가 없으면 보고하고 요청한다.
2. 담당이 아닌 파일은 요청 없이 수정하지 않는다. 특히 박정환의 화면·파이프라인 파일, 공용 DB 설정, `core/llm.py`는 담당자와 합의한 뒤에 바꾼다.
3. ChromaDB 데이터 구조, 컬렉션 이름, MySQL 스키마를 독자적으로 정하거나 바꾸지 않는다. 기존 마이그레이션 파일을 고치지 않는다.
4. 문서 유형은 `tech`/`secure`, 메타데이터 키 `source`/`page`/`chunk`는 이름과 타입을 유지한다.
5. 비밀값(API 키, DB 접속 정보)은 환경변수로만 다루고 코드·로그·커밋에 남기지 않는다.
6. 구현 후에는 단위 테스트를 실행하고, 실행한 결과만 성공으로 보고한다.
7. `main` 직접 푸시 금지. 커밋·푸시·PR은 요청이 있을 때만 한다. 커밋 메시지는 Conventional Commits 형식이다.
