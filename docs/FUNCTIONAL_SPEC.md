# MANSA 문서관리 기능명세서

> 기준일: 2026-10-29 / 기준 브랜치: `feat/102-pdf-chunking`
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

> DB 정의가 바뀌었을 수 있다. §7.4의 "변경 확인 필요"를 먼저 본다.

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

> DB 정의가 바뀌었을 수 있다. §7.4의 "변경 확인 필요"를 먼저 본다.

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

- 모델 `gpt-4o-mini`(`config.LLM_MODEL`)로 여러 청크를 배치(`BATCH_SIZE` 5개)로 분석해 두 종류를 생성한다. 15개씩 보내면 LLM이 뒤쪽 청크의 태그를 비워서 돌려주는 일이 많아 5개로 줄였다. 구현은 `features/processing/tagger.py`의 `tag(chunks, vocabulary, complete=llm.complete)`이다.
  - `part`: 설비 부위 (분류표 부위의 표준 이름, 예: 메인 로프, 완충기)
  - `task`: 작업 (분류표 작업의 표준 이름. **부위와 동작을 합친 이름**, 예: 메인 로프 점검)
- 질의응답이 질문에서 뽑은 부위·작업(분류표 이름)과 청크의 태그가 글자까지 같아야 순위에 반영되므로, 태그는 **분류표 목록 안의 표준 이름만** 쓴다. 어휘(`Vocabulary`)는 `TaxonomyService`의 부위·작업·동의어를 복사해 만든다(`Vocabulary.from_taxonomy`). 분류표 파일은 읽기만 한다. 동의어는 표준 이름으로 바꾼 뒤 판단하고, 목록에 없는 용어는 태그에서 뺀다(§8).
- ChromaDB에는 쉼표로 구분한 문자열로 저장한다: `{"part": "메인 로프, 완충기", "task": "메인 로프 점검"}`. 구분자는 `", "`이고, 태그 안에는 쉼표를 넣지 않는다.
- 부위(또는 그 동의어)가 본문에 하나도 없는 청크는 LLM을 부르지 않는다(제목만 있는 청크, 디자인 설명 등).
- 배치 결과는 **청크 ID로만** 대응시킨다. 모르는 ID, 중복 ID, 누락된 ID의 결과는 버린다.
- 문자열만 남기고 앞뒤 공백·빈 값·중복을 제거한다. 청크당 `part`는 최대 3개, `task`는 최대 2개(`MAX_PART_TAGS`, `MAX_TASK_TAGS`)만 LLM이 준 순서대로 남긴다. 결과가 비면 해당 키를 **생략**한다. 빈 문자열은 저장하지 않는다.
- 원문에 근거한 태그만 남긴다. `part`는 부위 이름이나 동의어가 본문에 있어야 하고, `task`는 작업 이름의 앞부분(부위)과 마지막 단어(동사)가 모두 본문에 있어야 한다. 공백·영문 대소문자 차이는 무시하고, 한 글자 동의어(`카`)는 `카문`·`카드`에 걸리지 않게 단어 경계를 본다.
- 배치 하나가 실패해도 문서 처리는 중단하지 않고, 그 배치의 청크는 태그 없이 둔다. 함수 전체도 예외를 내지 않는다. 로그에는 예외 종류와 배치 위치만 남긴다.

### 3.6 임베딩

