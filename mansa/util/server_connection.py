import chromadb
from chromadb.api import ClientAPI

from config import CHROMA_PORT, SECURE_CHROMA_HOST, TECH_CHROMA_HOST


def _connect(host: str | None) -> ClientAPI:
    """지정한 Railway Chroma 서버에 HTTPS로 접속해 클라이언트를 반환한다.

    host는 mansa/.env의 TECH_CHROMA_HOST, SECURE_CHROMA_HOST 값이다. 비어 있으면 RuntimeError를
    발생시킨다. 접속 직후 heartbeat를 호출해 연결을 확인하므로 서버에 닿지 않으면 예외가 발생한다.
    """
    if not host:
        raise RuntimeError("Chroma host is not set; check TECH_CHROMA_HOST/SECURE_CHROMA_HOST in mansa/.env")
    client = chromadb.HttpClient(host=host, port=CHROMA_PORT, ssl=True)
    client.heartbeat()
    return client


def get_tech_client() -> ClientAPI:
    """기술 벡터 DB 클라이언트를 반환한다."""
    return _connect(TECH_CHROMA_HOST)


def get_secure_client() -> ClientAPI:
    """안전 벡터 DB 클라이언트를 반환한다."""
    return _connect(SECURE_CHROMA_HOST)
