# RAG 코드 내부 작동 원리 (rag_ingest, rag_query)

`mansa/util/rag_ingest.py`(올리기)와 `mansa/util/rag_query.py`(조회·검색)가 함수 단위로 어떻게 동작하는지 정리한 문서다.
사용법은 [RagPipeline.md](RagPipeline.md)를 본다. 두 파일에는 클래스가 없고 모듈 수준 함수만 있다.

> `rag_ingest.py`의 함수 이름 앞에는 현재 `test_`가 붙어 있다. 이 문서도 현재 이름을 따른다.

## 전체 구조

```
test_ingest_file ──┬─ test_load_pdf / test_load_csv   파일 → 단위(텍스트, 메타데이터) 목록
                   ├─ test_chunk_units                단위 → 청크(id, 텍스트, 메타데이터) 목록
                   ├─ embed (기본: test_embed_with_openai)   텍스트 → 벡터
                   └─ upload_embeddings (vector_upload.py)    벡터 DB에 upsert

search_chunks ──┬─ get_collection (vector_upload.py)   컬렉션 가져오기
                ├─ embed (기본: test_embed_with_openai)   질문 → 벡터
                └─ collection.query                    가까운 청크 찾기

get_chunks ─────┬─ get_collection
                ├─ collection.get                      조건·id로 그대로 가져오기
                └─ _position                           정렬 키
```

`rag_query.py`는 `rag_ingest.py`의 `Embedder` 타입과 `test_embed_with_openai`만 가져다 쓴다. 올릴 때와 검색할 때 같은 임베딩 함수를 쓰게 하려는 구조다.

## rag_ingest.py

### 모듈 수준 값

| 이름 | 값 | 의미 |
|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 임베딩 모델. 벡터 차원 1536 |
| `CHUNK_SIZE` | 800 | 청크 최대 글자 수 |
| `CHUNK_OVERLAP` | 100 | 이웃한 청크가 겹치는 글자 수 |
| `BATCH_SIZE` | 100 | 임베딩 호출과 업로드를 나누는 단위 |
| `Embedder` | `Callable[[list[str]], list[list[float]]]` | 텍스트 목록을 받아 벡터 목록을 돌려주는 함수의 타입 |
| `Unit` | `tuple[str, dict]` | (원문 텍스트, 출처 메타데이터). 읽기 단계의 결과 한 건 |

### test_load_pdf(path)

PDF를 페이지 단위로 읽어 `Unit` 목록을 돌려준다.

1. `pypdf.PdfReader`로 PDF를 열고 페이지를 1부터 번호를 매기며 돈다.
2. 페이지마다 `extract_text()`로 글자를 뽑고 앞뒤 공백을 지운다. 글자가 없으면(`None` 또는 빈 문자열) 그 페이지는 건너뛴다.
3. 남은 페이지마다 `(텍스트, {"source": 파일명, "page": 번호})`를 만든다. 번호는 건너뛴 페이지를 포함한 실제 페이지 번호다.
4. 결과가 하나도 없으면 `ValueError`를 낸다. 스캔본처럼 글자가 없는 PDF를 "성공, 0건"으로 숨기지 않기 위해서다.

한계: 글자를 이미지로 담은 PDF는 읽지 못한다(OCR 없음). 표와 다단 구성은 `pypdf`가 뽑는 순서대로 나온다.

### test_load_csv(path)

CSV를 행 단위로 읽어 `Unit` 목록을 돌려준다.

1. 파일 전체를 `utf-8-sig`로 읽는다. BOM이 있는 UTF-8도 처리된다. `UnicodeDecodeError`가 나면 엑셀 한글 CSV에 흔한 `cp949`로 다시 읽는다.
2. `csv.DictReader`가 첫 줄을 헤더로 쓰고, 이후 행을 1부터 번호를 매기며 돈다.
3. 각 행에서 컬럼 이름과 값이 모두 있고 값이 공백뿐이 아닌 칸만 골라 `컬럼: 값` 줄로 만들고 줄바꿈으로 이어 붙인다.
   - 예: `제목: 서버 점검 절차\n내용: 매주 월요일 새벽 2시`
4. 줄이 하나도 없는 행(모든 값이 빈 행)은 건너뛴다. 건너뛴 행도 번호는 소비하므로 `row`는 CSV 원본의 행 번호와 일치한다.
5. 남은 행이 없으면 `ValueError`를 낸다.