- 모델 `text-embedding-3-large`, 차원 3072. 문서 청크와 질문 임베딩은 **같은 모델**이어야 한다.
- 공통 함수는 `core.llm.embed(texts: list[str]) -> list[list[float]]`이며 `core/llm.py`에 **구현되어 있다**. 입력과 같은 순서로 벡터를 돌려주고, 모델은 `config.EMBEDDING_MODEL`(기본 `text-embedding-3-large`)이다. QA의 `Embedder` 타입(`Callable[[list[str]], list[list[float]]]`)과 같아서 `search_chunks(..., embed=embed)`에 그대로 넘길 수 있다.
- 동작: `LLM_API_KEY`가 없으면 `RuntimeError`, 빈 목록이면 API를 부르지 않고 `[]`, API 실패는 openai 예외로 그대로 전달한다(임베딩 없이는 저장할 수 없다). **빈 문자열 검사와 응답 차원(3072) 검사는 코드에 없다.** 실제 API 호출로 차원을 확인하지는 않았다.
- `core/llm.py`와 `config.py`는 QA와 공유하는 파일이다. 수정할 때는 최소 변경으로 하고 QA와 먼저 합의한다.
- QA의 `util/rag_ingest.py`·`rag_query.py`의 기본 임베딩 함수(`test_embed_with_openai`)도 같은 `config.EMBEDDING_MODEL`을 쓰므로 모델과 차원은 `core.llm.embed`와 같다. 다만 함수가 따로 있어서, 통일할 시점은 QA와 맞춘다. 임베딩 모델을 바꾸면 벡터 차원이 달라져(small 1536, large 3072) 이미 만든 컬렉션에는 넣거나 검색할 수 없다.
- 컬렉션은 처음 저장할 때 차원이 고정된다. 기존 `rag_ingest` 테스트 데이터(1536차원)가 남은 컬렉션에는 저장하지 않는다.

### 3.7 청킹 원칙

구현 위치는 `features/processing/chunker.py`(진입점), `chunker_secure.py`, `chunker_tech.py`, `chunk_utils.py`다.

**공통**
- 진입점은 `chunk(document, content, models=None)`다. `document.doc_type`이 `secure`면 안전기준, `tech`면 기술사양서 청킹으로 분기하고, 알 수 없는 유형이면 `ValueError`다. `models`는 기술사양서에서만 쓴다.
- **청크는 페이지를 넘지 않는다.** 출처가 `(source, page)`로 표시되기 때문이다. 조항이 다음 페이지로 이어지면 그 페이지에서 새 청크가 된다.
- 본문 길이는 300~1,200자를 목표로 하고 머리말을 포함해 1,500자를 넘지 않는다. 임베딩 입력 한도(8,191토큰)보다 충분히 작다.
- 한 페이지 안에서 본문 청크를 먼저, 표 청크를 다음에 하나의 `chunk` 순번(0부터)으로 매긴다.
- **신뢰도 낮은 표(`is_reliable=False`)는 청크를 만들지 않는다.** 그 표의 글자는 본문에 남아 있어서 본문 청크에 들어간다.
- **수식 폰트의 읽을 수 없는 글리프(사설 영역 문자)는 청크에서 지운다.** 지워서 글자·숫자가 남지 않은 줄은 버린다. `PdfContent`의 원본은 바꾸지 않으므로 나중에 수식을 읽을 수 있게 되면 원본을 다시 쓸 수 있다.
- 표 안의 각주 표시(`100가)`, `2,500다)`)는 지우거나 분리하지 않고 그대로 둔다.
- **청크 본문에 모델명이나 조항 번호를 포함한다.** QA의 BM25는 본문 텍스트만 보고, 메타데이터는 보지 않는다.

**안전기준 (`chunker_secure.py`)**
- 줄 머리의 조항 번호(`6.5.1.2`)로 나눈다. 직전 조항의 다음 번호(첫 하위 조항이거나 같은 단계에서 1~5 큰 번호)일 때만 조항으로 보고, 본문 속 숫자(`89 …`, `1 000 ㎏`, `3 참조)`)는 조항으로 보지 않는다.
- 짧은 조항은 같은 페이지 안에서 합친다(1~2단계 조항에서 새 청크를 시작). 1,200자를 넘는 조항은 줄·문장 경계에서 나눈다.
- 본문 앞에 맥락 머리말을 붙인다: 상위 제목 `[6.5 승강로]`, 이어지는 조항 `[8.2.1.2 일반사항 계속]`, 부속서 `[부속서 Ⅴ 기계류 공간 - 접근]`.
- 부속서(`부속서 Ⅰ` 제목이 페이지 앞 3줄 안에 있을 때)는 조항 번호 없이 처리하고 `section_title`에 부속서 제목을 넣는다.
- 신뢰도 높은 표는 행마다 `열 이름: 값 | …` 문장으로 바꾸고, 표 제목(`[ 표 5. … ]`)을 청크마다 붙인다. 값이 한 칸뿐인 행(`비고`)은 값만 쓴다. 첫 열이 조항 번호면 그 청크의 `clause`로 쓴다.

