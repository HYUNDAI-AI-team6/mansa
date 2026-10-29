# 환경변수로 바꾼 설정값

코드 안에 숫자와 이름으로 박혀 있던 설정값 21개를 `mansa/config.py`에 등록해서 `.env`로 바꿀 수 있게 했다.
`.env`에 적지 않으면 아래 표의 기본값을 쓰므로, 아무것도 안 해도 동작은 이전과 같다.
**단, `EMBEDDING_MODEL`의 기본값은 이전 코드(`small`)와 달리 `large`다.** 아래 "주의할 점"을 먼저 읽는다.

## 쓰는 방법

### 값을 바꾸고 싶을 때
`mansa/.env`에 변수 이름과 값을 한 줄로 적고 앱을 다시 켠다. `config.py`는 앱을 켤 때 한 번만 읽는다.
적을 수 있는 변수는 `mansa/.env.example`에 주석(`#`)으로 모두 들어 있다. 주석을 풀고 값을 적는다.

```
CHUNK_SIZE=500
VECTOR_TOP_K=10
SAFETY_COLLECTION=my_safety_docs
```

### 코드에서 값을 읽을 때
`config`에서 가져온다. 숫자나 이름을 코드에 직접 적지 않는다.

```python
from config import CHUNK_SIZE, VECTOR_TOP_K
```

이번에 옮긴 변수는 원래 있던 모듈에서도 같은 이름으로 그대로 쓸 수 있다(그 모듈이 `config`에서 가져오기 때문이다).
예를 들어 `retriever.VECTOR_TOP_K`, `rag_ingest.CHUNK_SIZE`는 이전처럼 동작한다.

### 값의 규칙
잘못된 값은 앱을 켤 때 변수 이름과 함께 오류로 알려 주고 멈춘다. 빈 값이나 공백만 있으면 기본값을 쓴다.

| 종류 | 변수 | 허용 범위 |
|---|---|---|
| 1 이상의 정수 | `CHUNK_SIZE`, `BATCH_SIZE`, `CORPUS_PAGE_SIZE`, `VECTOR_TOP_K`, `BM25_TOP_K`, `RESULT_TOP_K`, `TAG_TOP_K`, `EVIDENCE_TOP_N` | 1 이상 |
| 1~50의 정수 | `MEMBER_MAX_LENGTH` | 1 이상 50 이하 (DB 칸 길이가 50) |
| 0 이상의 정수 | `CHUNK_OVERLAP`, `MAX_REGENERATIONS` | 0 이상. `CHUNK_OVERLAP`은 `CHUNK_SIZE`보다 작아야 한다 |
| 실수 | `MIN_EVIDENCE_SCORE` | 0 이상 1 이하 |
| 둘 중 하나 | `SAFETY_DOC_TYPE`, `MANUAL_DOC_TYPE` | `tech` 또는 `secure` |
| 쉼표로 나눈 이름 | `TAG_KEYS` | 빈 이름 없이 `part,task`처럼 적는다 |
| 문자열 | `EMBEDDING_MODEL`, `SAFETY_COLLECTION`, `MANUAL_COLLECTION`, `DEFAULT_CONTACT`, `ADMIN_DEPT_LABEL` | 비어 있지 않은 글자 |
| 경로 | `EVAL_ROOT`, `TESTSET_PATH`, `SAVE_DIR` | 절대 경로 또는 저장소 루트 기준 상대 경로 |

## 바뀐 변수 목록

모두 이전에는 아래 "이전 위치"의 파일 안에 직접 적혀 있었고, 지금은 `config.py`에서 읽는다.

### 임베딩·청킹 (문서를 올릴 때)

