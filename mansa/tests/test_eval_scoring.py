import unittest

import openai

from core.exceptions import LlmError
from features.evaluation.judge import JudgeOutput, LlmJudge
from features.evaluation.models import AnswerRecord, Judgement, NumberCheck, TestCase
from features.evaluation.scoring import (
    classify_failure,
    collect_llm_errors,
    collect_number_notes,
    compute_latency,
    compute_metrics,
    contains_number,
    score_case,
)

L2 = TestCase("T1", "브레이크 갭 기준값", "L2", ["0.5 mm"], ["doc:1"])
L3 = TestCase("T2", "[모델 B] 정격하중", "L3", ["1000 kg"], [])
OK = Judgement(True, "일관됨")


class NumberMatchTest(unittest.TestCase):
    def test_section_and_spaces(self):
        self.assertTrue(contains_number("5.6절을 참고하세요", "5.6절"))
        self.assertTrue(contains_number("갭은 0.5mm 입니다", "0.5 mm"))

    def test_not_part_of_other_number(self):
        self.assertFalse(contains_number("110 mm", "10 mm"))
        self.assertFalse(contains_number("10.5 mm", "10"))
        self.assertFalse(contains_number("105 m/min", "10"))

    def test_fullwidth_and_thousands(self):
        self.assertTrue(contains_number("정격하중 １，０００ ｋｇ", "1000 kg"))
        self.assertTrue(contains_number("1,000kg", "1000 kg"))

    def test_unit_case_must_match(self):
        self.assertFalse(contains_number("1 mPa", "1 MPa"))
        self.assertFalse(contains_number("1000 KG", "1000 kg"))
        self.assertTrue(contains_number("1 ㎫", "1 MPa"))
        self.assertFalse(contains_number("0.5 mmhg", "0.5 mm"))

    def test_not_part_of_exponent_or_fraction(self):
        self.assertFalse(contains_number("1e5 mm", "5 mm"))
        self.assertFalse(contains_number("1E-5 mm", "-5 mm"))
        self.assertFalse(contains_number("1/1000 kg", "1000 kg"))
        self.assertFalse(contains_number("1 / 1000 kg", "1000 kg"))
        self.assertFalse(contains_number("1e5", "1"))

    def test_compound_unit(self):
        for answer in ["10 N·m", "10 N*m", "10 N × m", "10 N.m", "10 N ⋅ m"]:
            self.assertFalse(contains_number(answer, "10 N"), answer)
        self.assertFalse(contains_number("0.5 mm^2", "0.5 mm"))
        self.assertFalse(contains_number("0.5 mm ^ 2", "0.5 mm"))
        self.assertTrue(contains_number("토크 10 N · m", "10 N·m"))
        self.assertTrue(contains_number("10 N*m", "10 N*m"))

    def test_compound_symbol_allows_ranges_and_dimensions(self):
        self.assertTrue(contains_number("10 mm × 20 mm", "10 mm"))
        self.assertTrue(contains_number("10N-20N", "10 N"))
        self.assertTrue(contains_number("10-20", "10"))
        self.assertTrue(contains_number("10 N-m", "10 N"))
        self.assertTrue(contains_number("허용 범위 5-10 mm", "10 mm"))
        self.assertTrue(contains_number("5mm-10mm", "10 mm"))
        self.assertTrue(contains_number("-5~-10 °C", "-10 °C"))
        self.assertFalse(contains_number("편차 -10 mm", "10 mm"))
        self.assertFalse(contains_number("1e-5 mm", "5 mm"))
        self.assertTrue(contains_number("기준은 0.5mm.", "0.5 mm"))

    def test_greek_unit_spacing(self):
        self.assertTrue(contains_number("10Ω", "10 Ω"))
        self.assertTrue(contains_number("10 Ω", "10Ω"))
        self.assertTrue(contains_number("10 Ω", "10 Ω"))  # 옴 기호(U+2126)는 NFKC로 Ω가 된다
        self.assertFalse(contains_number("10 Ω", "10"))

    def test_comma_separated_list(self):
        self.assertTrue(contains_number("500kg,1000kg", "1000 kg"))
        self.assertTrue(contains_number("500kg,1000kg", "500 kg"))
        self.assertFalse(contains_number("1,000,500 kg", "500 kg"))

    def test_sign_must_match(self):
        self.assertFalse(contains_number("-1000 kg", "1000 kg"))
        self.assertFalse(contains_number("−1000 kg", "1000 kg"))
        self.assertFalse(contains_number("+1000 kg", "1000 kg"))
        self.assertTrue(contains_number("편차는 - 5 mm", "-5 mm"))
        self.assertFalse(contains_number("편차는 5 mm", "-5 mm"))

    def test_unit_must_match_fully(self):
        self.assertFalse(contains_number("0.5 mm2", "0.5 mm"))
        self.assertFalse(contains_number("0.5 mm²", "0.5 mm"))
        self.assertFalse(contains_number("1000 kg/h", "1000 kg"))
        self.assertFalse(contains_number("1000 kgf", "1000 kg"))
        self.assertFalse(contains_number("10 mm", "10"))
        self.assertFalse(contains_number("10%", "10"))
        self.assertFalse(contains_number("105 m/min", "105 m"))

    def test_unit_boundary_allows_text_after(self):
        self.assertTrue(contains_number("0.5 mm 이하", "0.5 mm"))
        self.assertTrue(contains_number("기준은 0.5mm.", "0.5 mm"))
        self.assertTrue(contains_number("105 m / min 입니다", "105 m/min"))
        self.assertTrue(contains_number("(1000 kg), 2개", "1000 kg"))
        self.assertTrue(contains_number("１０％", "10%"))
        self.assertTrue(contains_number("0.5 ㎜", "0.5 mm"))