**기술사양서 (`chunker_tech.py`)**
- 모델 이름 목록(`models`)은 박정환이 문서를 처리할 때마다 기준정보(`EquipmentModelService().list_models()`의 `name`, 원본은 `data/master/equipment_models.csv`)에서 읽어 넘긴다. PDF에서 제품명을 규칙으로 추측하면 `PASSENGER ELEVATORS` 같은 문구가 섞여 틀린 `model`이 들어가기 때문이다. 목록이 없으면 `model` 키와 머리말을 넣지 않는다.
- 이름 매칭은 **긴 이름부터** 하고, 앞뒤에 영문·숫자가 바로 붙지 않는 **단어 경계**에서만 맞춘다(`YZER`와 `NEW YZER`가 둘 다 있을 때 짧은 쪽이 먼저 걸리지 않게). 대소문자와 단어 사이 공백 차이는 무시한다. **`model`에는 PDF 표기가 아니라 목록에 있는 이름 그대로** 넣는다. 질문 분석이 등록된 이름으로 `model`을 찾아서 철자가 다르면 청크를 못 찾는다.
- 페이지 본문에 이름이 나오는 모델마다 그 페이지의 청크를 만들고 `[모델]` 머리말과 `model`을 둔다. **한 페이지에 모델이 둘 이상 나오면(공유 표, 소개 페이지) 같은 내용을 모델별로 복제한다.** 복제로 검색 결과에 같은 문장이 두 번 나올 수 있지만, QA(세림님)와 합의해 그대로 둔다. 모델이 나오지 않는 페이지는 `model` 없이 만든다.
- 표는 열 이름 행(최대 3줄)을 합쳐 열 이름을 만들고(`Car Inside` + `W` → `Car Inside W`), 행마다 `열 이름: 값 | …`로 바꾼다. 병합으로 가려진 칸은 같은 열의 위 행 값으로 채우고 실제 빈 칸은 채우지 않는다.
- 본문은 줄 단위로 묶고, 페이지 번호 줄과 글자가 30자 미만인 페이지(사진 설명 한두 줄)는 만들지 않는다.

**알려진 한계**
- 기술사양서의 `model`은 기준정보 CSV에 실제 모델이 채워져야 들어간다. 지금은 `[모델 A]` 같은 자리표시자라서 그대로면 `model` 없이 저장되고, QA의 모델 필터에 걸리지 않는다(§8). 문서는 CSV를 채운 뒤에 올려야 하고, 올린 뒤에 CSV를 고치면 문서를 삭제하고 다시 올려야 한다.
- LUXEN 전원설비 표(23p, 25p)는 한 칸에 값이 여러 개(`550 600 700`)라 행과 값의 연결이 부정확하다.
- 데이터 행에 숫자가 하나도 없는 표는 앞 3행을 열 이름으로 본다.
- 가로로 병합된 칸이 데이터 행에 있으면 위 행 값이 잘못 채워질 수 있다. 이번 PDF 3개에서는 확인되지 않았다.
- 규칙은 PDF 3개(안전기준 KC 2050-51, 엘트론, LUXEN/NEW YZER)로 만들었다. 다른 문서에는 맞지 않을 수 있다.

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
| `model` | str | `tech` | 차종·모델명. 청크당 하나. 기준정보 모델 이름 중 페이지에 나온 것을 **목록의 철자 그대로** 쓴다(§3.7, §8) |
| `clause` | str | `secure` | 조항·절 번호 (예: `6.6.4.1.2`). 표 청크는 첫 열이 조항 번호일 때만, 부속서는 없음 |
| `section_title` | str | `secure` | 조항·절 제목, 부속서는 부속서 제목. 선택 항목 |
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
| 청킹 진입점 `chunk()` | 완료 | `chunker.py` |
| 안전기준 청킹, `Chunk` 구조 | 완료 | `chunker_secure.py`, `models.py`, `chunk_utils.py` |
| 기술사양서 청킹 | 완료 | `chunker_tech.py`. 모델 이름 목록(`models`)이 있어야 `model`이 채워짐 |
| 태그 생성 (`part`, `task`) | 완료 | `tagger.py`. 실제 LLM(`gpt-4o-mini`)으로 PDF 3개를 태깅해 확인했다. 배치 5개 기준 안전기준 호출 대상 274개 중 150개에 부위, 13개에 작업 태그가 붙었다 |
| 임베딩 생성 (`core.llm.embed`) | 구현됨 | `core/llm.py`. 실제 API 호출로 차원을 확인하지 않았고, 빈 문자열·차원 검사는 없다 |
| 문서 등록·중복 확인, 목록·상태·삭제 서비스 | 미구현 | `features/documents/`는 비어 있음 |

