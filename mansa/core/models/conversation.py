from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# 질문 기록 화면 "대화 목록 -> 하나의 대화 목록 선택 -> 그 대화의 지난 질문,답변 보기"
class Conversation(Base):
    """회원 한 명의 대화 묶음. 질문·답변 기록(QaHistory)은 이 대화 ID에 연결된다."""

    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True) # 현재 회원 테이블이 없어서 FK 없이 뒀습니다. 
                                                     # 회원 모델이 develop에 들어오면 ForeignKey 추가
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
        