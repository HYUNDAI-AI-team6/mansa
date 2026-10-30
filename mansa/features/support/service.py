"""고객센터(L3) 사용법 안내 챗봇. LLM이 안내 주제를 고르면 미리 정해 둔 안내를 원문 그대로 돌려준다.

안내 주제(id, LLM이 고를 때 읽는 설명, 안내 원문)는 data/support/guides.json 에서 읽는다.
주제를 추가하거나 고치려면 이 파일만 수정하고 앱을 다시 시작한다.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import openai
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, ValidationError, create_model

from config import LLM_API_KEY, LLM_MODEL
from core.exceptions import LlmError
from core.llm import choose_tool

logger = logging.getLogger(__name__)

GUIDES_PATH = Path(__file__).resolve().parents[2] / "data" / "support" / "guides.json"
GET_GUIDE_DOC = "MANSA 사용법 안내 하나를 꺼내 사용자에게 그대로 보여 준다."

FALLBACK = (
    "가이드에서 답을 찾지 못했어요. 위의 관리자 연결을 누르면 "
    "관리자와 직접 이야기할 수 있어요."
)

HISTORY_MAX_PAIRS = 5  # LLM에 함께 보낼 최근 질문·답변 쌍 수

SYSTEM_PROMPT = """너는 MANSA(설비 매뉴얼·안전 문서 질의응답 서비스)의 고객센터에서 사용법을 안내하는 챗봇이다.
- MANSA 사용법 질문이 GetGuide 주제의 안내 자체를 묻으면 반드시 GetGuide를 호출해 답한다.
- 이미 받은 안내에 대해 이어서 묻는 질문은 GetGuide를 다시 호출하지 말고, 앞 대화의 안내 내용을 근거로 직접 짧게 답한다.
  앞 안내로 답할 수 없으면 관리자 연결을 안내한다.