### 5.1 데이터 구조 (실제 코드 기준)

```text
PageText(page_no, text, char_count, image_count, is_low_text)           # pdf_text.py
PdfText(file_name, page_count, pages)

TableBlock(page_no, table_index, bbox, rows, row_count, col_count,
           empty_ratio, is_reliable, merged)                            # pdf_tables.py
PdfTables(file_name, page_count, tables, failed_pages)

PageContent(page_no, body_text, tables, is_low_text, image_count)       # pdf_content.py
PdfContent(file_name, page_count, pages, failed_table_pages)
```

```text
Chunk(text, metadata)  # .chunk_id = "{document_id}:p{page}:{chunk}"      # models.py
DocumentLike           # 청킹이 문서에서 읽는 속성: id, title, filename, doc_type
```

`TableBlock.merged`는 `rows`와 같은 크기의 표시로, True인 칸은 병합된 셀에 가려진 칸(PyMuPDF가 `None`으로 준 칸)이다. 실제로 비어 있는 칸(False)과 구분하려고 둔다. `Chunk`의 메타데이터는 §4를 따른다.

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
- 병합으로 가려진 칸은 `merged`로 표시한다. 표 값과 헤더를 연결한 텍스트화, 병합 헤더·병합 칸 채우기는 청킹 단계에서 한다(§3.7).

## 6. PDF 추출의 알려진 한계

OCR과 Vision LLM 기반 도면·이미지 해석은 구현 범위에서 제외한다. 읽을 수 없는 스캔본·도면의 내용을 임의로 만들어내지 않는다. 테스트 PDF 3개(LUXEN/NEW YZER 카탈로그, 엘트론 기술사양서, 안전기준 KC 2050-51:2022)로 확인한 한계는 아래와 같다.

- **안전기준 수식:** 수식 본체가 읽히지 않는다(예: 11p, 181~182p). 수식은 이미지가 아니라 한글(HWP) 수식 편집기 폰트(`HyhwpEQ`)의 글자 코드로 들어 있고(42페이지, 수식이 든 텍스트 블록 496개, 글자 종류 108개), 코드가 표준 유니코드가 아니라 텍스트로 안 나온다. 청크에서는 이 글리프를 지우므로 변수 설명(`여기서, F : 전체 수직력(N)`)만 남고 수식은 없다. 수식 복원은 추후 진행한다(후보: 글리프 → 문자 변환표, 수식 영역 비전 LLM).
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
| 청킹 | `chunk(document, content, models=None) -> list[Chunk]` | 완료 |
| 태그 | `tag(chunks: Sequence[Chunk], vocabulary: Vocabulary, complete=llm.complete) -> list[Chunk]` | 완료 |
| 임베딩 | `embed(texts: list[str]) -> list[list[float]]` | 구현됨(`core.llm.embed`) |

