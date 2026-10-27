import unittest
from unittest.mock import Mock

from core.exceptions import LlmError
from core.schemas import Answer, AnswerDraft, AnswerSection, Clarify, Intent, NoAnswer, ScoredChunk
from features.qa.answer_generator import SAFETY_NOTICE
from features.qa.service import MAX_REGENERATIONS, QAService


def make_service(intent: Intent | None = None, score: float = 0.9) -> tuple[QAService, dict]:
    """모든 단계가 성공하는 가짜 객체로 QAService를 만든다. 테스트마다 필요한 단계만 바꾼다."""
    intent = intent or Intent(intent="spec", model_ids=["CR-100"], parts=["boom"], title="붐 길이")
    draft = AnswerDraft(spec=AnswerSection("12 m", ["c1"]))
    deps = {
        "analyzer": Mock(
            **{"analyze.return_value": intent, "validate_ids.side_effect": lambda i: i}
        ),
        "clarify_policy": Mock(**{"needs_clarification.return_value": False}),
        "retriever": Mock(**{
            "search_manual.return_value": [ScoredChunk("c1", "붐 길이 12 m", score, "tech")],
            "search_safety.return_value": [],
        }),
        "generator": Mock(**{"generate.return_value": draft, "verify_sources.return_value": draft}),
        "history": Mock(**{"save.return_value": 42}),
    }
    return QAService(**deps), deps


class QAServiceAnswerTest(unittest.TestCase):
    def test_success_returns_answer_with_notice_and_saved_id(self):
        service, deps = make_service()

        result = service.answer("CR-100 붐 길이는?", None, member_id=7)

        self.assertIsInstance(result, Answer)
        self.assertEqual(result.conversation_id, 42)
        self.assertEqual(result.spec.text, "12 m")
        self.assertTrue(result.safety.text.startswith(SAFETY_NOTICE))
        deps["analyzer"].analyze.assert_called_once_with("CR-100 붐 길이는?", None, True)
        saved = deps["history"].save.call_args.args
        self.assertEqual(saved[:4], (7, None, "CR-100 붐 길이는?", "붐 길이"))

    def test_follow_up_question_is_not_first(self):
        service, deps = make_service()

        service.answer("작업반경은?", 42, member_id=7)

        deps["analyzer"].analyze.assert_called_once_with("작업반경은?", 42, False)

    def test_analyze_llm_error_returns_llm_failure(self):
        service, deps = make_service()
        deps["analyzer"].analyze.side_effect = LlmError("timeout")

        result = service.answer("질문", None, member_id=7)

        self.assertEqual(result.reason, "llm_failure")
        deps["retriever"].search_manual.assert_not_called()

    def test_out_of_scope_stops_before_search(self):
        service, deps = make_service(Intent(intent="out_of_scope"))

        result = service.answer("내일 날씨는?", None, member_id=7)

        self.assertEqual(result.reason, "out_of_scope")
        deps["retriever"].search_manual.assert_not_called()

    def test_clarification_returns_options_before_search(self):
        service, deps = make_service()
        deps["clarify_policy"].needs_clarification.return_value = True
        options = Clarify("어떤 모델인가요?", ["CR-100", "CR-200"])
        deps["clarify_policy"].build_options.return_value = options

        result = service.answer("붐 길이는?", None, member_id=7)

        self.assertEqual(result.options, ["CR-100", "CR-200"])
        deps["retriever"].search_manual.assert_not_called()

    def test_low_score_returns_no_answer_without_generating(self):
        service, deps = make_service(score=0.1)

        result = service.answer("질문", None, member_id=7)

        self.assertIsInstance(result, NoAnswer)
        self.assertEqual(result.reason, "insufficient_evidence")
        deps["generator"].generate.assert_not_called()
        deps["history"].save.assert_not_called()

    def test_regenerates_until_verification_passes(self):
        service, deps = make_service()
        good = AnswerDraft(spec=AnswerSection("12 m", ["c1"]))
        deps["generator"].verify_sources.side_effect = [None, good]

        result = service.answer("질문", None, member_id=7)

        self.assertIsInstance(result, Answer)
        self.assertEqual(deps["generator"].generate.call_count, 2)

    def test_gives_up_after_max_regenerations(self):
        service, deps = make_service()
        deps["generator"].verify_sources.return_value = None

        result = service.answer("질문", None, member_id=7)

        self.assertEqual(result.reason, "llm_failure")
        self.assertEqual(deps["generator"].generate.call_count, 1 + MAX_REGENERATIONS)
        deps["history"].save.assert_not_called()

    def test_generate_llm_error_returns_llm_failure(self):
        service, deps = make_service()
        deps["generator"].generate.side_effect = LlmError("bad json")

        result = service.answer("질문", None, member_id=7)

        self.assertEqual(result.reason, "llm_failure")
        deps["history"].save.assert_not_called()

    def test_search_failure_propagates(self):
        service, deps = make_service()
        deps["retriever"].search_manual.side_effect = ConnectionError("chroma down")

        with self.assertRaises(ConnectionError):
            service.answer("질문", None, member_id=7)


if __name__ == "__main__":
    unittest.main()
