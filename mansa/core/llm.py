from openai import OpenAI

from config import LLM_API_KEY, LLM_MODEL #config.py가 .env에서 읽어 둔 값을 가져온다.

_client: OpenAI | None = None #OpenAi 연결 객체를 담아 둘 보관함

def _get_client() -> OpenAI: #연결 객체를 꺼내 주는 함수. ask가 질문할 때마다 이 함수를 부른다.
    """처음 호출할 때 OpenAI 클라이언트를 만들고 이후에는 재사용한다.
    
    .env에 LLM_API_KEY나 LLM_MODEL이 없으면 API를 호출하기 전에 RuntimeError를 발생시킨다.
    오류메시지에는 키 값을 넣지 않는다.
    """
    global _client #함수 안에서 바깥에 있는 보관함 변수를 바꾸겠다는 선언
    if not LLM_API_KEY or not LLM_MODEL: #.env에 LLM_API_KEY나 LLM_MODEL이 없으면 RuntimeError를 일으키겠다.
        raise RuntimeError("LLM_API_KEY or LLM_MODEL은 .env에 적혀있지 않다.")
    if _client is None: #클라이언트 보관함이 비어있으니 연결 객체를 만들어서 넣어라
        _client = OpenAI(api_key=LLM_API_KEY)
    return _client

def ask(question: str) -> str:
    """질문 하나를 LLM에 보내고 답변 텍스트를 반환한다.
    외부 API를 호출한다. 인증 실패, 네트워크 오류는 openai 예외로 그대로 전달된다.
    """
    response = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content or ""