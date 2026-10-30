"""기준 차이 비교: 매뉴얼(기술 문서)의 수치와 안전 문서의 기준 수치를 단위를 맞춰 코드로 비교한다.

LLM이 글로 "차이"를 쓰기 전에, 숫자 비교만은 코드가 맡아 틀리지 않게 하려는 것이다.
  1. 근거 청크에서 비교할 수치를 뽑는다(extract_values).
  2. 단위를 맞추고(normalize_unit) 같은 항목끼리 비교한다(DiffChecker.compare).
  3. 결과를 답변 프롬프트에 넣을 글로 바꾼다(format_comparison).
조건이 다르거나 비교 기준이 분명하지 않으면 억지로 판정하지 않고 "비교 불가"로 알린다.
"""

import re
import unicodedata
from dataclasses import dataclass
from math import isclose
from typing import Literal

from core.schemas import Evidence, ScoredChunk

Verdict = Literal["충족", "미충족", "동일", "다름", "비교 불가"]

# 단위 이름 -> (기준 단위, 기준 단위로 바꿀 때 곱하는 수). 키는 NFKC로 바꾼 뒤 소문자다("㎏"→"kg", "㎡"→"m2").
# shortcut: 승강기 사양·안전기준에 나오는 단위만 둔다. 새 단위가 필요하면 여기에 한 줄 더한다.
_UNITS: dict[str, tuple[str, float]] = {
    "mm": ("mm", 1.0),
    "cm": ("mm", 10.0),
    "m": ("mm", 1000.0),
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "t": ("kg", 1000.0),
    "n": ("N", 1.0),
    "kn": ("N", 1000.0),
    "m2": ("m²", 1.0),
    "cm2": ("m²", 0.0001),
    "lx": ("lx", 1.0),
    "m/s": ("m/min", 60.0),
    "m/min": ("m/min", 1.0),
}

# 안전 문서의 비교 말 -> 연산자. "이내"는 기준값을 포함하므로 "이하"와 같다.
_COMPARATORS = {"이상": ">=", "이하": "<=", "초과": ">", "미만": "<", "이내": "<="}

_NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
# 숫자 + 단위 + (비교 말). 단위는 긴 것부터 맞추고, 단위 뒤에 영문이 더 붙으면(mmHg 등) 맞지 않는다.
_QUANTITY = re.compile(
    rf"(?P<num>{_NUMBER})\s*(?P<unit>㎜|㎝|㎏|㎡|㏓|m/min|m/s|kN|mm|cm|kg|lx|m|t|N)(?![A-Za-z²/])"
    r"(?:\s*(?:를|을|은|는|가|이)?\s*(?P<cmp>이상|이하|초과|미만|이내))?"
)


def normalize_unit(value: float, unit: str) -> tuple[float, str]:
    """값을 기준 단위로 바꿔 (바뀐 값, 기준 단위)를 돌려준다. 예: (2.5, "m") → (2500.0, "mm").

    길이는 mm, 무게는 kg, 힘은 N, 넓이는 m², 조도는 lx, 속도는 m/min이 기준이다.
    알 수 없는 단위는 ValueError를 발생시킨다.
    """
    key = unicodedata.normalize("NFKC", unit).replace(" ", "").replace("²", "2").lower()
    if key not in _UNITS:
        raise ValueError(f"unknown unit: {unit!r}")
    base, factor = _UNITS[key]
    return value * factor, base


@dataclass(frozen=True)
class SpecValue:
    """비교할 수치 하나. 매뉴얼 값이든 안전 기준 값이든 같은 모양이다.

    name은 비교 항목 이름(예: "피트 깊이")이고, raw는 근거 원문에 적힌 그대로의 값(예: "2.5 m")이다.
    comparator는 안전 기준의 "이상/이하/초과/미만/이내"이며 매뉴얼 값에는 없다.
    condition은 적용 조건(예: "별도 피트 출입문이 없는 경우")이고 모르면 빈 문자열이다.
    label은 값이 어느 모델의 것인지(예: "HC20022US1")이며 없으면 빈 문자열이다.
    """

    name: str
    value: float
    unit: str
    source_id: str
    raw: str = ""
    comparator: str = ""
    condition: str = ""
    label: str = ""

    def normalized(self) -> tuple[float, str]:
        """기준 단위로 바꾼 (값, 단위)."""
        return normalize_unit(self.value, self.unit)

    @property
    def shown(self) -> str:
        """답변에 쓸 값 표기. 원문에 단위가 없으면 단위를 괄호로 덧붙여 숫자와 단위가 붙어 보이지 않게 한다."""
        text = self.raw or f"{self.value:g} {self.unit}"
        if not re.search(r"[A-Za-z㎜㎝㎏㎡㏓]", text):
            text = f"{text} (단위 {self.unit})"
        return f"{text} {self.comparator}".strip()