class ScoreCaseTest(unittest.TestCase):
    def test_none_vs_empty_sources(self):
        no_info = score_case(L2, AnswerRecord("T1", "0.5 mm"), OK)
        self.assertIsNone(no_info.retrieval_hit)
        self.assertIsNone(no_info.source_ok)
        empty = score_case(L2, AnswerRecord("T1", "0.5 mm", cited_ids=[], retrieved_ids=[]), OK)
        self.assertIs(empty.retrieval_hit, False)
        self.assertIs(empty.source_ok, False)
        self.assertIsNone(empty.overattach)

    def test_retrieval_source_overattach(self):
        record = AnswerRecord(
            "T1", "0.5 mm", cited_ids=["doc:1", "doc:9"], retrieved_ids=["doc:1", "doc:2"]
        )
        score = score_case(L2, record, OK)
        self.assertTrue(score.retrieval_hit)
        self.assertTrue(score.source_ok)
        self.assertEqual(score.overattach, 0.5)
        self.assertTrue(score.numeric_ok)
        self.assertTrue(score.consistent)

    def test_retrieval_recall_threshold(self):
        def hit(expected, retrieved):
            case = TestCase("T1", "q", "L2", [], expected)
            return score_case(case, AnswerRecord("T1", "a", retrieved_ids=retrieved), OK).retrieval_hit

        self.assertTrue(hit(["a#p1"], ["a#p1", "b#p2"]))
        self.assertTrue(hit(["a#p1", "b#p2", "c#p3"], ["a#p1", "c#p3"]))
        self.assertFalse(hit(["a#p1", "b#p2"], ["a#p1"]))
        self.assertFalse(hit(["a#p1", "b#p2", "c#p3"], ["a#p1"]))

    def test_error_fails_computable_metrics(self):
        score = score_case(L2, AnswerRecord("T1", error="timeout"), None)
        self.assertEqual(
            (score.numeric_ok, score.retrieval_hit, score.consistent), (False, False, False)
        )


