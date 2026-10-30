import unittest
from types import SimpleNamespace
from unittest import mock

from core.exceptions import LlmError
from core.schemas import Answer, AnswerDraft, AnswerSection, Evidence, Intent, NoAnswer, ScoredChunk
from features.history.service import HistoryService
from features.history.store import MemoryHistoryStore
from features.qa.answer_generator import SAFETY_NOTICE, AnswerGenerator
from features.qa.service import QAService

EVIDENCE = Evidence(chunks=[
    ScoredChunk("m1", "권상기 브레이크 갭은 0.5 mm 이하로 유지한다.", 0.9, "tech"),
    ScoredChunk("s1", "브레이크 점검 전 주전원을 차단한다. 체결 토크는 40 N·m 이다.", 0.8, "secure"),
])


def section(text="", *ids):
    return AnswerSection(text, list(ids))


def draft(procedure=None, spec=None, safety=None, diff=None):
    return AnswerDraft(procedure or section(), spec or section(), safety or section(), diff or section())


def llm_output(procedure=("", []), spec=("", []), safety=("", []), diff=("", [])):
    """complete가 돌려주는 dict 모양."""
    parts = {"procedure": procedure, "spec": spec, "safety": safety, "diff": diff}
    return {name: {"text": text, "source_ids": ids} for name, (text, ids) in parts.items()}


