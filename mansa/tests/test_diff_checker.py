import unittest

from core.schemas import Evidence, ScoredChunk
from features.qa.diff_checker import (
    DiffChecker,
    SpecValue,
    build_comparison,
    extract_values,
    format_comparison,
    normalize_unit,
)

TECH_TEXT = (
    "[HYDRO 501]\n"
    "Model No: HC20022US1 | Capacity: 2000 | Speed: 15 | PIT: 1250\n"
    "Model No: HF07522US | Capacity: 750 | Speed: 15 | PIT: 1300"
)
SAFETY_TEXT = (
    "5.2.1.2 피트의 깊이가 2.5 m 이하인 경우 피트 출입문 또는 승강장문에서 쉽게 접근 가능한 사다리를 둘 수 있다. "
    "피트의 깊이가 1.6 m를 초과하면 상부와 하부에 정지스위치를 2개 설치한다. "
    "피트 바닥의 조도는 50 lx 이상이어야 한다."
)


def tech_chunk(text=TECH_TEXT):
    return ScoredChunk("t1", text, 0.9, "tech")


def safety_chunk(text=SAFETY_TEXT):
    return ScoredChunk("s1", text, 0.8, "secure")


def value(number=1250.0, unit="mm", source="t1", name="피트 깊이", **extra):
    return SpecValue(name, number, unit, source, **extra)


class NormalizeUnitTest(unittest.TestCase):
    def test_length_is_converted_to_millimetres(self):
        self.assertEqual(normalize_unit(2.5, "m"), (2500.0, "mm"))
        self.assertEqual(normalize_unit(30, "cm"), (300.0, "mm"))
        self.assertEqual(normalize_unit(1250, "mm"), (1250.0, "mm"))

    def test_mass_is_converted_to_kilograms(self):
        self.assertEqual(normalize_unit(2, "t"), (2000.0, "kg"))
        self.assertEqual(normalize_unit(500, "g"), (0.5, "kg"))
        self.assertEqual(normalize_unit(750, "kg"), (750.0, "kg"))

    def test_other_units_are_converted_to_their_base_unit(self):
        self.assertEqual(normalize_unit(1.5, "kN"), (1500.0, "N"))
        self.assertEqual(normalize_unit(1, "m/s"), (60.0, "m/min"))
        self.assertEqual(normalize_unit(50, "lx"), (50.0, "lx"))

    def test_compatibility_characters_and_case_are_accepted(self):
        self.assertEqual(normalize_unit(1000, "㎏"), (1000.0, "kg"))
        self.assertEqual(normalize_unit(1250, "㎜"), (1250.0, "mm"))
        self.assertEqual(normalize_unit(0.37, "㎡"), (0.37, "m²"))
        self.assertEqual(normalize_unit(5, " KG "), (5.0, "kg"))
        self.assertEqual(normalize_unit(1, "kN"), (1000.0, "N"))  # kN과 N을 대소문자로 섞지 않는다

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            normalize_unit(1, "lb")


