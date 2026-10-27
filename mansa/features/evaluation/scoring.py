"""규칙 채점, 실패 원인 분류, 지표·지연 집계. 모두 파일·외부 호출 없는 순수 함수다."""

import re
import unicodedata
from statistics import mean

from features.evaluation.models import (
    AnswerRecord,
    CaseScore,
    Failure,
    Judgement,
    LlmError,
    NumberCheck,
    NumberNote,
    TestCase,
)

# 답변에서 수치 후보를 뽑을 때 쓰는 패턴(실패 설명용). 예: "0.5 mm", "5.6절", "-10%"
_NUMBER_TOKEN = re.compile(r"[+\-±−]?\d+(?:[.,]\d+)*\s*(?:[a-zA-Zµ%/°²³]+|절|초|회|개)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-"})
_MAX_FOUND = 3
# 수치 앞에 오면 다른 수치의 일부로 보는 것: 부호·자릿수·소수점, 분수(1/1000), 지수(1e5, 1e-5)
# "-"는 앞이 공백·문장 시작이면 부호("-1000 kg")로 막고, 앞에 글자·숫자가 붙으면 범위("5-10 mm")로 본다.
# 천 단위가 아닌 쉼표는 목록 구분자로 보고 막지 않는다 (예: "500kg,1000kg")
_BEFORE_NUMBER = r"(?<![\d.+±])(?<!(?<![^\W_])-)(?<!\d/)(?<!\d[eE])(?<!\d[eE]-)"
_UNIT_LETTER = r"a-zA-ZµμͰ-Ͽ"
# 수치·단위 뒤에 오면 단위가 더 이어지는 것으로 보는 것 (예: mm 뒤의 2, kg 뒤의 /h, kg 뒤의 f)
# 복합 단위: "·", "^"는 항상, "*", "×", "."은 뒤에 단위 글자가 올 때만 막는다
# ("N*m"·"N.m"은 막고 "10 mm × 20 mm", 문장 끝 "0.5mm."은 통과)
# "-"는 범위 표기와 구분하기 어려워 막지 않는다. 그래서 "10 N-m"은 "10 N"과 맞는다.
_AFTER_UNIT = rf"[\d{_UNIT_LETTER}%°/·⋅∙^]|[*×.][{_UNIT_LETTER}]|\.\d"


def normalize(text: str) -> str:
    """수치 비교용 정규화. 단위 환산(1000 mm = 1 m)은 하지 않는다.

    전각→반각(NFKC, ²→2·㎜→mm 포함), 유니코드 빼기 기호→"-", 천 단위 쉼표 제거,
    공백 하나로 축소 후 숫자와 단위 사이·"/"와 곱셈·지수 기호 앞뒤·부호와 숫자 사이 공백 제거.
    대소문자는 단위 의미가 달라지므로(MPa·mPa) 바꾸지 않는다.
    다른 공백은 남겨 "1000 kg 2개"처럼 이웃한 값이 하나로 붙지 않게 한다.
    """
    text = unicodedata.normalize("NFKC", text).translate(_MINUS)
    text = _THOUSANDS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 숫자 뒤에 문자(라틴·그리스·한글 등 모든 유니코드 문자)나 %·°가 오면 단위로 보고 붙인다
    text = re.sub(r"(?<=\d) (?=[^\W\d_]|[%°])", "", text)
    text = re.sub(r" ?([/·⋅∙*×^]) ?", r"\1", text)
    return re.sub(r"(?<=[+\-±]) (?=\d)", "", text)


def contains_number(answer: str, expected: str) -> bool:
    """answer에 expected와 부호·숫자·단위가 모두 같은 값이 있으면 True다.

    - 앞 경계: "1000 kg"은 "-1000 kg", "11000 kg", "1.1000 kg", "1/1000 kg" 안에서,
      "5 mm"는 "1e5 mm" 안에서 맞지 않는다. "500kg,1000kg", 범위 "5-10 mm"에서는 맞는다.
    - 뒤 경계: "0.5 mm"는 "0.5 mm²"(→mm2), "0.5 mm/s", "0.5 mmHg" 안에서 맞지 않고,
      단위 없는 "10"은 "10 mm"·"10%"·"10.5" 안에서 맞지 않는다.
      복합 단위 "10 N·m", "10 N*m", "0.5 mm^2" 안에서도 "10 N"·"0.5 mm"는 맞지 않는다.
    - 단위 대소문자가 달라도 맞지 않는다("1 MPa" ↔ "1 mPa").
    한글 단위(절·초·회 등)는 뒤에 오는 조사와 구분할 수 없어 한글 뒤 경계는 검사하지 않는다.
    """
    target = normalize(expected)
    if not target:
        return False
    pattern = rf"{_BEFORE_NUMBER}{re.escape(target)}(?!{_AFTER_UNIT})"
    return re.search(pattern, normalize(answer)) is not None


