import os


import chromadb
from chromadb.api import ClientAPI

# Railway 공개 도메인은 8000 포트가 아니라 HTTPS(443)로 접속해야 한다. (8000은 컨테이너 내부 포트)
TECH_DB_HOST = os.getenv("TECH_CHROMA_HOST", "techchromadb-production.up.railway.app")
SECURE_DB_HOST = os.getenv("SECURE_CHROMA_HOST", "securechromadb-production.up.railway.app")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "443"))


def _connect(host: str) -> ClientAPI:
    """지정한 Railway Chroma 서버에 HTTPS로 접속해 클라이언트를 반환한다.

    접속 직후 heartbeat를 호출해 연결을 확인하므로 서버에 닿지 않으면 예외가 발생한다.
    """
    client = chromadb.HttpClient(host=host, port=CHROMA_PORT, ssl=True)
    client.heartbeat()
    return client


def get_tech_client() -> ClientAPI:
    """기술 벡터 DB 클라이언트를 반환한다."""
    return _connect(TECH_DB_HOST)


def get_secure_client() -> ClientAPI:
    """안전 벡터 DB 클라이언트를 반환한다."""
    return _connect(SECURE_DB_HOST)