- `tag`는 입력과 같은 순서·길이로 돌려주고, 태그가 있는 청크만 `metadata`에 `part`·`task`를 추가한 새 `Chunk`를 돌려준다. `IngestSteps.tag`는 청크 목록 하나만 받으므로, 박정환이 `chunk`와 같은 방식으로 `functools.partial(tag, vocabulary=Vocabulary.from_taxonomy(TaxonomyService.from_directory()))`로 감싸서 연결한다.
- `IngestSteps`는 합의한 시그니처(`extract`, `chunk`, `tag`, `embed`)로 develop에 반영됐다(PR #52). `chunk`의 `models`는 박정환이 문서를 처리할 때마다 `EquipmentModelService().list_models()`의 이름을 읽어 넘기는 함수로 감싸서 `IngestSteps.chunk`에 연결한다. 청킹 쪽은 `chunk(document, content, models=None)` 시그니처를 유지한다. `document`는 `id`, `title`, `filename`, `doc_type`과 함께 파이프라인이 읽는 `file_path`를 모두 가져야 한다(`get_document()`가 제공).
- 실제 PDF 3개의 청크가 `Indexer.prepare()` 검증을 통과하고, 가짜 저장소로 `IngestPipeline`이 완료 기록까지 가는 것을 테스트로 확인했다. 실제 ChromaDB 서버 저장과 실제 임베딩 호출은 확인하지 않았다.
- `Indexer.prepare()`가 청크에서 검사하는 조건: `text`는 공백이 아닌 문자열, `source`는 비어 있지 않은 `str`, `page`는 1 이상 `int`, `chunk`는 0 이상 `int`, `document_id`·`document_type`은 문서와 같은 값, 값은 `str/int/float/bool`만, 같은 `(page, chunk)`는 한 번만. 이 조건을 어기면 `ValueError`다.
- 스캔본은 `ScannedPdfError`로 오고, `pipeline._error_text`는 `IngestError` 외 예외를 "예외이름 (see server log)"로만 기록한다. 박정환의 어댑터가 사용자용 문구로 바꾼다.
- 완료할 때 `set_status(id, "COMPLETED", chunk_count=저장한 청크 수)`로 청크 수를 넘긴다.

### 7.2 문서관리 → 박정환 (`DocumentService`)

> DB 정의가 바뀌었을 수 있다. §7.4의 "변경 확인 필요"를 먼저 본다.

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
- **컬렉션은 기술 `tech_docs`, 안전 `safety_docs`로 확정**됐다(박정환 전달). QA의 `retriever.py`(`config.MANUAL_COLLECTION`)도 기본값이 `tech_docs`로 같음을 확인했다(#83).
- `ids`, `embeddings`, `documents`, `metadatas`는 같은 길이여야 하고, 같은 id를 다시 보내면 덮어쓴다(upsert).
- 컬렉션은 처음 저장할 때 임베딩 차원이 고정된다. 다른 차원은 저장하지 않는다.
- **거리 방식은 L2(Chroma 기본값)로 둔다.** QA의 `distance_to_similarity`가 `1 - d/2`로 L2를 가정하므로, cosine 컬렉션을 만들면 유사도가 틀려진다. 바꾸려면 QA와 먼저 합의한다.
- 두 서버에는 현재 인증이 없다. 자세한 사용법은 `docs/VectorDBConnector.md`를 따른다.

### 7.4 문서관리 → MySQL

> **변경 확인 필요:** DB 담당이 이후 전달한 정의(`documents_info`)는 아래 표와 다르다. 컬럼은 `filename`(확장자 포함 여부 불명), `document_type`, `department_id`(NULL 허용), `status` ENUM(`PROCESSING`/`COMPLETED`/`FAILED`), `upload_at`, `updated_at`이고, 중복 판정은 `UNIQUE (filename, document_type)`이다. `title_hash`, `chunk_count`, 원본 경로, 실패 사유 컬럼은 없다. 인덱스 `idx_documents_status_created`가 테이블에 없는 컬럼 `created_at`을 가리켜서 그대로는 만들어지지 않는다. 어느 정의가 최종인지 DB 담당이 확인하면 §3.2, §3.3, §7.2, §7.4를 함께 고친다.

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
- 질문에 부위·작업이 없으면 분류표 부위를 선택지로 되묻는다(`clarify_policy.py`). 분류표가 35개로 늘어서 선택지는 분류표 앞쪽 `MAX_PART_OPTIONS`(8)개까지만 보여주도록 장영균이 수정했다(QA 확인 필요, §8).
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
| 분류표를 실제 PDF 3개 용어 기준으로 확장했다(부위 37개, 작업 49개, 작업 위치 7개). 엘트론 용어로 부위 2개(적재하중 검출 모니터링 장치, 안전봉)와 동의어 `Car Door → 카문`을 더하고, `가버너 → 과속조절기`로 고쳤다. 관계표(`task_relations.json`)에는 새 작업 33개를 같은 청크에서 함께 나온 작업 위치·위험 유형 횟수로 채웠다(근거가 4개 미만인 작업과 `권상기` 계열은 비어 있다). 태그는 이 목록 안에서만 고른다. 확정 여부와 어색한 조합 정리, `task`를 **부위+동작 합친 이름**으로 유지하는 것(명세 예시의 동사 단위 `점검`과 다름) | QA·기준정보 담당 |
| 분류표 확장으로 되묻기 선택지가 35개가 되어 `clarify_policy.py`의 `build_options`를 앞쪽 8개로 줄이고 테스트를 고쳤다. 상한·자르는 방식(앞쪽부터)이 맞는지 | QA |
| 동의어 `가버너 → 조속기`의 표준 태그가 분류표에 없어서 `가버너 → 과속조절기`로 고쳤다(LLM이 `조속기`를 태그로 만들어내던 문제). 분류표의 `비상정지장치`는 PDF에 거의 안 나오고(1건) PDF는 `추락방지안전장치`(43건)를 쓴다. `조속기`·`비상정지장치`를 동의어로 넣을지 | 기준정보 담당 |
| `config.py`의 `CHUNK_SIZE`(800)·`CHUNK_OVERLAP`(100)은 QA의 `util/rag_ingest.py`(테스트용 적재)만 쓴다. 문서관리 청킹(`features/processing/`)은 300~1,200자, 겹침 없음으로 따로 정했다. 두 기준 중 정식 기준과 설정 정리 방법 | QA |
| `chunk`를 0부터 시작하는 것, `model`·`clause` 같은 키가 없는 청크의 처리 | QA |
| QA의 `util/rag_*` 기본 임베딩(`test_embed_with_openai`)을 `core.llm.embed`로 통일할 시점, `core.llm.embed`에 빈 문자열·차원(3072) 검사를 추가할지 | QA |
| 상태 전이 검증 수용 여부, 삭제 중간 실패 처리 | 박정환 |
| `data/master/equipment_models.csv`에 실제 설비 모델(제조사·모델명·정격 속도·하중·용도·구동 방식) 채우기. 지금은 자리표시자라 `model` 없이 저장된다 | 박정환(CSV 작성), 장영균(PDF에서 인식되는 표기 제공) |
| `model` 키가 없는 청크(모델이 안 나오는 페이지)를 모델 필터가 제외해도 되는지. 모델별 복제 청크는 그대로 두기로 합의함 | QA |
| 안전기준 수식(`HyhwpEQ` 글리프) 복원 방식과 시점 | 장영균 |
| 도면 페이지에 OCR/Vision을 추가할지 | 팀 합의 |

## 9. 작업 규칙

1. 실제 저장소에서 확인하지 못한 파일, 함수, DB 필드를 있다고 가정하지 않는다. 필요한 정보가 없으면 보고하고 요청한다.
2. 담당이 아닌 파일은 요청 없이 수정하지 않는다. 특히 박정환의 화면·파이프라인·`Indexer` 파일, QA의 `util/rag_*.py`와 `features/retrieval/`, 공용 DB 설정, `core/llm.py`는 담당자와 합의한 뒤에 바꾼다.
3. ChromaDB 데이터 구조, 컬렉션 이름, MySQL 스키마를 독자적으로 정하거나 바꾸지 않는다. 기존 마이그레이션 파일을 고치지 않고 새 번호 파일로 추가한다.
4. 문서 유형은 `tech`/`secure`, 메타데이터 키 `source`/`page`/`chunk`는 이름과 타입을 유지한다.
5. 비밀값(API 키, DB 접속 정보)은 환경변수로만 다루고 코드·로그·커밋에 남기지 않는다.
6. 구현 후에는 단위 테스트를 실행하고, 실행한 결과만 성공으로 보고한다.
7. `main` 직접 푸시 금지. 커밋·푸시·PR은 요청이 있을 때만 한다. 커밋 메시지는 Conventional Commits 형식이다.