class CompareTest(unittest.TestCase):
    def compare(self, tech, safety):
        return DiffChecker().compare(tech, safety)

    def test_value_inside_a_safety_limit_is_satisfied_after_unit_conversion(self):
        (item,) = self.compare([value(1250, unit="mm")], [value(2.5, unit="m", source="s1", comparator="이하")])
        self.assertEqual(item.verdict, "충족")
        self.assertEqual((item.tech.source_id, item.safety.source_id), ("t1", "s1"))

    def test_value_outside_a_safety_limit_is_not_satisfied(self):
        (item,) = self.compare([value(1250)], [value(1.6, unit="m", source="s1", comparator="이상")])
        self.assertEqual(item.verdict, "미충족")

    def test_each_comparator_is_applied(self):
        cases = [("이상", 1000, True), ("이상", 1001, False), ("이하", 1000, True), ("이하", 999, False),
                 ("초과", 1000, False), ("초과", 999, True), ("미만", 1000, False), ("미만", 1001, True),
                 ("이내", 1000, True), ("이내", 999, False)]
        for comparator, limit, expected in cases:
            with self.subTest(comparator=comparator, limit=limit):
                (item,) = self.compare([value(1000)], [value(limit, source="s1", comparator=comparator)])
                self.assertEqual(item.verdict, "충족" if expected else "미충족")

    def test_equal_values_in_different_units_are_the_same(self):
        (item,) = self.compare([value(1250, unit="mm")], [value(1.25, unit="m", source="s1")])
        self.assertEqual(item.verdict, "동일")

    def test_different_values_are_reported_as_different(self):
        (item,) = self.compare([value(1250)], [value(1.3, unit="m", source="s1")])
        self.assertEqual(item.verdict, "다름")

    def test_different_unit_kinds_cannot_be_compared(self):
        (item,) = self.compare([value(1250, unit="mm")], [value(100, unit="kg", source="s1", comparator="이상")])
        self.assertEqual(item.verdict, "비교 불가")
        self.assertIn("단위 종류", item.reason)

    def test_unknown_unit_cannot_be_compared(self):
        (item,) = self.compare([value(1250, unit="lb")], [value(100, unit="kg", source="s1", comparator="이상")])
        self.assertEqual(item.verdict, "비교 불가")

    def test_a_range_on_the_manual_side_cannot_be_compared(self):
        (item,) = self.compare([value(1250, comparator="이상")], [value(2.5, unit="m", source="s1", comparator="이하")])
        self.assertEqual(item.verdict, "비교 불가")

    def test_conditions_that_differ_cannot_be_compared(self):
        (item,) = self.compare(
            [value(1250, condition="유압식")],
            [value(2.5, unit="m", source="s1", comparator="이하", condition="로프식")],
        )
        self.assertEqual(item.verdict, "비교 불가")
        self.assertIn("조건", item.reason)

    def test_same_conditions_are_compared_ignoring_spaces(self):
        (item,) = self.compare(
            [value(1250, condition="유압 식")],
            [value(2.5, unit="m", source="s1", comparator="이하", condition="유압식")],
        )
        self.assertEqual(item.verdict, "충족")

    def test_a_safety_only_condition_is_kept_in_the_reason(self):
        (item,) = self.compare(
            [value(1250)],
            [value(2.5, unit="m", source="s1", comparator="이하", condition="별도 피트 출입문이 없는 경우")],
        )
        self.assertEqual(item.verdict, "충족")
        self.assertIn("별도 피트 출입문이 없는 경우", item.reason)

    def test_only_items_with_the_same_name_are_paired(self):
        self.assertEqual(self.compare([value(name="정격하중", number=2000, unit="kg")], [value(2.5, unit="m", source="s1", comparator="이하")]), [])

    def test_every_pair_is_compared(self):
        items = self.compare(
            [value(1250)],
            [value(2.5, unit="m", source="s1", comparator="이하"), value(1.6, unit="m", source="s1", comparator="초과")],
        )
        self.assertEqual([i.verdict for i in items], ["충족", "미충족"])

    def test_nothing_to_compare_gives_an_empty_list(self):
        self.assertEqual(self.compare([], []), [])


class ExtractTest(unittest.TestCase):
    def test_manual_rows_give_the_pit_depth_per_model_with_the_assumed_unit(self):
        values = [v for v in extract_values(tech_chunk()) if v.name == "피트 깊이"]
        self.assertEqual([(v.label, v.value, v.unit, v.raw) for v in values],
                         [("HC20022US1", 1250.0, "mm", "1250"), ("HF07522US", 1300.0, "mm", "1300")])

    def test_manual_unit_in_the_column_name_or_after_the_number_wins(self):
        (a,) = extract_values(tech_chunk("Model No: A1 | PIT(m): 1.3"))
        self.assertEqual((a.value, a.unit), (1.3, "m"))
        (b,) = extract_values(tech_chunk("Model No: A1 | PIT: 1300mm"))
        self.assertEqual((b.value, b.unit, b.raw), (1300.0, "mm", "1300mm"))

    def test_capacity_is_read_as_kilograms(self):
        values = [v for v in extract_values(tech_chunk()) if v.name == "정격하중"]
        self.assertEqual([v.value for v in values], [2000.0, 750.0])
        self.assertTrue(all(v.unit == "kg" for v in values))

    def test_columns_that_only_contain_the_word_are_not_taken(self):
        self.assertEqual(extract_values(tech_chunk("Model No: A1 | PITCH: 30 | Speed: 15")), [])

    def test_safety_sentences_give_limits_with_their_comparators(self):
        values = extract_values(safety_chunk())
        self.assertEqual([(v.name, v.value, v.unit, v.comparator, v.raw, v.source_id) for v in values],
                         [("피트 깊이", 2.5, "m", "이하", "2.5 m", "s1"), ("피트 깊이", 1.6, "m", "초과", "1.6 m", "s1")])

    def test_a_safety_number_without_a_comparator_is_not_a_limit(self):
        self.assertEqual(extract_values(safety_chunk("피트의 깊이는 1.6 m 이다.")), [])

    def test_a_safety_sentence_about_another_item_is_ignored(self):
        self.assertEqual(extract_values(safety_chunk("승강로의 깊이가 2 m 이상이어야 한다.")), [])  # "피트"가 없다

    def test_other_document_types_give_nothing(self):
        self.assertEqual(extract_values(ScoredChunk("x", TECH_TEXT, 0.5, "etc")), [])


