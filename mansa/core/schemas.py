from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# 질문 의도. 공통 core/constants가 생기면 그쪽 값으로 옮긴다.
IntentType = Literal["spec", "procedure", "safety", "inspection", "out_of_scope"]
NoAnswerReason = Literal["insufficient_evidence", "out_of_scope", "llm_failure"]


@dataclass
class Intent:
    """질문 분석 결과. QuestionAnalyzer.analyze가 만들고 이후 단계가 읽는다.

    model_ids·parts는 validate_ids를 거친 뒤에는 실제 등록된 값만 남는다.
    title은 대화의 첫 질문일 때만 채워지는 대화 제목이다.
    """

    intent: IntentType
    model_ids: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    task: str | None = None
    values: list[str] = field(default_factory=list)
    title: str | None = None


@dataclass(frozen=True)
class ScoredChunk:
    """검색된 문서 청크 하나와 관련도 점수.

    score는 0~1 범위이며 클수록 관련이 높다. AnswerGuard가 이 값을 근거 충분성 기준과
    비교하므로 RRF 순위 점수처럼 범위가 다른 값을 그대로 넣지 않는다.
    doc_type은 "tech"(매뉴얼·사양서) 또는 "secure"(안전 문서)다.
    """

    chunk_id: str
    text: str
    score: float
    doc_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    """답변에 쓸 근거 청크 목록. 점수가 높은 순서로 정렬되어 있다."""

    chunks: list[ScoredChunk] = field(default_factory=list)


@dataclass
class AnswerSection:
    """답변 영역 하나의 본문과 그 본문을 쓸 때 참고한 근거 청크 ID 목록."""

    text: str = ""
    source_ids: list[str] = field(default_factory=list)


@dataclass
class AnswerDraft:
    """AnswerGenerator가 만든 검증 전 답변. ① 절차 ② 사양 ③ 안전 ④ 기준 차이 4개 영역이다."""

    procedure: AnswerSection = field(default_factory=AnswerSection)
    spec: AnswerSection = field(default_factory=AnswerSection)
    safety: AnswerSection = field(default_factory=AnswerSection)
    diff: AnswerSection = field(default_factory=AnswerSection)


@dataclass
class Answer:
    """근거 검사를 통과하고 안전 참고 문구가 붙은 최종 답변.

    conversation_id는 대화 기록에 저장된 뒤 채워지며, 화면은 이 값으로 다음 질문을 이어 보낸다.
    """

    procedure: AnswerSection
    spec: AnswerSection
    safety: AnswerSection
    diff: AnswerSection
    conversation_id: int | None = None


@dataclass
class Clarify:
    """모델·부위가 정해지지 않았을 때 사용자에게 되묻는 질문과 선택지."""

    question: str
    options: list[str] = field(default_factory=list)


@dataclass
class NoAnswer:
    """답변 불가 안내. reason으로 근거 부족·범위 밖·LLM 실패를 구분한다."""

    reason: NoAnswerReason
    message: str
    contact: str


@dataclass
class QaTurn:
    """대화 안의 질문·답변 한 쌍. 저장한 답변을 그대로 보여 주며 다시 생성하지 않는다."""

    question: str
    answer: Answer
    created_at: datetime


@dataclass
class Conversation:
    """회원 한 명의 대화 하나. turns는 먼저 한 질문부터 순서대로다."""

    id: int
    member_id: int
    title: str
    created_at: datetime
    turns: list[QaTurn] = field(default_factory=list)


@dataclass
class ConversationSummary:
    """질문 기록 목록의 한 줄. tags(모델·작업)는 아직 저장하지 않아 빈 리스트다."""

    id: int
    title: str
    updated_at: datetime
    question_count: int
    tags: list[str] = field(default_factory=list)


@dataclass
class SourceView:
    """근거 원문 창에 보여 줄 근거 청크 하나. before·after는 같은 페이지의 바로 앞뒤 청크다.
    
    부서·조항은 청크 메타데이터에 아직 없어 빈 문자열이다. page는 CSV처럼 페이지가 없으면 None이다.
    """

    chunk_id: str
    text: str
    before: str
    after: str
    doc_name: str
    page: int | None
    department: str = ""
    clause: str = ""