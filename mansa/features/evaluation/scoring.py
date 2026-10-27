"""규칙 채점, 실패 원인 분류, 지표·지연 집계. 모두 파일·외부 호출 없는 순수 함수다."""

import re
import unicodedata
from statistics import mean

from features.evaluation.models import (
    LATENCY_UNITS,
    AnswerRecord,
    CaseScore,
    Failure,
    Judgement,
    TestCase,
)

# 답변에서 수치 후보를 뽑을 때 쓰는 패턴(실패 설명용). 예: "0.5 mm", "5.6절", "-10%"
_NUMBER_TOKEN = re.compile(r"[+\-±−]?\d+(?:[.,]\d+)*\s*(?:[a-zA-Zµ%/°²³]+|절|초|회|개)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-"})
_MAX_FOUND = 3
# 수치 앞에 오면 다른 수치의 일부(부호·자릿수)로 보는 문자
_BEFORE_NUMBER = r"[\d.,+\-±]"
# 수치·단위 뒤에 오면 단위가 더 이어지는 것으로 보는 문자 (예: mm 뒤의 2, kg 뒤의 /h, kg 뒤의 f)
_AFTER_UNIT = r"[\da-zµ%°/]"


def normalize(text: str) -> str:
    """수치 비교용 정규화. 단위 환산(1000 mm = 1 m)은 하지 않는다.

    전각→반각(NFKC, ²→2·㎜→mm 포함), 소문자, 유니코드 빼기 기호→"-", 천 단위 쉼표 제거,
    공백 하나로 축소 후 숫자와 단위 사이·"/" 앞뒤·부호와 숫자 사이 공백 제거.
    다른 공백은 남겨 "1000 kg 2개"처럼 이웃한 값이 하나로 붙지 않게 한다.
    """
    text = unicodedata.normalize("NFKC", text).lower().translate(_MINUS)
    text = _THOUSANDS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=\d) (?=[a-zµ%°가-힣])", "", text)
    text = re.sub(r" ?/ ?", "/", text)
    return re.sub(r"(?<=[+\-±]) (?=\d)", "", text)


def contains_number(answer: str, expected: str) -> bool:
    """answer에 expected와 부호·숫자·단위가 모두 같은 값이 있으면 True다.

    - 앞 경계: "1000 kg"은 "-1000 kg", "11000 kg", "1.1000 kg" 안에서 맞지 않는다.
    - 뒤 경계: "0.5 mm"는 "0.5 mm²"(→mm2), "0.5 mm/s", "0.5 mmhg" 안에서 맞지 않고,
      단위 없는 "10"은 "10 mm"·"10%"·"10.5" 안에서 맞지 않는다.
    한글 단위(절·초·회 등)는 뒤에 오는 조사와 구분할 수 없어 한글 뒤 경계는 검사하지 않는다.
    """
    target = normalize(expected)
    if not target:
        return False
    pattern = rf"(?<!{_BEFORE_NUMBER}){re.escape(target)}(?!{_AFTER_UNIT}|\.\d)"
    return re.search(pattern, normalize(answer)) is not None


def find_numbers(answer: str) -> list[str]:
    """답변에 나온 수치 후보를 앞에서부터 최대 _MAX_FOUND개 반환한다(실패 설명 표시용)."""
    return [m.group().strip() for m in _NUMBER_TOKEN.finditer(answer)][:_MAX_FOUND]


def score_case(case: TestCase, record: AnswerRecord, judgement: Judgement | None) -> CaseScore:
    """문항 하나를 지표별로 판정한다.

    응답기가 값을 주지 않았거나(None) 정답이 비어 있으면 그 지표는 None이다.
    오류 문항은 계산 가능한 지표를 모두 실패(False)로 둔다. 근거 지표를 응답기가 아예
    제공하지 않는 경우의 처리는 compute_metrics가 맡는다.
    """
    score = CaseScore(case_id=case.id, error=record.error is not None)
    has_sources = bool(case.expected_sources)
    if case.expected_numbers:
        score.numeric_ok = not score.error and all(
            contains_number(record.answer_text, n) for n in case.expected_numbers
        )
        score.found_numbers = find_numbers(record.answer_text)
    if score.error:
        score.retrieval_hit = False if has_sources else None
        score.source_ok = False if has_sources else None
        score.consistent = False
        return score
    if has_sources and record.retrieved_ids is not None:
        score.retrieval_hit = bool(set(case.expected_sources) & set(record.retrieved_ids))
    if has_sources and record.cited_ids is not None:
        score.source_ok = set(case.expected_sources) <= set(record.cited_ids)
    if record.cited_ids:
        extra = set(record.cited_ids) - set(case.expected_sources)
        score.overattach = len(extra) / len(set(record.cited_ids))
    if judgement is not None:
        score.consistent = judgement.consistent
    return score