@dataclass(frozen=True)
class DiffItem:
    """같은 항목의 매뉴얼 값과 안전 기준 값을 비교한 결과 하나.

    verdict: 안전 기준이 "이상/이하/초과/미만"일 때는 "충족"·"미충족", 값끼리 같은지만 볼 때는
    "동일"·"다름", 비교할 수 없으면 "비교 불가"다. reason은 판정 이유 한 줄이다.
    """

    name: str
    tech: SpecValue
    safety: SpecValue
    verdict: Verdict
    reason: str


def _same_condition(a: str, b: str) -> bool:
    """조건 문구가 같은지(공백 차이 무시) 본다."""
    return "".join(a.split()) == "".join(b.split())


class DiffChecker:
    """매뉴얼 값과 안전 기준 값을 짝지어 단위를 맞춰 비교한다."""

    def compare(self, tech: list[SpecValue], safety: list[SpecValue]) -> list[DiffItem]:
        """같은 항목 이름의 매뉴얼 값과 안전 기준 값을 모두 짝지어 비교한 결과를 돌려준다.

        짝이 없는 항목은 결과에 넣지 않는다. 다음 경우는 "비교 불가"다.
        - 단위 종류가 달라 같은 기준 단위로 바꿀 수 없을 때(mm와 kg, 알 수 없는 단위)
        - 매뉴얼 값이 "이상·이하" 같은 범위라 한 값으로 볼 수 없을 때
        - 양쪽에 적용 조건이 있는데 서로 다를 때
        안전 기준에 "이상·이하·초과·미만·이내"가 있으면 매뉴얼 값이 그 기준에 맞는지(충족·미충족),
        없으면 두 값이 같은지(동일·다름) 판정한다. 안전 기준에만 조건이 있으면 판정은 하되 이유에 조건을 적는다.
        """
        items: list[DiffItem] = []
        for t in tech:
            for s in safety:
                if t.name == s.name:
                    items.append(self._compare_one(t, s))
        return items

    def _compare_one(self, t: SpecValue, s: SpecValue) -> DiffItem:
        """값 한 쌍을 비교한다."""

        def result(verdict: Verdict, reason: str) -> DiffItem:
            return DiffItem(t.name, t, s, verdict, reason)

        try:
            tech_value, tech_base = t.normalized()
            safety_value, safety_base = s.normalized()
        except ValueError:
            return result("비교 불가", "알 수 없는 단위라 비교할 수 없어요")
        if tech_base != safety_base:
            return result("비교 불가", f"단위 종류가 달라요 ({t.unit}과 {s.unit})")
        if t.comparator:
            return result("비교 불가", f"매뉴얼 값이 범위({t.shown})라서 한 값으로 비교할 수 없어요")
        if t.condition and s.condition and not _same_condition(t.condition, s.condition):
            return result("비교 불가", f"적용 조건이 달라요 (매뉴얼: {t.condition} / 안전 기준: {s.condition})")

        suffix = f" (안전 기준 조건: {s.condition})" if s.condition and not t.condition else ""
        operator = _COMPARATORS.get(s.comparator)
        if operator:
            ok = {
                ">=": tech_value >= safety_value or isclose(tech_value, safety_value, rel_tol=1e-9),
                "<=": tech_value <= safety_value or isclose(tech_value, safety_value, rel_tol=1e-9),
                ">": tech_value > safety_value and not isclose(tech_value, safety_value, rel_tol=1e-9),
                "<": tech_value < safety_value and not isclose(tech_value, safety_value, rel_tol=1e-9),
            }[operator]
            verdict: Verdict = "충족" if ok else "미충족"
            return result(verdict, f"매뉴얼 {t.shown}는 안전 기준 {s.shown}에 {'맞아요' if ok else '맞지 않아요'}{suffix}")
        if s.comparator:  # 모르는 비교 말
            return result("비교 불가", f"안전 기준의 비교 표현({s.comparator})을 알 수 없어요")
        same = isclose(tech_value, safety_value, rel_tol=1e-9)
        verdict = "동일" if same else "다름"
        return result(verdict, f"매뉴얼 {t.shown}, 안전 기준 {s.shown}로 {'같아요' if same else '달라요'}{suffix}")


@dataclass(frozen=True)
class _Item:
    """코드로 비교할 항목 정의: 매뉴얼 표의 열 이름과 안전 문서 문장의 말로 같은 항목을 알아본다."""

    name: str
    tech_columns: tuple[str, ...]
    safety_words: tuple[str, ...]
    safety_context: str  # 안전 문서 문장에 이 말도 함께 있어야 이 항목으로 본다
    default_unit: str  # 매뉴얼 표에 단위가 없을 때 쓰는 단위


# shortcut: 안전기준에 "~ 이상·이하" 같은 기준값이 있고 매뉴얼 사양표에도 같은 값이 있는 항목만 둔다.
# 항목을 늘리려면 한 줄을 더하면 된다. 매뉴얼 사양표에 단위가 없으면 default_unit을 가정한다(PIT 1250 → mm).
COMPARABLE_ITEMS: tuple[_Item, ...] = (
    _Item("피트 깊이", ("PIT",), ("피트의 깊이", "피트 깊이", "깊이"), "피트", "mm"),
    _Item("정격하중", ("Capacity", "정격하중", "Rated Load"), ("정격하중",), "", "kg"),
)