| 변수 | 기본값 | 설명 | 이전 위치 | 값을 읽는 곳 |
|---|---|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-large` | 임베딩에 쓰는 OpenAI 모델 | `util/rag_ingest.py` | `rag_ingest.test_embed_with_openai` (올릴 때와 `rag_query`의 검색 질문 변환이 같은 함수를 쓴다) |
| `CHUNK_SIZE` | `800` | 청크 한 개의 최대 글자 수 | `util/rag_ingest.py` | `rag_ingest.test_chunk_units` |
| `CHUNK_OVERLAP` | `100` | 이웃한 청크가 겹치는 글자 수 | `util/rag_ingest.py` | `rag_ingest.test_chunk_units` |
| `BATCH_SIZE` | `100` | 임베딩 호출과 업로드를 나누는 개수 | `util/rag_ingest.py` | `rag_ingest.test_ingest_file` |

### 검색 (질문에 맞는 문서를 찾을 때)

| 변수 | 기본값 | 설명 | 이전 위치 | 값을 읽는 곳 |
|---|---|---|---|---|
| `SAFETY_DOC_TYPE` | `secure` | 안전 문서가 있는 벡터 DB(`tech` 기술 DB / `secure` 안전 DB) | `features/retrieval/retriever.py` | `retriever.search_safety` |
| `SAFETY_COLLECTION` | `safety_docs` | 안전 문서 컬렉션 이름 | `features/retrieval/retriever.py` | `retriever.search_safety` |
| `MANUAL_DOC_TYPE` | `tech` | 매뉴얼이 있는 벡터 DB | `features/retrieval/retriever.py` | `retriever.search_manual` |
| `MANUAL_COLLECTION` | `tech_docs` | 매뉴얼 컬렉션 이름 | `features/retrieval/retriever.py` | `retriever.search_manual` |
| `CORPUS_PAGE_SIZE` | `500` | 말뭉치를 한 번에 읽어 오는 청크 수 | `features/retrieval/retriever.py` | `retriever.load_corpus` |
| `VECTOR_TOP_K` | `20` | 벡터(의미) 검색 결과 개수 | `features/retrieval/retriever.py` | `retriever.search_vector` |
| `BM25_TOP_K` | `20` | 키워드(BM25) 검색 결과 개수 | `features/retrieval/retriever.py` | `retriever.search_bm25` |
| `RESULT_TOP_K` | `20` | 합친 검색 결과 중 남기는 개수 | `features/retrieval/retriever.py` | `retriever.to_scored_chunks` |
| `TAG_TOP_K` | `20` | 태그 순위 결과 개수 | `features/retrieval/retriever.py` | `retriever.rank_by_tags` |
| `TAG_KEYS` | `part,task` | 청크 메타데이터에서 태그 값을 꺼낼 때 쓰는 키 이름(부위·작업). 값은 쉼표로 구분한 문자열이어야 한다 | `features/retrieval/retriever.py` | `retriever.chunk_tags` (태그 순위 `rank_by_tags`가 사용) |
| `EVIDENCE_TOP_N` | `8` | 답변에 쓸 근거 청크 개수 | `features/retrieval/retriever.py` | `retriever.merge_evidence` |

### 답변 품질

| 변수 | 기본값 | 설명 | 이전 위치 | 값을 읽는 곳 |
|---|---|---|---|---|
| `MIN_EVIDENCE_SCORE` | `0.3` | 근거가 충분하다고 보는 최소 점수(0~1) | `features/qa/answer_guard.py` | `answer_guard.is_sufficient` |
| `DEFAULT_CONTACT` | `안전관리팀` | 답변할 수 없을 때 안내하는 담당 부서 이름 | `features/qa/answer_guard.py` | `answer_guard.build_no_answer` |
| `MAX_REGENERATIONS` | `2` | 근거 검사에 실패했을 때 답변을 다시 만드는 횟수 | `features/qa/service.py` | `service._generate_verified` |

### 회원 관리

| 변수 | 기본값 | 설명 | 이전 위치 | 값을 읽는 곳 |
|---|---|---|---|---|
| `MEMBER_MAX_LENGTH` | `50` | 회원 아이디·이름의 최대 글자 수(DB 칸 길이 50 이하) | `features/auth/membersmanage.py` | `membersmanage._clean` |
| `ADMIN_DEPT_LABEL` | `관리자` | 부서가 없는 관리자를 목록에 보여 줄 부서 이름 | `features/auth/membersmanage.py` | `membersmanage.list_members` |

### 평가 파일 위치

| 변수 | 기본값 | 설명 | 이전 위치 | 값을 읽는 곳 |
|---|---|---|---|---|
| `EVAL_ROOT` | 저장소 루트의 `eval/` | 평가 파일을 두는 기준 폴더 | `features/evaluation/storage.py` | 아래 두 값의 기준 |
| `TESTSET_PATH` | `EVAL_ROOT/testsets/tech_qa.json` | 평가에 쓰는 질문·정답 파일 | `features/evaluation/storage.py` | `runner.run_evaluation`, `runner.rescore`, `ui/evaluation._testset_info` |
| `SAVE_DIR` | `EVAL_ROOT/save` | 평가 결과(JSON·CSV)를 저장하는 폴더 | `features/evaluation/storage.py` | `app.main`(화면이 파일을 열 수 있게 허용), `runner.run_evaluation`·`rescore`, `storage.new_run_id`·`save_answers`·`save_report`·`load_latest`·`latest_csv` |

- `EVAL_ROOT`만 바꾸면 `TESTSET_PATH`와 `SAVE_DIR`가 같이 따라간다. 따로 적으면 적은 값이 우선한다.
- 상대 경로는 실행 위치(cwd)가 아니라 **저장소 루트** 기준이다.

## 어디에 어떤 값을 써야 하는가

| 하고 싶은 일 | 바꿀 변수 |
|---|---|
| 문서를 더 잘게/크게 나눈다 | `CHUNK_SIZE`, `CHUNK_OVERLAP` |
| 검색 결과를 더 많이/적게 가져온다 | `VECTOR_TOP_K`, `BM25_TOP_K`, `RESULT_TOP_K`, `TAG_TOP_K` |
| 답변에 붙는 근거 개수를 바꾼다 | `EVIDENCE_TOP_N` |
| "문서에서 찾을 수 없다"가 너무 자주/드물게 나온다 | `MIN_EVIDENCE_SCORE` |
| 답변 재생성 횟수를 바꾼다 | `MAX_REGENERATIONS` |
| 다른 컬렉션에 올린 문서를 검색한다 | `SAFETY_COLLECTION`, `MANUAL_COLLECTION` (올릴 때 `test_ingest_file`에 넘긴 이름과 같아야 한다) |
| 안내 문구의 담당 부서를 바꾼다 | `DEFAULT_CONTACT` |
| 평가 결과를 다른 폴더에 저장한다 | `SAVE_DIR` (또는 `EVAL_ROOT`) |
| 다른 평가 질문 파일을 쓴다 | `TESTSET_PATH` |

## 주의할 점

- **`EMBEDDING_MODEL` 기본값이 바뀌었다.** 이전 코드는 `text-embedding-3-small`(차원 1536)이었고, 지금 기본값은 `text-embedding-3-large`(차원 3072)다.
  이미 `small`로 올린 컬렉션이 있으면 `large`로는 올릴 수도 검색할 수도 없다(차원이 달라 오류가 난다).
  쓰던 모델이 `small`이면 `.env`에 `EMBEDDING_MODEL=text-embedding-3-small`을 적는다.
  올릴 때와 검색할 때 같은 모델이어야 하므로 모델을 바꾸면 컬렉션을 새로 만들어 다시 올린다.
- **컬렉션 이름과 문서 종류는 올리는 쪽과 맞춰야 한다.** `SAFETY_COLLECTION` 등을 바꾸기만 하고 문서를 그 이름으로 올리지 않으면 검색 결과가 비어 있다.
- **`TAG_KEYS`는 문서를 올릴 때 넣은 메타데이터 키와 같아야 한다.** `retriever.chunk_tags`가 청크 메타데이터에서 이 키로 태그를 꺼내 질문의 부위·작업과 겹치는 개수로 순위를 매긴다.
  청크에 없는 키를 적어도 오류는 나지 않고 그 청크에 태그가 없는 것으로 처리되어, 태그 순위에서 빠질 뿐이다.
  (지금 코드는 키 값이 `"브레이크,도어"`처럼 쉼표로 구분한 문자열이라고 가정한다.)
- **`.env`를 고치면 앱을 다시 켠다.** 켜져 있는 동안은 바뀌지 않는다.
- **테스트와의 관계:** `tests/test_eval_storage.py`는 `EVAL_ROOT`가 저장소 루트 아래 `eval/`일 것을, `tests/test_eval_testset.py`는 그 아래 `testsets/tech_qa.json`이 있을 것을 전제로 한다. `.env`에 `EVAL_ROOT`를 다른 곳으로 적으면 실패한다. 저장소 안의 다른 폴더(예: `my_eval`)로 바꾸면 `tech_qa.json`을 못 찾아 `test_eval_testset.py`의 한 테스트(`test_bundled_testset_is_valid`)만 실패하고,
  저장소 밖으로 바꾸면 `test_eval_storage.py`의 검사도 같이 실패한다. 테스트를 돌릴 때는 `EVAL_ROOT`를 `.env`에서 빼 둔다.
- 이전부터 `config.py`에 있던 `DATABASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `TECH_CHROMA_HOST`, `SECURE_CHROMA_HOST`, `CHROMA_PORT`는 이 문서의 대상이 아니다. 이 문서는 새로 옮긴 21개만 다룬다.