행 하나를 "컬럼: 값" 텍스트로 만드는 이유는, 값만 이어 붙이면 의미를 알 수 없고 임베딩에 컬럼 이름이 문맥으로 들어가게 하려는 것이다.

### test_chunk_units(units)

`Unit` 목록을 청크로 나눠 `(id, 텍스트, 메타데이터)` 목록을 돌려준다.

1. `RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)`를 한 번 만든다.
2. 단위마다 `split_text`로 텍스트를 나눈다. 이 분할기는 `"\n\n"`, `"\n"`, `" "`, `""` 순서로 큰 구분자부터 시도해서 800자 이하가 될 때까지 쪼갠다. 문단, 줄, 단어 경계를 가능한 한 지킨다.
3. 이웃한 조각은 앞 조각의 끝 100자 안팎이 다음 조각의 앞에 겹쳐 들어간다. 경계에서 문장이 잘려도 문맥이 이어지게 하려는 것이다.
4. 청크마다 id를 만든다. PDF는 `파일명:p페이지:청크번호`, CSV는 `파일명:r행:청크번호`다. 키는 메타데이터에 `page`가 있으면 PDF, 없으면 CSV로 판단한다.
5. 메타데이터는 읽기 단계의 값에 `chunk`(그 단위 안에서 0부터의 번호)를 더한 것이다.

id가 파일 내용이 아니라 위치로 정해지므로 같은 파일을 다시 올리면 같은 id를 덮어쓴다(중복 없음). 반대로 파일이 줄어 청크 수가 줄면 남는 옛 id는 그대로 남는다.

알려진 문제: 단위 텍스트가 800자를 넘고 첫 줄이 짧으면 분할기가 줄바꿈에서 먼저 끊어서 첫 줄만 따로 청크가 된다. CSV 행의 `제목: ...` 줄이 이 경우이며 본문과 떨어져 검색에 도움이 되지 않는다.

### test_embed_with_openai(texts)

텍스트 목록을 벡터 목록으로 바꾼다.

1. `LLM_API_KEY`(config.py가 `.env`에서 읽은 값)가 비어 있으면 `RuntimeError`를 낸다.
2. 호출할 때마다 `OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=...)`를 만들어 `embed_documents(texts)`를 호출한다. 입력 순서와 같은 순서로 벡터가 나온다.

유료 외부 API 호출이다. API 오류(키 오류 401 등)는 잡지 않고 그대로 전달한다.

### test_ingest_file(path, doc_type, collection_name, embed=test_embed_with_openai)

위 함수들을 이어서 파일 하나를 올리고 올린 청크 수를 돌려준다.

1. `path`를 `Path`로 바꾼다. 확장자(소문자)가 `.pdf`/`.csv`가 아니면 `ValueError`.
2. `doc_type`이 `tech`/`secure`(`DocType`의 값)가 아니면 `ValueError`. 두 검사는 파일을 읽거나 API를 부르기 전에 한다. 잘못된 입력으로 비용이 들지 않게 하려는 것이다.
3. 확장자에 맞는 읽기 함수를 골라 `Unit` 목록을 만들고 `test_chunk_units`로 청크 목록을 만든다.
4. 청크를 `BATCH_SIZE`(100)개씩 자른다. 묶음마다
   - 텍스트를 `embed`에 넘겨 벡터를 얻고,
   - `upload_embeddings`로 id, 벡터, 텍스트, 메타데이터를 보낸다.
5. 전체 청크 수를 반환한다.

설계 이유:

- 묶음 단위로 처리하는 것은 임베딩 API와 Chroma의 한 번에 처리량 제한을 피하고 메모리를 아끼기 위해서다.
- 중간 묶음에서 실패하면 앞 묶음은 이미 저장된 상태다. 같은 파일을 다시 올리면 같은 id를 덮어써서 복구된다.
- `embed`를 인자로 받는 것은 테스트에서 가짜 임베딩을 넣어 API 없이 실행하기 위해서다.
- 임베딩이 도중에 실패하면 이미 저장된 묶음과 아직 안 올린 묶음이 섞인 상태가 된다. 전체를 하나의 트랜잭션으로 처리하지는 않는다.

## rag_query.py

### search_chunks(query, doc_type, collection_name, top_k=5, where=None, embed=...)

질문과 의미가 가까운 청크를 찾는다. 항목은 `{"id", "text", "metadata", "distance"}`다.

