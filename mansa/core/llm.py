from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config import EMBEDDING_MODEL, LLM_API_KEY, LLM_MODEL #config.py가 .env에서 읽어 둔 값을 가져온다.

_chain: Runnable | None = None #OpenAi 연결 객체를 담아 둘 보관함

def _get_chain() -> Runnable: #연결 객체를 꺼내 주는 함수. ask가 질문할 때마다 이 함수를 부른다.
    """처음 호출할 때 프롬프트 → LLM → 문자열 변환 체인을 만들고 이후에는 재사용한다.

    .env에 LLM_API_KEY나 LLM_MODEL이 없으면 API를 호출하기 전에 RuntimeError를 발생시킨다.
    오류 메시지에는 키 값을 넣지 않는다.
    """
    global _chain #함수 안에서 바깥에 있는 보관함 변수를 바꾸겠다는 선언
    if not LLM_API_KEY or not LLM_MODEL: #.env에 LLM_API_KEY나 LLM_MODEL이 없으면 RuntimeError를 일으키겠다.
        raise RuntimeError("LLM_API_KEY or LLM_MODEL is not set in .env")
    if _chain is None: #클라이언트 보관함이 비어있으니 연결 객체를 만들어서 넣어라
        prompt = ChatPromptTemplate.from_messages(
            [MessagesPlaceholder("history"), ("human", "{question}")]
        )
        model = ChatOpenAI(model=LLM_MODEL, api_key=LLM_API_KEY)
        _chain = prompt | model | StrOutputParser()
    return _chain

def ask(question: str, history: list[dict] | None = None) -> str:
    """질문을 LLM에 보내고 답변 텍스트를 반환한다.

    history는 같은 대화의 이전 질문·답변 목록이다({"role": "user"|"assistant", "content": str}).
    함께 보내 LLM이 앞의 대화를 이어서 답하게 한다. history는 변경하지 않는다.
    외부 API를 호출한다. 인증 실패·네트워크 오류는 openai 예외로 그대로 전달된다.
    """

    return _get_chain().invoke({"question": question, "history": history or []})

_embeddings: OpenAIEmbeddings | None = None #임베딩 모델 객체를 담아 둘 보관함

def _get_embeddings() -> OpenAIEmbeddings: #임베딩 모델 객체를 꺼내 주는 함수. embed가 부를 때마다 쓴다.
    """처음 호출할 때 임베딩 모델 객체를 만들고 이후에는 재사용한다.

    모델은 생성형 LLM(LLM_MODEL)과 별도인 EMBEDDING_MODEL(기본 text-embedding-3-large, 3072차원)이다.
    .env에 LLM_API_KEY가 없으면 API를 호출하기 전에 RuntimeError를 발생시킨다.
    오류 메시지에는 키 값을 넣지 않는다.
    """
    global _embeddings #함수 안에서 바깥에 있는 보관함 변수를 바꾸겠다는 선언
    if not LLM_API_KEY: #.env에 LLM_API_KEY가 없으면 RuntimeError를 일으키겠다.
        raise RuntimeError("LLM_API_KEY is not set in .env")
    if _embeddings is None: #보관함이 비어있으니 임베딩 모델 객체를 만들어서 넣어라
        _embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=LLM_API_KEY)
    return _embeddings

def embed(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터 목록으로 바꾼다. 결과는 입력과 같은 순서다.

    빈 목록이면 API를 부르지 않고 빈 목록을 반환한다. 유료 외부 API(OpenAI)를 호출한다.
    벡터 DB에 올린 문서와 같은 모델이어야 검색이 맞는다. 모델을 바꾸면 문서를 다시 임베딩해야 한다.
    인증 실패·네트워크 오류는 openai 예외로 그대로 전달된다. texts는 변경하지 않는다.
    """
    if not texts: #보낼 문장이 없으면 돈 드는 호출을 하지 않는다.
        return []
    return _get_embeddings().embed_documents(texts)