# 안전 문서에서 항목 말 뒤로 이 글자 수 안에 나온 수치만 그 항목의 값으로 본다
_NEAR_CHARS = 30


def _to_float(number: str) -> float:
    """"1,250"·"2.5" 같은 글자를 숫자로 바꾼다."""
    return float(number.replace(",", ""))


def _tech_values(chunk: ScoredChunk) -> list[SpecValue]:
    """매뉴얼 표 행("열: 값 | 열: 값")에서 비교 항목의 값을 뽑는다."""
    values: list[SpecValue] = []
    for line in chunk.text.splitlines():
        fields = [part.split(":", 1) for part in line.split("|") if ":" in part]
        if not fields:
            continue
        label = next((v.strip() for k, v in fields if k.strip().lower().startswith("model")), "")
        for key, raw_value in fields:
            for item in COMPARABLE_ITEMS:
                if not any(re.search(rf"(?<![A-Za-z0-9]){re.escape(col)}(?![A-Za-z0-9])", key, re.IGNORECASE) for col in item.tech_columns):
                    continue
                match = re.match(rf"\s*(?P<num>{_NUMBER})\s*(?P<unit>[A-Za-z㎜㎝㎏]+)?", raw_value)
                if not match:
                    continue
                unit = match.group("unit") or ""
                header_unit = re.search(r"\(\s*([A-Za-z㎜㎝㎏]+)\s*\)", key)
                if not unit:
                    unit = header_unit.group(1) if header_unit else item.default_unit
                raw = match.group("num") + (match.group("unit") or "")
                values.append(SpecValue(item.name, _to_float(match.group("num")), unit, chunk.chunk_id, raw=raw, label=label))
    return values


def _safety_values(chunk: ScoredChunk) -> list[SpecValue]:
    """안전 문서 문장에서 "항목 ... 2.5 m 이하" 꼴의 기준값을 뽑는다. 비교 말이 없는 수치는 기준값으로 보지 않는다."""
    values: list[SpecValue] = []
    for sentence in re.split(r"(?<=[.다요])\s+|\n", chunk.text):
        for item in COMPARABLE_ITEMS:
            if item.safety_context and item.safety_context not in sentence:
                continue
            for word in item.safety_words:
                for hit in re.finditer(re.escape(word), sentence):
                    window = sentence[hit.end(): hit.end() + _NEAR_CHARS]
                    match = _QUANTITY.search(window)
                    if not match or not match.group("cmp"):
                        continue
                    raw = window[match.start(): match.end("unit")]
                    value = SpecValue(item.name, _to_float(match.group("num")), match.group("unit"), chunk.chunk_id, raw=raw, comparator=match.group("cmp"))
                    if value not in values:
                        values.append(value)
    return values


def extract_values(chunk: ScoredChunk) -> list[SpecValue]:
    """청크 한 개에서 비교할 수치를 뽑는다. 기술 문서("tech")는 표 행에서, 안전 문서("secure")는 문장에서 뽑는다."""
    if chunk.doc_type == "tech":
        return _tech_values(chunk)
    if chunk.doc_type == "secure":
        return _safety_values(chunk)
    return []


def _mentions(question: str, label: str) -> bool:
    """질문에 모델 이름(label)이 나오는지 본다. 대소문자와 글자 사이 공백은 무시하고, 앞뒤에 영문·숫자가 붙으면 다른 이름으로 본다."""
    chars = r"\s*".join(re.escape(ch) for ch in label if not ch.isspace())
    return bool(chars) and re.search(rf"(?<![A-Za-z0-9]){chars}(?![A-Za-z0-9])", question, re.IGNORECASE) is not None


def build_comparison(evidence: Evidence, question: str) -> list[DiffItem]:
    """근거 청크에서 수치를 뽑아 비교한다.

    매뉴얼 표 한 청크에 여러 모델 행이 있으므로, 질문에 모델 이름이 나온 행만 비교한다.
    질문에 나온 모델 행이 없으면 어느 값을 비교할지 알 수 없어 빈 목록을 돌려준다.
    """
    tech: list[SpecValue] = []
    safety: list[SpecValue] = []
    for chunk in evidence.chunks:
        for value in extract_values(chunk):
            if chunk.doc_type == "tech":
                if _mentions(question, value.label) and value not in tech:
                    tech.append(value)
            elif value not in safety:
                safety.append(value)
    return DiffChecker().compare(tech, safety)


def format_comparison(items: list[DiffItem]) -> str:
    """비교 결과를 프롬프트에 넣을 글로 만든다. 값은 근거 원문 표기 그대로이고 근거 ID를 함께 적는다. 결과가 없으면 빈 문자열."""
    lines = []
    for item in items:
        who = f" ({item.tech.label})" if item.tech.label else ""
        lines.append(
            f"- {item.name}{who}: 매뉴얼 {item.tech.shown} [근거 ID: {item.tech.source_id}]"
            f" / 안전 문서 {item.safety.shown} [근거 ID: {item.safety.source_id}] → {item.verdict}. {item.reason}"
        )
    return "\n".join(lines)