def compute_metrics(scores: list[CaseScore]) -> dict[str, float | None]:
    """문항 판정을 지표 5개의 백분율로 모은다.

    오류가 아닌 문항 중 값을 낸 문항이 하나도 없는 지표는 None("값 없음")이다.
    값이 있으면 오류 문항도 분모에 넣어 실패로 센다. 과잉 첨부율은 문항별 비율의 평균이다.
    """
    def rate(attr: str) -> float | None:
        """CaseScore의 통과 여부 필드 하나를 백분율로 바꾼다."""
        if all(getattr(s, attr) is None for s in scores if not s.error):
            return None
        values = [getattr(s, attr) for s in scores if getattr(s, attr) is not None]
        return 100 * sum(values) / len(values)

    overattach = [s.overattach for s in scores if s.overattach is not None]
    return {
        "검색 적중률": rate("retrieval_hit"),
        "수치 정확도": rate("numeric_ok"),
        "출처 정확도": rate("source_ok"),
        "과잉 첨부율": 100 * mean(overattach) if overattach else None,
        "표현 일관성": rate("consistent"),
    }


def classify_failure(
    case: TestCase,
    record: AnswerRecord,
    score: CaseScore,
    judgement: Judgement | None,
) -> Failure | None:
    """통과하지 못한 지표가 있는 문항을 실패 사례로 만든다. 모두 통과(또는 계산 불가)면 None이다.

    원인: 검색 미적중 → 검색, 그 밖의 L3 → 조회, 그 밖의 L2 → 생성.
    """
    checks = (score.retrieval_hit, score.numeric_ok, score.source_ok, score.consistent)
    if not score.error and False not in checks:
        return None
    if score.retrieval_hit is False and not score.error:
        cause = "검색"
    elif case.workflow == "L3":
        cause = "조회"
    else:
        cause = "생성"
    return Failure(
        case_id=case.id,
        question=case.question,
        workflow=case.workflow,
        cause=cause,
        detail=_failure_detail(case, record, score, judgement),
    )


def _failure_detail(
    case: TestCase,
    record: AnswerRecord,
    score: CaseScore,
    judgement: Judgement | None,
) -> str:
    """실패 사례의 "기대 → 실제" 설명. 가장 먼저 실패한 항목 하나만 설명한다."""
    if record.error:
        return f"응답 오류: {record.error}"
    if score.retrieval_hit is False:
        retrieved = (record.retrieved_ids or [])[:_MAX_FOUND]
        return f"{_join(case.expected_sources)} → {_join(retrieved)}"
    if score.numeric_ok is False:
        return f"{_join(case.expected_numbers)} → {_join(score.found_numbers)}"
    if score.source_ok is False:
        return f"근거 {_join(case.expected_sources)} → {_join(record.cited_ids or [])}"
    reason = judgement.reason if judgement else ""
    return f"표현 불일치: {reason}" if reason else "표현 불일치"


def _join(values: list[str]) -> str:
    """목록을 쉼표로 잇는다. 비어 있으면 "없음"이다."""
    return ", ".join(values) if values else "없음"


def compute_latency(records: list[AnswerRecord]) -> dict[str, float | None]:
    """측정값이 있는 문항만으로 기술 Q&A 평균 지연·토큰을 계산한다. 고객센터 항목은 None이다."""
    latencies = [r.latency_sec for r in records if r.latency_sec is not None]
    tokens = [r.tokens for r in records if r.tokens is not None]
    result: dict[str, float | None] = dict.fromkeys(LATENCY_UNITS)
    result["기술 Q&A 평균 지연"] = mean(latencies) if latencies else None
    result["기술 Q&A 평균 토큰"] = mean(tokens) if tokens else None
    return result
