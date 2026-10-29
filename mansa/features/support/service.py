"""고객센터(L3) 사용법 안내 챗봇. LLM이 안내 주제를 고르면 미리 정해 둔 안내를 원문 그대로 돌려준다."""

import logging
from collections.abc import Callable
from typing import Literal

import openai
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, ValidationError

from config import LLM_API_KEY, LLM_MODEL
from core.exceptions import LlmError
from core.llm import choose_tool

logger = logging.getLogger(__name__)

# 주제별 안내. 목록이면 번호 단계, 문자열이면 말풍선 하나로 화면에 그대로 표시된다.
GUIDES: dict[str, list[str] | str] = {
    "upload": [
        "관리자 메뉴에서 문서 업로드로 들어갑니다.",
        "PDF를 고르고 문서 유형과 소속 부서를 정합니다.",
        "업로드를 누르면 추출 → 청킹 → 색인까지 자동으로 처리돼요.",
    ],
    "history": "왼쪽 메뉴의 질문 기록에서 지난 기술 Q&A 대화를 다시 볼 수 있어요. "
    "항목을 누르면 그때 대화가 그대로 열려요.",
    "model_choice": "모델을 고르지 않아도 질문할 수 있어요. "
    "답을 찾는 데 모델이 필요하면 후보를 보여 드리고 다시 물어봐요.",
    "safety_notice": "③ 안전 요건은 AI가 문서에서 찾은 참고 정보예요. "
    "실제 작업 전 최종 판단은 안전관리자 확인이 필요해요.",
    "odd_answer": "근거 원문 창에서 출처를 먼저 확인해 주세요. 그래도 이상하면 "
    "위의 관리자 연결을 눌러 알려 주세요.",
}

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


class GetGuide(BaseModel):
    """MANSA 사용법 안내 하나를 꺼내 사용자에게 그대로 보여 준다."""

    topic: Literal[
        "upload", "history", "model_choice", "safety_notice", "odd_answer"
    ] = Field(
        description=(
            "upload: 문서(PDF) 업로드·등록 방법. "
            "history: 지난 질문 기록 보기. "
            "model_choice: 설비 모델을 고르지 않고 질문하면 어떻게 되는지. "
            "safety_notice: 답변의 안전 요건 안내 문구가 무슨 뜻인지. "
            "odd_answer: 답변이 이상하거나 틀린 것 같을 때 할 일."
        )
    )


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
