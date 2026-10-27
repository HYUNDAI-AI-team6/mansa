"""평가 기능이 주고받는 데이터 구조."""

from dataclasses import dataclass, field
from typing import Literal

Workflow = Literal["L2", "L3"]
FailureCause = Literal["검색", "조회", "생성"]
LlmStage = Literal["답변", "채점"]

# 화면과 CSV에 나오는 지표 순서. scoring.compute_metrics가 이 키로 값을 채운다.
METRIC_NAMES = ["검색 적중률", "수치 정확도", "출처 정확도", "과잉 첨부율", "표현 일관성"]
# 지연·토큰 항목 이름 → 단위. 고객센터 항목은 이번 범위에서 측정하지 않아 항상 None이다.
LATENCY_UNITS = {
    "기술 Q&A 평균 지연": "초",
    "기술 Q&A 평균 토큰": "토큰",
    "고객센터 평균 지연": "초",
    "고객센터 평균 토큰": "토큰",
}


@dataclass(frozen=True)
class TestCase:
    """테스트셋 문항 하나.

    expected_numbers는 답변에 그대로 나와야 하는 수치·단위 문자열(예: "5.6절", "10 mm")이고,
    expected_sources는 정답 근거 ID 목록이다. 근거 ID 형식은 응답기가 돌려주는 ID와 같아야 한다.
    """

    __test__ = False  # unittest/pytest가 이름 때문에 테스트 클래스로 오인하지 않게 한다.

    id: str
    question: str
    workflow: Workflow
    expected_numbers: list[str] = field(default_factory=list)
    expected_sources: list[str] = field(default_factory=list)


@dataclass
class TestSet:
    """테스트셋 파일 전체. cases는 파일에 적힌 순서를 유지한다."""

    __test__ = False

    title: str
    description: str
    cases: list[TestCase]


@dataclass
class AnswerRecord:
    """응답기가 문항 하나에 답한 결과.

    None은 "응답기가 이 값을 제공하지 않음"이고 빈 리스트는 "제공했지만 0개"다.
    채점은 이 차이로 지표를 "값 없음"으로 둘지 판단한다. error가 있으면 호출이 실패한 문항이다.
    """

    case_id: str
    answer_text: str = ""
    cited_ids: list[str] | None = None
    retrieved_ids: list[str] | None = None
    latency_sec: float | None = None
    tokens: int | None = None
    error: str | None = None


@dataclass
class Judgement:
    """채점 LLM의 표현 일관성 판정.

    error가 있으면 채점 LLM 호출·해석에 실패한 것이고 consistent는 None이다.
    """

    consistent: bool | None
    reason: str = ""
    error: str | None = None


@dataclass
class CaseScore:
    """문항 하나의 지표별 판정. None은 그 지표를 이 문항에서 계산할 수 없다는 뜻이다.

    overattach는 인용 근거 중 정답이 아닌 근거의 비율(0~1)이다. 나머지는 통과 여부다.
    error는 응답기 호출이 실패한 문항인지 나타낸다.
    """

    case_id: str
    error: bool = False
    retrieval_hit: bool | None = None
    numeric_ok: bool | None = None
    source_ok: bool | None = None
    overattach: float | None = None
    consistent: bool | None = None
    found_numbers: list[str] = field(default_factory=list)


@dataclass
class Failure:
    """화면의 실패 사례 한 줄."""

    case_id: str
    question: str
    workflow: Workflow
    cause: FailureCause
    detail: str


@dataclass
class LlmError:
    """LLM 호출 실패 한 건. stage는 답변(응답기) 또는 채점(judge) 단계다."""

    case_id: str
    question: str
    stage: LlmStage
    reason: str


@dataclass
class EvalReport:
    """평가 1회의 집계 결과.

    metrics는 METRIC_NAMES 순서의 지표명 → 백분율(0~100) 또는 None("값 없음")이다.
    latency는 화면 표시 이름 → 값(초·토큰) 또는 None이다. finished_at은 전체 평가가 끝난 시각(ISO 8601)이다.
    failures는 답변 품질 실패, llm_errors는 답변·채점 LLM 호출 실패다. LLM 오류 문항도 지표에서는 실패로 센다.
    """

    run_id: str
    testset_title: str
    answerer: str
    total: int
    finished_at: str
    metrics: dict[str, float | None]
    failures: list[Failure]
    latency: dict[str, float | None]
    answers_file: str = ""
    llm_errors: list[LlmError] = field(default_factory=list)


@dataclass(frozen=True)
class Progress:
    """실행 중 진행 상황. done은 답변을 받은 문항 수다."""

    done: int
    total: int
    stage: str = "answer"
