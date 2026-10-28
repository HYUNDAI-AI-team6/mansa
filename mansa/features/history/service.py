"""질문 기록(명세서 services.history). 대화를 만들고 질문·답변을 저장하고 다시 보여 준다."""

from collections.abc import Callable
from datetime import datetime

from core.schemas import Answer, Conversation, ConversationSummary
from features.history.store import HistoryStore

TITLE_LENGTH = 30


class HistoryService:
    """회원별 대화 기록을 저장·조회한다. 저장소와 현재 시각 함수는 생성자에서 바꿔 끼울 수 있다."""

    def __init__(self, store: HistoryStore, now: Callable[[], datetime] = datetime.now) -> None:
        """store에는 지금은 MemoryHistoryStore, now는 테스트에서 시각을 고정할 때 바꾼다."""
        self._store = store
        self._now = now

    def save(
        self,
        member_id: int,
        conversation_id: int | None,
        question: str,
        title: str | None,
        answer: Answer,
    ) -> int:
        """질문·답변을 저장하고 대화 ID를 반환한다.

        conversation_id가 None이면 새 대화를 만든다. 제목은 title이고, 없으면 질문 앞부분이다.
        다른 회원의 대화나 없는 대화에 이어 쓰려 하면 LookupError를 발생시킨다.
        """
        now = self._now()
        if conversation_id is None:
            conversation_id = self._store.create_conversation(member_id, title or _default_title(question), now)
        else:
            self._own(member_id, conversation_id)
        self._store.add_turn(conversation_id, question, answer, now)
        return conversation_id

    def list_conversations(self, member_id: int, limit: int) -> list[ConversationSummary]:
        """회원의 대화를 최근에 질문한 순서로 limit개까지 반환한다. 없으면 빈 리스트다."""
        summaries = self._store.list_summaries(member_id)
        # 시각이 같으면 나중에 만든 대화(id가 큰 쪽)가 앞에 온다
        summaries.sort(key=lambda s: (s.updated_at, s.id), reverse=True)
        return summaries[: max(limit, 0)]

    def get_conversation(self, member_id: int, conversation_id: int) -> Conversation:
        """회원 본인의 대화를 저장된 질문·답변 그대로 반환한다. 답변을 다시 만들지 않는다.
        
        없는 대화와 다른 회원의 대화를 구분하지 않고 LookupError를 발생시킨다.
        """
        return self._own(member_id, conversation_id)

    def _own(self, member_id: int, conversation_id: int) -> Conversation:
        """회원 본인의 대화를 반환한다. 없거나 다른 회원의 대화면 LookupError다."""
        conversation = self._store.get(conversation_id)
        if conversation is None or conversation.member_id != member_id:
            raise LookupError(f"conversation not found: {conversation_id}")
        return conversation


def _default_title(question: str) -> str:
    """질문의 공백을 정리해 앞 TITLE_LENGTH자를 제목으로 쓴다. 길면 말줄임표를 붙인다."""
    text = " ".join(question.split())
    return text if len(text) <= TITLE_LENGTH else text[:TITLE_LENGTH] + "…"