def find_numbers(answer: str) -> list[str]:
    """답변에 나온 수치 후보를 앞에서부터 최대 _MAX_FOUND개 반환한다(실패 설명 표시용)."""
    return [m.group().strip() for m in _NUMBER_TOKEN.finditer(answer)][:_MAX_FOUND]


def score_case(case: TestCase, record: AnswerRecord, judgement: Judgement | None) -> CaseScore:
    """문항 하나를 지표별로 판정한다.

    수치 정확도는 규칙(contains_number)을 먼저 쓰고, 규칙이 놓친 수치만 채점 LLM 판정으로 다시 본다.
    응답기가 값을 주지 않았거나(None) 정답이 비어 있으면 그 지표는 None이다.
    오류 문항은 계산 가능한 지표를 모두 실패(False)로 둔다. 근거 지표를 응답기가 아예
    제공하지 않는 경우의 처리는 compute_metrics가 맡는다.
    """
    score = CaseScore(case_id=case.id, error=record.error is not None)
    has_sources = bool(case.expected_sources)
    if case.expected_numbers:
        score.numeric_ok = not score.error and _check_numbers(case, record, judgement, score)
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
        # 채점 LLM 오류도 표현 일관성에서는 실패로 센다. 오류 내용은 collect_llm_errors가 따로 남긴다.
        score.consistent = False if judgement.error else judgement.consistent
    return score


def _check_numbers(
    case: TestCase, record: AnswerRecord, judgement: Judgement | None, score: CaseScore
) -> bool:
    """정답 수치가 모두 답변에 있으면 True다. 규칙과 LLM이 다르게 본 수치는 score에 기록한다.

    - 규칙 통과: 통과. LLM이 matched=false면 numbers_disputed에 남긴다(판정은 규칙을 따른다).
    - 규칙 실패: LLM이 matched=true이고 근거 원문이 _verified_quote를 통과하면 통과로 보고
      numbers_by_llm에 남긴다. 채점 LLM 오류(numbers 없음)면 규칙 결과만 쓴다.
    """
    checks = _number_checks(case, judgement)
    ok = True
    for expected, check in zip(case.expected_numbers, checks):
        if contains_number(record.answer_text, expected):
            if check is not None and not check.matched:
                score.numbers_disputed.append(expected)
        elif quote := _verified_quote(check, expected, record.answer_text):
            score.numbers_by_llm[expected] = quote
        else:
            ok = False
    return ok


def _number_checks(case: TestCase, judgement: Judgement | None) -> list[NumberCheck | None]:
    """정답 수치 순서대로 LLM 판정을 맞춘다. expected 문자열로 찾고, 못 찾으면 같은 순번 판정을 쓴다.

    순번으로 맞추는 것은 LLM이 expected를 조금 바꿔 옮긴 경우를 위한 것으로, 개수가 같을 때만 쓴다.
    """
    numbers = judgement.numbers if judgement else []
    by_expected = {c.expected: c for c in numbers}
    same_count = len(numbers) == len(case.expected_numbers)
    return [
        by_expected.get(n) or (numbers[i] if same_count else None)
        for i, n in enumerate(case.expected_numbers)
    ]


def _verified_quote(check: NumberCheck | None, expected: str, answer: str) -> str:
    """LLM이 맞다고 한 수치의 근거 원문을 확인해 돌려준다. 확인하지 못하면 빈 문자열이다.

    LLM이 답변에 없는 내용을 지어내는 경우를 막으려고 두 가지를 본다.
    1. quote가 답변에 실제로 있는 문자열이다(공백 차이만 무시).
    2. 정답 수치의 숫자들이 quote에 모두 있다(단위 환산·다른 값은 통과시키지 않는다).
    """
    if check is None or not check.matched:
        return ""
    quote = " ".join(check.quote.split())
    if not quote or quote not in " ".join(answer.split()):
        return ""
    digits = re.findall(r"\d+(?:\.\d+)?", normalize(expected))
    normalized = normalize(quote)
    return quote if digits and all(d in normalized for d in digits) else ""