class FakeComplete:
    """core.llm.complete 대신 쓰는 가짜. 정해 둔 결과를 순서대로 돌려주거나 던지고 호출을 기록한다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, workflow, prompt, schema, history=None):
        self.calls.append({"workflow": workflow, "prompt": prompt, "schema": schema})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class GenerateTest(unittest.TestCase):
    def test_converts_llm_output_to_draft(self):
        fake = FakeComplete(llm_output(procedure=("갭을 측정한다.", ["m1"]), spec=("0.5 mm 이하", ["m1"])))
        result = AnswerGenerator(fake).generate("브레이크 갭 기준은?", EVIDENCE)
        self.assertEqual(result.procedure, section("갭을 측정한다.", "m1"))
        self.assertEqual(result.spec, section("0.5 mm 이하", "m1"))
        self.assertEqual(result.diff, section())

    def test_prompt_has_question_and_every_chunk(self):
        fake = FakeComplete(llm_output())
        AnswerGenerator(fake).generate("브레이크 갭 기준은?", EVIDENCE)
        call = fake.calls[0]
        self.assertEqual(call["workflow"], "L2")
        self.assertIn("브레이크 갭 기준은?", call["prompt"])
        self.assertIn("[ID: m1] (매뉴얼)\n권상기 브레이크 갭은 0.5 mm 이하로 유지한다.", call["prompt"])
        self.assertIn("[ID: s1] (안전 문서)", call["prompt"])
        self.assertEqual(set(call["schema"].model_fields), {"procedure", "spec", "safety", "diff"})

    def test_llm_error_is_passed_to_caller(self):
        with self.assertRaises(LlmError):
            AnswerGenerator(FakeComplete(LlmError("timeout"))).generate("질문", EVIDENCE)


class VerifySourcesTest(unittest.TestCase):
    def setUp(self):
        self.generator = AnswerGenerator(FakeComplete())

    def check(self, value):
        return self.generator.verify_sources(value, EVIDENCE)

    def test_valid_draft_is_returned(self):
        value = draft(spec=section("갭은 0.5mm 이하", "m1"), safety=section("토크 40 N·m", "s1"))
        self.assertIs(self.check(value), value)  # 띄어쓰기가 달라도 같은 수치로 본다

    def test_all_empty_fails(self):
        self.assertIsNone(self.check(draft()))

    def test_text_without_source_fails(self):
        self.assertIsNone(self.check(draft(procedure=section("갭을 측정한다."))))

    def test_unknown_source_id_fails(self):
        self.assertIsNone(self.check(draft(procedure=section("갭을 측정한다.", "m1", "x9"))))

    def test_number_not_in_cited_source_fails(self):
        self.assertIsNone(self.check(draft(spec=section("갭은 0.7 mm 이하", "m1"))))

    def test_number_only_in_uncited_source_fails(self):
        # 40 N·m는 s1에만 있다. m1만 인용했으면 맞지 않는다
        self.assertIsNone(self.check(draft(spec=section("토크는 40 N·m", "m1"))))

    def test_step_numbers_are_not_checked(self):
        value = draft(procedure=section("1. 주전원을 차단한다.\n2. 갭을 측정한다.", "s1", "m1"))
        self.assertIs(self.check(value), value)

    def test_empty_section_needs_no_source(self):
        value = draft(spec=section("0.5 mm 이하", "m1"), diff=section("   "))
        self.assertIs(self.check(value), value)


class QAServiceWithGeneratorTest(unittest.TestCase):
    """QAService에 진짜 AnswerGenerator·HistoryService를 넣고 LLM만 가짜로 바꾼다."""

    def build(self, *outcomes):
        intent = Intent(intent="procedure", title="브레이크 갭")
        self.fake = FakeComplete(*outcomes)
        return QAService(
            analyzer=SimpleNamespace(analyze=lambda q, cid, first: intent, validate_ids=lambda i: i),
            clarify_policy=SimpleNamespace(needs_clarification=lambda i: False),
            retriever=SimpleNamespace(search_manual=lambda q, i: EVIDENCE.chunks[:1],
                                      search_safety=lambda q, i: EVIDENCE.chunks[1:]),
            generator=AnswerGenerator(self.fake),
            history=HistoryService(MemoryHistoryStore()),
        )

    def test_answer_has_sections_and_safety_notice(self):
        qa = self.build(llm_output(spec=("0.5 mm 이하", ["m1"]), safety=("주전원을 차단한다.", ["s1"])))
        result = qa.answer("브레이크 갭 기준은?", None, 1)
        self.assertIsInstance(result, Answer)
        self.assertEqual(result.spec.text, "0.5 mm 이하")
        self.assertTrue(result.safety.text.startswith(SAFETY_NOTICE))
        self.assertEqual(result.conversation_id, 1)

    def test_wrong_number_is_regenerated(self):
        qa = self.build(llm_output(spec=("0.7 mm 이하", ["m1"])), llm_output(spec=("0.5 mm 이하", ["m1"])))
        result = qa.answer("브레이크 갭 기준은?", None, 1)
        self.assertEqual(result.spec.text, "0.5 mm 이하")
        self.assertEqual(len(self.fake.calls), 2)

    def test_llm_failure_becomes_no_answer(self):
        result = self.build(LlmError("timeout")).answer("브레이크 갭 기준은?", None, 1)
        self.assertIsInstance(result, NoAnswer)
        self.assertEqual(result.reason, "llm_failure")


class DiffComparisonTest(unittest.TestCase):
    """#53 기준 차이: 코드가 비교한 결과를 답변 프롬프트에 넣고, 그 값을 근거 검사가 인정한다."""

    QUESTION = "HYDRO 501 자동차용 HC20022US1의 PIT 깊이와 피트 안전기준을 알려줘"
    EVIDENCE = Evidence(chunks=[
        ScoredChunk("t1", "Model No: HC20022US1 | Capacity: 2000 | PIT: 1250", 0.9, "tech"),
        ScoredChunk("s1", "피트의 깊이가 2.5 m 이하인 경우 사다리를 둘 수 있다.", 0.8, "secure"),
    ])

    def test_prompt_carries_the_code_comparison_with_original_numbers_and_source_ids(self):
        fake = FakeComplete(llm_output())
        AnswerGenerator(fake).generate(self.QUESTION, self.EVIDENCE)
        prompt = fake.calls[0]["prompt"]
        self.assertIn("[코드로 비교한 결과]", prompt)
        self.assertIn("피트 깊이 (HC20022US1): 매뉴얼 1250 (단위 mm) [근거 ID: t1]", prompt)
        self.assertIn("안전 문서 2.5 m 이하 [근거 ID: s1] → 충족", prompt)
        self.assertNotIn("2500", prompt)  # 환산한 값은 프롬프트에 넣지 않는다

    def test_prompt_says_none_when_nothing_could_be_compared(self):
        fake = FakeComplete(llm_output())
        AnswerGenerator(fake).generate("브레이크 갭 기준은?", EVIDENCE)
        self.assertTrue(fake.calls[0]["prompt"].endswith("[코드로 비교한 결과]\n없음"))

    def test_a_failing_comparison_does_not_stop_the_answer(self):
        fake = FakeComplete(llm_output(spec=("0.5 mm 이하", ["m1"])))
        with mock.patch("features.qa.answer_generator.build_comparison", side_effect=RuntimeError("boom")):
            with self.assertLogs("features.qa.answer_generator", level="ERROR"):  # 오류는 로그로 남긴다
                result = AnswerGenerator(fake).generate("브레이크 갭 기준은?", EVIDENCE)
        self.assertEqual(result.spec.text, "0.5 mm 이하")
        self.assertTrue(fake.calls[0]["prompt"].endswith("없음"))

    def test_a_unit_the_code_attached_to_a_manual_value_passes_the_source_check(self):
        diff = ("HC20022US1의 PIT는 1250 mm이고 안전 문서 기준 2.5 m 이하에 맞아요.", ["t1", "s1"])
        draft = AnswerGenerator().verify_sources(
            AnswerDraft(section(), section(), section(), AnswerSection(*diff)), self.EVIDENCE, self.QUESTION
        )
        self.assertIsNotNone(draft)

    def test_a_converted_value_is_still_rejected(self):
        diff = ("HC20022US1의 PIT는 1.25 m이고 안전 문서 기준 2.5 m 이하에 맞아요.", ["t1", "s1"])
        draft = AnswerGenerator().verify_sources(
            AnswerDraft(section(), section(), section(), AnswerSection(*diff)), self.EVIDENCE, self.QUESTION
        )
        self.assertIsNone(draft)

    def test_the_assumed_unit_only_counts_for_the_chunk_it_came_from(self):
        spec = ("HC20022US1의 PIT는 1250 mm예요.", ["s1"])  # 1250이 있는 t1을 인용하지 않았다
        draft = AnswerGenerator().verify_sources(
            AnswerDraft(section(), AnswerSection(*spec), section(), section()), self.EVIDENCE, self.QUESTION
        )
        self.assertIsNone(draft)

    def test_without_the_question_nothing_extra_is_allowed(self):
        diff = ("PIT는 1250 mm이에요.", ["t1"])
        draft = AnswerGenerator().verify_sources(
            AnswerDraft(section(), section(), section(), AnswerSection(*diff)), self.EVIDENCE
        )
        self.assertIsNone(draft)


if __name__ == "__main__":
    unittest.main()