import openai
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_openai.chat_models.base import OpenAIRefusalError
from pydantic import BaseModel

from config import (  #config.py가 .env에서 읽어 둔 값을 가져온다.
    EMBEDDING_MODEL,
    LLM_API_KEY,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT,
)
from core.exceptions import LlmError

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

# 다시 시도하면 나아질 수 있는 오류. pydantic ValidationError(응답이 형식과 다름)도 ValueError의 한 종류다.
_RETRYABLE_ERRORS = (ValueError, openai.LengthFinishReasonError, openai.APITimeoutError)

_model: ChatOpenAI | None = None #구조화 응답에 쓸 LLM 객체를 담아 둘 보관함

def _get_model() -> ChatOpenAI: #LLM 객체를 꺼내 주는 함수. complete가 부를 때마다 쓴다.
    """처음 호출할 때 시간 제한을 건 LLM 객체를 만들고 이후에는 재사용한다.

    재시도 횟수를 complete가 직접 세도록 SDK 자체 재시도는 끈다(max_retries=0).
    .env에 LLM_API_KEY나 LLM_MODEL이 없으면 API를 호출하기 전에 RuntimeError를 발생시킨다.
    """
    global _model #함수 안에서 바깥에 있는 보관함 변수를 바꾸겠다는 선언
    if not LLM_API_KEY or not LLM_MODEL:
        raise RuntimeError("LLM_API_KEY or LLM_MODEL is not set in .env")
    if _model is None: #보관함이 비어있으니 LLM 객체를 만들어서 넣어라
        _model = ChatOpenAI(
            model=LLM_MODEL, api_key=LLM_API_KEY, timeout=LLM_TIMEOUT, max_retries=0
        )
    return _model

#대화 이력 뒤에 이번 질문을 붙이는 프롬프트, history가 비어 있으면 질문만 보낸다.
_PROMPT = ChatPromptTemplate.from_messages([MessagesPlaceholder("history"), ("human", "{question}")])

def _get_chain(schema: type[BaseModel]) -> Runnable: #complete가 부를 때마다 응답 형식에 맞는 체인을 만든다.
    """대화 이력 -> 프롬프트 -> schema 형식 응답으로 이어지는 체인을 만든다.
    
    schema가 호출마다 달라 체인은 저장하지 않고, 비용이 드는 LLM객체는 _get_model()로 재사용한다.
    """
    return _PROMPT | _get_model().with_structured_output(schema)

def complete(workflow: str, prompt: str, schema: type[BaseModel], history: list[dict] | None = None) -> dict:
    """프롬프트를 LLM에 보내 schema 형식의 응답을 받아 dict로 반환한다.

    workflow는 호출한 기능 이름("L2" 기술 Q&A, "L3" 고객센터)이며 지금은 오류 메시지에만 쓴다.
    history는 같은 대화의 이전 질문·답변 목록이다 ({"role": "user"|"assistant", "content": str}).
    함께 보내 LLM이 앞의 대화를 이어서 답하게 한다. 없으면 prompt만 보낸다. history는 변경하지 않는다.
    응답이 형식에 맞지 않거나, 길이 제한으로 잘리거나, 시간이 초과되면 LLM_MAX_RETRIES번까지
    다시 시도하고, 그래도 실패하면 LlmError를 발생시킨다(원인 예외는 __cause__에 남는다).
    LLM이 요청을 거부하면 다시 시도하지 않고 바로 LlmError다. 인증 실패 같은 다른 오류는
    다시 시도하지 않고 openai 예외로 그대로 전달된다. 유료 외부 API(OpenAI)를 호출한다.
    """
    chain = _get_chain(schema)
    for _ in range(1 + LLM_MAX_RETRIES):
        try:
            return chain.invoke({"question": prompt, "history": history or []}).model_dump()
        except OpenAIRefusalError as exc: #같은 질문은 다시 보내도 거부될 가능성이 높다.
            raise LlmError(f"{workflow} LLM refused the request") from exc
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
    raise LlmError(f"{workflow} LLM failed after {1 + LLM_MAX_RETRIES} attempts") from last_error

def choose_tool(
    workflow: str,
    system: str,
    question: str,
    tools: list[type[BaseModel]],
    history: list[dict] | None = None,
) -> AIMessage:
    """도구(tools)를 붙인 LLM에 system 지시, 이전 대화, 질문을 차례로 보내 응답 메시지를 반환한다.

    LLM이 도구를 고르면 응답의 tool_calls에 도구 이름과 인자가 담기고, 고르지 않으면 본문에 답변이 담긴다.
    도구를 실행하거나 결과를 다시 보내지 않는다(호출은 한 번). 본문은 문자열이 아니라 블록 목록일 수 있어
    텍스트는 호출자가 AIMessage.text로 꺼낸다. history는 complete()와 같은 형식이며 변경하지 않는다.
    시간 초과는 LLM_MAX_RETRIES번까지 다시 시도하고 그래도 실패하면 LlmError를 발생시킨다.
    다른 오류는 openai 예외로 그대로 전달된다. 유료 외부 API(OpenAI)를 호출한다.
    """
    model = _get_model().bind_tools(tools)
    messages = [
        {"role": "system", "content": system},
        *(history or []),
        {"role": "user", "content": question},
    ]
    for _ in range(1 + LLM_MAX_RETRIES):
        try:
            return model.invoke(messages)
        except openai.APITimeoutError as exc:
            last_error = exc
    raise LlmError(f"{workflow} LLM timed out after {1 + LLM_MAX_RETRIES} attempts") from last_error