def compute_metrics(scores: list[CaseScore]) -> dict[str, float | None]:
    """문항 판정을 지표 5개의 백분율로 모은다.

    LLM 오류 문항은 계산 가능한 지표에서 실패로 센다. 수치 정확도(정답 수치만 있으면 계산 가능)와
    표현 일관성은 전 문항이 오류여도 0%로 집계한다. 검색·출처 지표는 응답기가 근거 정보를 주는지에
    달려 있으므로, 오류가 아닌 문항 중 값을 낸 문항이 하나도 없으면 None("값 없음")이다.
    과잉 첨부율은 문항별 비율의 평균이다.
    """

    def rate(attr: str, needs_answerer_info: bool = False) -> float | None:
        """CaseScore의 통과 여부 필드 하나를 백분율로 바꾼다. 계산할 문항이 없으면 None이다."""
        if needs_answerer_info and all(getattr(s, attr) is None for s in scores if not s.error):
            return None
        values = [getattr(s, attr) for s in scores if getattr(s, attr) is not None]
        return 100 * sum(values) / len(values) if values else None

    overattach = [s.overattach for s in scores if s.overattach is not None]
    return {
        "검색 적중률": rate("retrieval_hit", needs_answerer_info=True),
        "수치 정확도": rate("numeric_ok"),
        "출처 정확도": rate("source_ok", needs_answerer_info=True),
        "과잉 첨부율": 100 * mean(overattach) if overattach else None,
        "표현 일관성": rate("consistent"),
    }


def classify_failure(
    case: TestCase,
    record: AnswerRecord,
    score: CaseScore,
    judgement: Judgement | None,
) -> Failure | None:
    """답변 품질이 기준에 못 미친 문항을 실패 사례로 만든다. 모두 통과(또는 계산 불가)면 None이다.

    답변 LLM 오류 문항과 채점 LLM 오류로 생긴 표현 일관성 실패는 품질 실패가 아니므로 여기서
    제외하고 collect_llm_errors가 따로 남긴다.
    원인: 검색 미적중 → 검색, 그 밖의 L3 → 조회, 그 밖의 L2 → 생성.
    """
    if score.error:
        return None
    judge_failed = judgement is not None and judgement.error is not None
    consistent = None if judge_failed else score.consistent
    if False not in (score.retrieval_hit, score.numeric_ok, score.source_ok, consistent):
        return None
    if score.retrieval_hit is False:
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
    if score.retrieval_hit is False:
        retrieved = (record.retrieved_ids or [])[:_MAX_FOUND]
        return f"{_join(case.expected_sources)} → {_join(retrieved)}"
    if score.numeric_ok is False:
        return f"{_join(case.expected_numbers)} → {_join(score.found_numbers)}"
    if score.source_ok is False:
        return f"근거 {_join(case.expected_sources)} → {_join(record.cited_ids or [])}"
    reason = judgement.reason if judgement else ""
    return f"표현 불일치: {reason}" if reason else "표현 불일치"


def collect_llm_errors(
    case: TestCase, record: AnswerRecord, judgement: Judgement | None
) -> list[LlmError]:
    """문항 하나의 답변·채점 LLM 호출 실패를 목록으로 만든다. 실패가 없으면 빈 목록이다."""
    errors = []
    if record.error:
        errors.append(LlmError(case.id, case.question, "답변", record.error))
    if judgement is not None and judgement.error:
        errors.append(LlmError(case.id, case.question, "채점", judgement.error))
    return errors


def collect_number_notes(case: TestCase, score: CaseScore) -> list[NumberNote]:
    """수치 판정에서 규칙과 채점 LLM이 다르게 본 기록을 만든다. 없으면 빈 목록이다."""
    rescued = [
        NumberNote(case.id, case.question, n, "LLM 통과", quote)
        for n, quote in score.numbers_by_llm.items()
    ]
    disputed = [
        NumberNote(case.id, case.question, n, "LLM 이견") for n in score.numbers_disputed
    ]
    return rescued + disputed


def _join(values: list[str]) -> str:
    """목록을 쉼표로 잇는다. 비어 있으면 "없음"이다."""
    return ", ".join(values) if values else "없음"


def compute_latency(records: list[AnswerRecord]) -> dict[str, float | None]:
    """측정값이 있는 문항만으로 기술 Q&A 평균 지연·토큰을 계산한다. 측정값이 없으면 None이다."""
    latencies = [r.latency_sec for r in records if r.latency_sec is not None]
    tokens = [r.tokens for r in records if r.tokens is not None]
    return {
        "기술 Q&A 평균 지연": mean(latencies) if latencies else None,
        "기술 Q&A 평균 토큰": mean(tokens) if tokens else None,
    }