- 장비·모델·부품·작업 절차·사양 수치·안전 기준 같은 기술 질문에는 직접 답하지 말고 기술 Q&A 메뉴에서 물어보라고 안내한다.
- GetGuide 주제에 없는 사용법 질문은 추측해서 설명하지 말고, 화면 위의 관리자 연결을 눌러 관리자에게 물어보라고 안내한다.
- 직접 답할 때는 한국어 존댓말 평문으로 한두 문장만 쓴다. 굵게, 목록 기호, 제목, 코드 같은 마크다운을 쓰지 않는다."""


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다. 파일이 없거나 형식이 틀리면 파일 이름을 담아 ValueError를 발생시킨다."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc


def _is_text(value: Any) -> bool:
    """공백만 있지 않은 문자열이면 True다."""
    return isinstance(value, str) and bool(value.strip())


def _guide_content(item: dict[str, Any], guide_id: str) -> list[str] | str:
    """주제 하나의 안내 원문을 꺼낸다. steps(비어 있지 않은 문자열 목록)와 text(문자열) 중 정확히 하나여야 한다.

    조건에 맞지 않으면 주제 id를 담아 ValueError를 발생시킨다. steps는 새 리스트로 복사해 반환한다.
    """
    if ("steps" in item) == ("text" in item):
        raise ValueError(f"guide {guide_id!r} must have exactly one of steps or text")
    if "text" in item:
        if not _is_text(item["text"]):
            raise ValueError(f"guide {guide_id!r} text must be a non-empty string")
        return item["text"]
    steps = item["steps"]
    if not isinstance(steps, list) or not steps or not all(_is_text(s) for s in steps):
        raise ValueError(f"guide {guide_id!r} steps must be a list of non-empty strings")
    return list(steps)


def load_guides(path: Path) -> tuple[dict[str, list[str] | str], type[BaseModel]]:
    """안내 데이터 파일을 읽어 (주제 id -> 안내 원문, 도구 schema GetGuide)를 반환한다.

    파일은 {"id", "when", "steps" 또는 "text"} 객체의 배열이다. 배열 순서가 도구 설명과 enum 순서가 된다.
    GetGuide는 topic 하나를 받는 pydantic 모델이며, topic은 파일의 id만 허용하고 설명은 "id: when." 을 이어 붙인다.
    파일이 없거나, JSON이 깨졌거나, 빈 배열이거나, id·when이 비었거나 겹치거나, 안내 원문 형식이 틀리면
    ValueError를 발생시킨다. 형식만 검사하며 문구가 실제 화면과 맞는지는 확인하지 않는다.
    """
    data = _read_json(path)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path.name} must be a non-empty list of guides")
    guides: dict[str, list[str] | str] = {}
    labels: list[str] = []
    for item in data:
        guide_id = item.get("id") if isinstance(item, dict) else None
        if not _is_text(guide_id):
            raise ValueError(f"{path.name} has a guide without a non-empty id")
        if guide_id in guides:
            raise ValueError(f"guide {guide_id!r} is duplicated")
        if not _is_text(item.get("when")):
            raise ValueError(f"guide {guide_id!r} when must be a non-empty string")
        guides[guide_id] = _guide_content(item, guide_id)
        labels.append(f"{guide_id}: {item['when']}.")
    model = create_model(
        "GetGuide",
        __doc__=GET_GUIDE_DOC,
        topic=(Literal[tuple(guides)], Field(description=" ".join(labels))),
    )
    return guides, model


# 앱을 시작할 때(이 모듈을 import할 때) 한 번 읽는다. 파일이 잘못되면 여기서 ValueError로 멈춘다.
# 주제별 안내 값은 목록이면 번호 단계, 문자열이면 말풍선 하나로 화면에 그대로 표시된다.
GUIDES, GetGuide = load_guides(GUIDES_PATH)


def _bot_text(msg: dict) -> str:
    """챗봇 메시지를 화면에 보인 그대로의 텍스트로 바꾼다. 단계 안내는 줄바꿈으로 이어 붙인다."""
    return "\n".join(msg["steps"]) if "steps" in msg else msg["text"]


def to_history(msgs: list[dict]) -> list[dict]:
    """고객센터 화면 메시지 목록을 LLM에 보낼 이전 대화 목록으로 바꾼다.

    사용자 질문 바로 다음에 챗봇 답변이 온 쌍만 골라 최근 HISTORY_MAX_PAIRS쌍을 순서대로 담는다.
    인사말(앞에 질문 없음), 관리자에게 보낸 질문(다음이 관리자), 관리자·시스템 메시지는 이 규칙으로 빠진다.
    shortcut: 관리자 연결을 끝낸 직후 다시 연결하면 관리자에게 보낸 마지막 질문이 연결 안내 말과 쌍으로 들어갈 수
    있다, 실제 관리자 연결을 구현할 때 메시지에 연결 상태를 남겨 걸러 낸다. msgs는 변경하지 않는다.
    """
    pairs = [
        (question, reply)
        for question, reply in zip(msgs, msgs[1:])
        if question["who"] == "user" and reply["who"] == "bot"
    ]
    history: list[dict] = []
    for question, reply in pairs[-HISTORY_MAX_PAIRS:]:
        history.append({"role": "user", "content": question["text"]})
        history.append({"role": "assistant", "content": _bot_text(reply)})
    return history


def _to_reply(message: AIMessage) -> dict:
    """LLM 응답을 화면 메시지 형식({"steps": [...]} 또는 {"text": ...})으로 바꾼다.

    도구를 골랐으면 첫 번째 호출의 인자를 GetGuide로 검증해 그 주제 안내를 원문 그대로, 아니면 응답 본문의 텍스트만 쓴다.
    도구 이름이 다르거나 인자가 검증에 실패하거나 빈 답변이면 FALLBACK 안내를 쓴다.
    로그에는 검증을 통과한 도구 이름과 주제만 남긴다. LLM이 보낸 인자 원문에는 질문 내용이 섞일 수 있어 남기지 않는다.
    """
    if message.tool_calls:
        call = message.tool_calls[0]
        # bind_tools는 schema만 보내고 돌아온 인자를 검증하지 않는다.
        try:
            topic = GetGuide.model_validate(call["args"]).topic
        except ValidationError:
            topic = None
        if call["name"] != GetGuide.__name__ or topic is None:
            logger.warning("support tool call rejected: invalid tool name or arguments")
            return {"text": FALLBACK}
        logger.info("support tool call: %s %s", GetGuide.__name__, topic)
        guide = GUIDES[topic]
        return {"steps": list(guide)} if isinstance(guide, list) else {"text": guide}
    text = message.text.strip()
    return {"text": text or FALLBACK}


def answer(
    question: str, msgs: list[dict], call: Callable[..., AIMessage] = choose_tool
) -> dict:
    """고객센터 질문 하나에 답해 화면 메시지 형식({"steps": [...]} 또는 {"text": ...})으로 반환한다.

    msgs는 지금 질문 앞까지의 화면 메시지 목록이며 to_history로 바꿔 함께 보낸다. LLM은 한 번만 호출한다.
    LLM 설정이 없으면 호출하지 않고, LLM 호출이 실패하면 원인을 로그에 남긴 뒤 FALLBACK 안내를 반환한다.
    call은 테스트용 호출 함수다(기본값 core.llm.choose_tool). 유료 외부 API(OpenAI)를 호출한다.
    """
    if not LLM_API_KEY or not LLM_MODEL:
        logger.warning("support chat skipped: LLM_API_KEY or LLM_MODEL is not set")
        return {"text": FALLBACK}
    try:
        # 도구 세팅하는곳
        message = call("L3", SYSTEM_PROMPT, question, [GetGuide], to_history(msgs))
    # 사용자 대화 화면이라 인증·모델 없음까지 포함해 어떤 LLM 오류든 안내로 바꾸고 화면을 멈추지 않는다.
    except (LlmError, openai.OpenAIError):
        logger.exception("support chat LLM call failed")
        return {"text": FALLBACK}
    return _to_reply(message)