class LlmNumberCheckTest(unittest.TestCase):
    TORQUE = TestCase("T9", "체결 토크", "L2", ["10 N·m"], [])

    def judged(self, matched, quote, consistent=True):
        return Judgement(consistent, "ok", numbers=[NumberCheck("10 N·m", matched, quote)])

    def test_llm_rescues_rule_miss_with_verified_quote(self):
        record = AnswerRecord("T9", "체결 토크는 10 N - m 입니다")
        score = score_case(self.TORQUE, record, self.judged(True, "10 N - m"))
        self.assertTrue(score.numeric_ok)
        self.assertEqual(score.numbers_by_llm, {"10 N·m": "10 N - m"})
        notes = collect_number_notes(self.TORQUE, score)
        self.assertEqual([(n.kind, n.quote) for n in notes], [("LLM 통과", "10 N - m")])

    def test_quote_not_in_answer_is_rejected(self):
        record = AnswerRecord("T9", "체결 토크는 규정값을 따릅니다")
        score = score_case(self.TORQUE, record, self.judged(True, "10 N·m"))
        self.assertFalse(score.numeric_ok)
        self.assertEqual(score.numbers_by_llm, {})

    def test_quote_with_other_digits_is_rejected(self):
        case = TestCase("T8", "길이", "L2", ["1000 mm"], [])
        record = AnswerRecord("T8", "길이는 1 m 입니다")
        judgement = Judgement(True, "ok", numbers=[NumberCheck("1000 mm", True, "1 m")])
        self.assertFalse(score_case(case, record, judgement).numeric_ok)

    def test_rule_pass_with_llm_dispute_keeps_rule(self):
        record = AnswerRecord("T1", "갭은 0.5 mm")
        judgement = Judgement(True, "ok", numbers=[NumberCheck("0.5 mm", False, "")])
        score = score_case(L2, record, judgement)
        self.assertTrue(score.numeric_ok)
        self.assertEqual(score.numbers_disputed, ["0.5 mm"])
        self.assertEqual([n.kind for n in collect_number_notes(L2, score)], ["LLM 이견"])

    def test_matches_by_position_when_expected_rewritten(self):
        record = AnswerRecord("T9", "체결 토크는 10 N - m 입니다")
        judgement = Judgement(True, "ok", numbers=[NumberCheck("10 N.m", True, "10 N - m")])
        self.assertTrue(score_case(self.TORQUE, record, judgement).numeric_ok)

    def test_judge_error_uses_rule_only(self):
        record = AnswerRecord("T9", "체결 토크는 10 N - m 입니다")
        score = score_case(self.TORQUE, record, Judgement(None, error="timeout"))
        self.assertFalse(score.numeric_ok)
        self.assertEqual(collect_number_notes(self.TORQUE, score), [])


class FailureTest(unittest.TestCase):
    def test_retrieval_cause(self):
        record = AnswerRecord("T1", "0.5 mm", retrieved_ids=["doc:2"])
        failure = classify_failure(L2, record, score_case(L2, record, OK), OK)
        self.assertEqual(failure.cause, "검색")
        self.assertEqual(failure.detail, "doc:1 → doc:2")

    def test_lookup_cause(self):
        record = AnswerRecord("T2", "등록되지 않은 모델입니다")
        failure = classify_failure(L3, record, score_case(L3, record, OK), OK)
        self.assertEqual(failure.cause, "조회")
        self.assertEqual(failure.detail, "1000 kg → 없음")

    def test_generation_cause(self):
        record = AnswerRecord("T1", "갭은 0.7 mm")
        failure = classify_failure(L2, record, score_case(L2, record, OK), OK)
        self.assertEqual(failure.cause, "생성")
        self.assertEqual(failure.detail, "0.5 mm → 0.7 mm")

    def test_answer_error_is_llm_error_not_failure(self):
        record = AnswerRecord("T1", error="timeout")
        self.assertIsNone(classify_failure(L2, record, score_case(L2, record, None), None))
        errors = collect_llm_errors(L2, record, None)
        self.assertEqual([(e.stage, e.reason) for e in errors], [("답변", "timeout")])
        good = AnswerRecord("T1", "0.5 mm")
        self.assertIsNone(classify_failure(L2, good, score_case(L2, good, OK), OK))

    def test_judge_error_counts_as_fail_and_is_listed(self):
        record = AnswerRecord("T1", "0.5 mm")
        judge_err = Judgement(None, error="codex timed out after 180s")
        score = score_case(L2, record, judge_err)
        self.assertIs(score.consistent, False)
        self.assertIsNone(classify_failure(L2, record, score, judge_err))
        errors = collect_llm_errors(L2, record, judge_err)
        self.assertEqual([(e.stage, e.reason) for e in errors],
                         [("채점", "codex timed out after 180s")])

    def test_judge_error_with_quality_failure(self):
        record = AnswerRecord("T1", "0.7 mm")
        judge_err = Judgement(None, error="boom")
        failure = classify_failure(L2, record, score_case(L2, record, judge_err), judge_err)
        self.assertEqual(failure.detail, "0.5 mm → 0.7 mm")


