# UI에서 벡터 DB로 보내기

임베딩된 문서를 문서 종류에 따라 기술 벡터 DB 또는 안전 벡터 DB로 보내는 함수의 사용법이다.
UI는 `upload_embeddings` 하나만 호출하면 되고, 어느 DB로 갈지는 함수가 정한다.

## 준비

```powershell
uv sync --locked
```

접속 주소는 코드에 없고 `mansa/.env`에서 읽는다. `mansa/.env.example`을 복사해 `mansa/.env`를 만든다.
호스트가 비어 있으면 접속 시 `RuntimeError`가 발생한다.

| 환경변수 | 값 | 설명 |
|---|---|---|
| `TECH_CHROMA_HOST` | `techchromadb-production.up.railway.app` | 기술 벡터 DB 주소 |
| `SECURE_CHROMA_HOST` | `securechromadb-production.up.railway.app` | 안전 벡터 DB 주소 |
| `CHROMA_PORT` | `443` (생략 시 기본값) | HTTPS 포트. 8000은 Railway 내부 포트라 외부에서 접속되지 않는다 |

## 함수

```python
from util.vector_upload import upload_embeddings

n = upload_embeddings(doc_type, collection_name, ids, embeddings, documents, metadatas)
```

| 인자 | 타입 | 설명 |
|---|---|---|
| `doc_type` | `"tech"` 또는 `"secure"` | `tech`는 기술 DB, `secure`는 안전 DB로 보낸다 |
| `collection_name` | `str` | 저장할 컬렉션 이름. 없으면 새로 만든다 |
| `ids` | `list[str]` | 문서 id. 같은 id를 다시 보내면 덮어쓴다 |
| `embeddings` | `list[list[float]]` | 이미 계산된 임베딩. `ids`와 같은 길이 |
| `documents` | `list[str]` 또는 `None` | 원문 텍스트. 주면 `ids`와 같은 길이 |
| `metadatas` | `list[dict]` 또는 `None` | 문서명, 페이지 등 출처 정보. 주면 `ids`와 같은 길이 |

반환값은 저장한 개수(`int`)다. `ids`가 비어 있으면 서버에 접속하지 않고 `0`을 반환한다.

## 컬렉션 이름

| 문서 종류 | `doc_type` | 컬렉션 |
|---|---|---|
| 기술문서 | `tech` | `tech_docs` |
| 안전문서 | `secure` | `safety_docs` |

## UI에서 쓰는 방법

화면에서 고른 문서 종류를 `doc_type`으로 바꿔 넘기면 된다. 아래는 Gradio를 가정한 예시이며
**실행해 보지 않았다.** Gradio는 아직 프로젝트에 설치되어 있지 않다(`uv add gradio` 필요).


예시의 파일 형식은 `tests_live/sample.json`의 한 종류 분량(`[{"id", "text", "emb", "meta"}, ...]`)이다.
실제 입력 형식이 다르면 `upload_embeddings`에 넘기는 부분만 맞추면 된다.

## 오류 처리

| 상황 | 결과 | UI 처리 |
|---|---|---|
| `doc_type`이 `tech`/`secure`가 아님 | `ValueError` | 입력 오류로 안내 |
| 인자 길이가 서로 다름 | `ValueError` | 입력 오류로 안내 |
| 서버에 접속하지 못함 | chromadb 예외가 그대로 전달됨 | 전송 실패로 안내 |
| 임베딩 차원이 컬렉션과 다름 | chromadb 예외가 그대로 전달됨 | 전송 실패로 안내 |

입력 오류는 DB에 접속하기 전에 발생하므로 서버에는 아무것도 저장되지 않는다.

## 주의

- 컬렉션은 처음 저장할 때 임베딩 차원이 고정된다. 임베딩 모델을 바꾸면 컬렉션을 새로 만들어야 한다.
- 한 번에 보내는 개수 제한은 두지 않았다. 수천 건 이상은 나눠서 호출한다. 대량 전송은 검증하지 않았다.
- 두 서버에는 현재 인증이 없다. 접속 주소를 아는 사람은 누구나 읽고 쓸 수 있다.

## 확인 방법

저장 결과를 로컬 파일로 내려받아 볼 수 있다. 서버 내용을 `dump/` 폴더의 JSON으로 저장한다.

```powershell
uv run --locked python -m util.dump_collections
```

실서버에 임시 컬렉션을 만들어 업로드와 dump를 검증하는 테스트는 아래로 실행한다.
`RUN_LIVE`가 없으면 건너뛴다.

```powershell
$env:RUN_LIVE="1"; uv run --locked python -m unittest tests_live.test_live_upload_dump -v
```
