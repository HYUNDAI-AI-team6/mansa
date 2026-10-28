import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "text-embedding-3-large"

# LLM 응답을 기다리는 최대 시간(초)과, 형식 오류·시간 초과 때 다시 시도할 횟수
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT") or 30)
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES") or 2)


TECH_CHROMA_HOST = os.getenv("TECH_CHROMA_HOST")
SECURE_CHROMA_HOST = os.getenv("SECURE_CHROMA_HOST")
# Railway 공개 도메인은 8000이 아니라 HTTPS(포트)로 접속한다. (8000은 컨테이너 내부 포트)
CHROMA_PORT = int(os.getenv("CHROMA_PORT"))

