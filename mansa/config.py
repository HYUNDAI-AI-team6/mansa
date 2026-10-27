import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")


TECH_CHROMA_HOST = os.getenv("TECH_CHROMA_HOST")
SECURE_CHROMA_HOST = os.getenv("SECURE_CHROMA_HOST")
# Railway 공개 도메인은 8000이 아니라 HTTPS(포트)로 접속한다. (8000은 컨테이너 내부 포트)
CHROMA_PORT = int(os.getenv("CHROMA_PORT"))

