"""대화 기록 저장소. 지금은 메모리에 두고, MySQL 테이블이 생기면 같은 규격의 저장소를 추가한다."""

from dataclasses import replace
from datetime import datetime
from typing import Protocol

from core.schemas import Answer, Conversation, ConversationSummary, QaTurn

class HistoryStore(Protocol):
    """HistoryService가 쓰는 저장소 규격. 대화 ID는 저장소가 정하는 정수다."""

    def create_conversation(self, member_id: int, title: str, created_at: datetime) -> int:
        """새 대화를 만들고 대화 ID를 반환한다."""
        ...

    def add_turn(self, conversation_id: int, question: str, answer: Answer, created_at:datetime) -> None:
        """대화에 질문·답변 한 쌍을 덧붙인다."""
        ...

    def get(self, conversation_id: int) -> Conversation | None:
        """대화를 질문·답변 기록과 함께 반환한다. 없으면 None이다."""
        ...

    def list_summaries(self, member_id: int) -> list[ConversationSummary]:
        """회원의 대화 요약을 모두 반환한다. 순서는 정하지 않는다."""
        ...

class MemoryHistoryStore:
    """대화 기록을 메모리에 두는 저장소. 앱을 다시 켜면 사라진다."""

    #shortcut: 대화·질문 기록 테이블이 없어 메모리에 둔다, 테이블이 생기면 MySQL 저장소를 추가해 바꾼다.

    def __init__(self) -> None:
        """빈 저장소를 만든다. 대화 ID는 DB의 자동 증가처럼 1부터 매긴다."""
        self._conversations: dict[int, Conversation] = {}

    def create_conversation(self, member_id: int, title: str, created_at: datetime) -> int:
        """새 대화를 만들고 대화 ID를 반환한다."""
        conversation_id = len(self._conversations) + 1
        self._conversations[conversation_id] = Conversation(conversation_id, member_id, title, created_at)
        return conversation_id

    def add_turn(self, conversation_id: int, question: str, answer: Answer, created_at: datetime) -> None:
        """대화에 질문·답변 한 쌍을 덧붙인다. 없는 대화 ID면 KeyError다."""
        self._conversations[conversation_id].turns.append(QaTurn(question, answer, created_at))

    def get(self, conversation_id: int) -> Conversation | None:
        """대화를 반환한다. 받은 쪽이 목록을 바꿔도 저장된 기록이 바뀌지 않게 복사본을 준다."""
        conversation = self._conversations.get(conversation_id)
        return None if conversation is None else replace(conversation, turns=list(conversation.turns))

    def list_summaries(self, member_id: int) -> list[ConversationSummary]:
        """회원의 대화 요약을 반환한다. 마지막 시각은 마지막 질문 시각, 질문이 없으면 만든 시각이다."""
        return [
            ConversationSummary(
                id=c.id,
                title=c.title,
                updated_at=c.turns[-1].created_at if c.turns else c.created_at,
                question_count=len(c.turns),
            )
            for c in self._conversations.values()
            if c.member_id == member_id
        ]