1. 질문이 공백뿐이면 `ValueError`, `top_k < 1`이면 `ValueError`.
2. `get_collection`으로 컬렉션을 가져온다. 이 단계에서 잘못된 `doc_type`이나 없는 컬렉션이 `ValueError`로 걸러진다.
3. 질문을 `embed([query])`로 벡터로 바꾼다. 여기서 처음 OpenAI API를 호출한다.
4. `collection.query`에 질문 벡터, `n_results=top_k`, `where`를 넘기고 문서·메타데이터·거리를 함께 요청한다.
5. Chroma가 돌려준 결과(질문이 하나이므로 `[0]`번째 묶음)를 `id, text, metadata, distance` 딕셔너리 목록으로 바꾼다.

핵심 포인트:

- 검증과 컬렉션 확인을 임베딩 호출보다 앞에 두어, 잘못된 입력에는 비용이 들지 않는다.
- `distance`는 Chroma 컬렉션의 기본 거리 방식(L2)의 값이다. 작을수록 가깝고 0~1로 정규화되어 있지 않다.
- 질문 벡터와 저장된 벡터는 같은 모델이 만든 것이어야 한다. 다르면 차원 오류가 나거나 결과가 무의미하다.
- 컬렉션이 비었거나 `where`에 맞는 청크가 없으면 빈 리스트가 나온다.

### get_chunks(doc_type, collection_name, where=None, ids=None, limit=10, offset=0)

임베딩 호출 없이 저장된 청크를 그대로 가져온다. 항목은 `{"id", "text", "metadata"}`다.

1. `limit < 1` 또는 `offset < 0`이면 `ValueError`.
2. `get_collection`으로 컬렉션을 가져온다.
3. `collection.get`에 `ids`, `where`, `limit`, `offset`을 넘기고 문서와 메타데이터를 요청한다.
4. 결과를 딕셔너리 목록으로 바꾸고 `_position` 키로 정렬해서 돌려준다.

핵심 포인트:

- 정렬은 가져온 `limit`개 안에서만 한다. 서버는 정렬 기준을 보장하지 않으므로, 청크가 `limit`보다 많으면 `offset`으로 나눠 읽어야 하고 묶음 사이의 순서는 서버가 정한 순서를 따른다.
- `where`는 Chroma의 메타데이터 필터 문법을 그대로 쓴다. 단일 조건은 `{"source": "a.pdf"}`, 여러 조건은 `{"$and": [{...}, {...}]}`다.
- `ids`를 주면 그 id의 청크만 가져온다. 없는 id는 결과에서 빠진다.

### _position(meta)

청크 메타데이터를 정렬 키 `(source, page 또는 row, chunk)`로 바꾸는 내부 함수다.

- 문자열 id로 정렬하면 `p10`이 `p2`보다 앞서므로, 번호를 정수로 비교하려고 메타데이터에서 값을 꺼내 쓴다.
- `page`가 없으면 `row`를 쓰고, 둘 다 없으면 0, `source`나 `chunk`가 없어도 각각 빈 문자열과 0을 쓴다. 메타데이터가 일부 빠진 청크가 있어도 정렬에서 오류가 나지 않게 한 것이다.

## 이 두 파일이 부르는 다른 코드

| 함수 | 파일 | 하는 일 |
|---|---|---|
| `upload_embeddings` | `vector_upload.py` | `doc_type` 검증, 길이 일치 검증, 컬렉션이 없으면 생성, `upsert`로 저장 |
| `get_collection` | `vector_upload.py` | `doc_type`으로 기술/안전 DB를 고르고 이미 있는 컬렉션을 가져옴. 없으면 `ValueError` |
| `get_tech_client`, `get_secure_client` | `server_connection.py` | 호스트와 포트(`config.py`)로 Chroma에 HTTPS 접속하고 `heartbeat`로 확인 |

컬렉션을 가져올 때는 `embedding_function=None`을 준다. 벡터를 이미 계산해서 넣고 검색에서도 직접 계산해서 넘기므로, Chroma가 기본 임베딩 모델을 따로 쓰지 않게 하려는 것이다.

## 확인한 범위

- 실서버에서 CSV와 PDF를 올리고, 청크 분할·메타데이터·검색 순위·조건 조회·페이징·오류 처리를 확인했다.
- 현재 저장소에는 자동 테스트 파일이 없다.
- 한글이 든 PDF, 대량 파일, 실제 업무 문서에서의 동작은 확인하지 못했다.
