from collections.abc import Sequence
from typing import Literal

from mansa.util.server_connection import get_secure_client, get_tech_client

DocType = Literal["tech", "secure"]

# 문서 종류별로 접속할 벡터 DB를 정한다. 새 종류가 생기면 여기에 추가한다.
_CLIENT_GETTERS = {"tech": get_tech_client, "secure": get_secure_client}


def upload_embeddings(
    doc_type: DocType,
    collection_name: str,
    ids: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    documents: Sequence[str] | None = None,
    metadatas: Sequence[dict] | None = None,
) -> int:
    """임베딩을 문서 종류에 맞는 벡터 DB 컬렉션에 저장하고 저장한 개수를 반환한다.

    doc_type이 "tech"면 기술 벡터 DB, "secure"면 안전 벡터 DB로 보낸다.
    알 수 없는 doc_type이나 길이가 서로 다른 입력은 ValueError를 발생시키며 DB에는 접속하지 않는다.
    같은 id가 이미 있으면 덮어쓰므로(upsert) 같은 데이터를 다시 보내도 중복되지 않는다.
    컬렉션이 없으면 새로 만든다. 서버 접속 실패는 호출자에게 그대로 전달된다.
    """
    if doc_type not in _CLIENT_GETTERS:
        raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(_CLIENT_GETTERS)}")
    for name, values in (("embeddings", embeddings), ("documents", documents), ("metadatas", metadatas)):
        if values is not None and len(values) != len(ids):
            raise ValueError(f"{name} length {len(values)} does not match ids length {len(ids)}")
    if not ids:
        return 0

    # 이미 계산한 임베딩을 넣으므로 서버/클라이언트 쪽 기본 임베딩 함수는 쓰지 않는다.
    collection = _CLIENT_GETTERS[doc_type]().get_or_create_collection(
        collection_name, embedding_function=None
    )
    collection.upsert(
        ids=list(ids),
        embeddings=[list(e) for e in embeddings],
        documents=list(documents) if documents is not None else None,
        metadatas=list(metadatas) if metadatas is not None else None,
    )
    return len(ids)