class MetricsTest(unittest.TestCase):
    def test_no_source_info_gives_none_even_with_errors(self):
        scores = [
            score_case(L2, AnswerRecord("T1", "0.5 mm"), OK),
            score_case(L2, AnswerRecord("T1", error="x"), None),
        ]
        metrics = compute_metrics(scores)
        self.assertIsNone(metrics["검색 적중률"])
        self.assertIsNone(metrics["출처 정확도"])
        self.assertIsNone(metrics["과잉 첨부율"])
        self.assertEqual(metrics["수치 정확도"], 50.0)
        self.assertEqual(metrics["표현 일관성"], 50.0)

    def test_all_errors_count_as_zero_percent(self):
        scores = [score_case(L2, AnswerRecord("T1", error="timeout"), None) for _ in range(3)]
        metrics = compute_metrics(scores)
        self.assertEqual(metrics["수치 정확도"], 0.0)
        self.assertEqual(metrics["표현 일관성"], 0.0)
        self.assertIsNone(metrics["검색 적중률"])
        self.assertIsNone(metrics["출처 정확도"])

    def test_latency_uses_measured_only(self):
        records = [AnswerRecord(str(i), latency_sec=2.0, tokens=100) for i in range(28)]
        records += [AnswerRecord("e1", error="x"), AnswerRecord("e2", error="x")]
        latency = compute_latency(records)
        self.assertEqual(latency["기술 Q&A 평균 지연"], 2.0)
        self.assertEqual(latency["기술 Q&A 평균 토큰"], 100)
        self.assertEqual(list(latency), ["기술 Q&A 평균 지연", "기술 Q&A 평균 토큰"])


class JudgeTest(unittest.TestCase):
    def test_llm_judge_passes_schema_and_converts_numbers(self):
        calls = []

        def call(workflow, prompt, schema):
            calls.append((workflow, prompt, schema))
            return {"consistent": True, "reason": "ok",
                    "numbers": [{"expected": "0.5 mm", "matched": True, "quote": "0.5mm"}]}

        judgement = LlmJudge(call=call).judge(L2, AnswerRecord("T1", "갭은 0.5mm"))
        workflow, prompt, schema = calls[0]
        self.assertEqual((workflow, schema), ("L2", JudgeOutput))
        self.assertIn("갭은 0.5mm", prompt)
        self.assertEqual(judgement, Judgement(True, "ok",
                                              numbers=[NumberCheck("0.5 mm", True, "0.5mm")]))

    def test_llm_judge_handles_error(self):
        def failing(workflow, prompt, schema):
            raise LlmError("L2 LLM failed after 3 attempts")

        failed = LlmJudge(call=failing).judge(L2, AnswerRecord("T1", "a"))
        self.assertEqual((failed.consistent, failed.error, failed.numbers),
                         (None, "L2 LLM failed after 3 attempts", []))

    def test_llm_judge_handles_content_filter(self):
        def filtered(workflow, prompt, schema):
            raise openai.ContentFilterFinishReasonError()

        failed = LlmJudge(call=filtered).judge(L2, AnswerRecord("T1", "a"))
        self.assertIsNone(failed.consistent)
        self.assertTrue(failed.error)


if __name__ == "__main__":
    unittest.main()