## 새 환경변수를 추가하는 방법

1. `config.py`에 읽는 줄을 추가한다. 형에 맞는 도우미를 쓴다: `_env_str`(문자열), `_env_int`(정수), `_env_float`(실수), `_env_path`(경로), `_env_choice`(허용 값 중 하나), `_env_tuple`(쉼표 목록).
   ```python
   MAX_MB = _env_int("MAX_MB", 50, minimum=1)
   ```
2. 쓰는 모듈에서 `from config import MAX_MB`로 가져온다. 값을 코드에 직접 적지 않는다.
3. `.env.example`에 같은 이름을 주석으로 추가하고 기본값과 설명을 적는다.
4. 값이 서로 영향을 주는 변수(예: `CHUNK_OVERLAP < CHUNK_SIZE`)는 `config.py`에서 켤 때 함께 검사한다.

## 이번에 환경변수로 바꾸지 않은 것

- 화면 구조에 묶인 값(예: `ui/qa.py`의 `OUTPUT_COUNT`)과 DB 컬럼 길이에 묶인 값(예: `ui/master.py`의 `MAX_LENGTH`)은 환경변수로 바꾸면 화면이나 저장이 깨진다.
- 한 파일에서만 쓰는 값(`MAX_MB`, `CODEX_TIMEOUT_SEC`, `TARGET_PERCENT` 등)은 이번 대상에 없어서 그대로 코드에 있다.
- 화면 문구, 프롬프트, 색·표 칸 같은 디자인 값은 환경마다 바꿀 값이 아니라서 대상이 아니다.