class BuildComparisonTest(unittest.TestCase):
    EVIDENCE = Evidence(chunks=[tech_chunk(), safety_chunk()])

    def test_only_the_model_named_in_the_question_is_compared(self):
        items = build_comparison(self.EVIDENCE, "HYDRO 501 자동차용 HC20022US1의 PIT 깊이는?")
        self.assertEqual([(i.tech.label, i.tech.value, i.verdict) for i in items],
                         [("HC20022US1", 1250.0, "충족"), ("HC20022US1", 1250.0, "미충족")])

    def test_model_matching_ignores_case_and_spaces(self):
        for question in ("hf07522us의 피트는?", "HF 07522US 의 피트는?"):
            items = build_comparison(self.EVIDENCE, question)
            self.assertEqual({i.tech.label for i in items}, {"HF07522US"})

    def test_a_model_name_inside_a_longer_name_is_not_a_match(self):
        evidence = Evidence(chunks=[tech_chunk("Model No: A1 | PIT: 1250\nModel No: A100 | PIT: 1300"), safety_chunk()])
        self.assertEqual({i.tech.label for i in build_comparison(evidence, "A100 모델의 PIT는?")}, {"A100"})
        self.assertEqual({i.tech.label for i in build_comparison(evidence, "A1의 PIT는?")}, {"A1"})

    def test_without_a_model_in_the_question_nothing_is_compared(self):
        self.assertEqual(build_comparison(self.EVIDENCE, "피트 깊이 기준이 뭐야?"), [])

    def test_missing_safety_or_manual_values_give_nothing(self):
        question = "HC20022US1 PIT는?"
        self.assertEqual(build_comparison(Evidence(chunks=[tech_chunk()]), question), [])
        self.assertEqual(build_comparison(Evidence(chunks=[safety_chunk()]), question), [])

    def test_the_same_value_in_two_chunks_is_not_repeated(self):
        evidence = Evidence(chunks=[tech_chunk(), tech_chunk(), safety_chunk(), safety_chunk()])
        self.assertEqual(len(build_comparison(evidence, "HC20022US1 PIT는?")), 2)


class FormatTest(unittest.TestCase):
    def test_lines_keep_the_original_numbers_and_name_the_source_chunks(self):
        items = build_comparison(Evidence(chunks=[tech_chunk(), safety_chunk()]), "HC20022US1 PIT는?")
        text = format_comparison(items)
        first = text.splitlines()[0]
        self.assertIn("피트 깊이 (HC20022US1)", first)
        self.assertIn("매뉴얼 1250 (단위 mm) [근거 ID: t1]", first)  # 단위를 숫자에 붙이지 않는다
        self.assertIn("안전 문서 2.5 m 이하 [근거 ID: s1]", first)
        self.assertIn("→ 충족", first)
        self.assertNotIn("2500", text)  # 환산한 값은 글에 쓰지 않는다
        self.assertEqual(len(text.splitlines()), 2)

    def test_no_items_give_an_empty_string(self):
        self.assertEqual(format_comparison([]), "")


if __name__ == "__main__":
    unittest.main()
