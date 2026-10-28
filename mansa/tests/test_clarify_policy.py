import unittest
from types import SimpleNamespace

from core.schemas import Clarify, Intent
from features.master.taxonomy import TaxonomyService
from features.qa.clarify_policy import MODEL_QUESTION, PART_QUESTION, RuleClarifyPolicy
from features.qa.service import QAService

PARTS = ["메인 로프", "권상기"]


def policy(parts=PARTS):
    """분류표 부위만 가진 가짜 TaxonomyService로 정책을 만든다."""
    return RuleClarifyPolicy(SimpleNamespace(taxonomy=SimpleNamespace(parts=parts)))


def intent(models=(), parts=(), task=None):
    return Intent(intent="procedure", model_ids=list(models), parts=list(parts), task=task)


class NeedsClarificationTest(unittest.TestCase):
    def test_clear_question_is_not_asked(self):
        self.assertFalse(policy().needs_clarification(intent(["[모델 A]"], ["메인 로프"])))

    def test_missing_model_is_not_asked(self):
        # 검색에 모델 필터가 없어 모델이 없어도 되묻지 않는다
        self.assertFalse(policy().needs_clarification(intent(parts=["메인 로프"])))

    def test_task_alone_is_enough(self):
        self.assertFalse(policy().needs_clarification(intent(task="메인 로프 점검")))

    def test_two_models_are_asked(self):
        self.assertTrue(policy().needs_clarification(intent(["[모델 A]", "[모델 B]"], ["메인 로프"])))

    def test_no_part_and_no_task_is_asked(self):
        self.assertTrue(policy().needs_clarification(intent(["[모델 A]"])))


class BuildOptionsTest(unittest.TestCase):
    def test_model_options_are_the_found_models(self):
        result = policy().build_options(intent(["[모델 A]", "[모델 B]"]))
        self.assertEqual(result, Clarify(MODEL_QUESTION, ["[모델 A]", "[모델 B]"]))

    def test_part_options_come_from_taxonomy(self):
        self.assertEqual(policy().build_options(intent()), Clarify(PART_QUESTION, PARTS))

    def test_options_are_copies(self):
        parts = list(PARTS)
        policy(parts).build_options(intent()).options.append("추가")
        self.assertEqual(parts, PARTS)  # 선택지를 바꿔도 분류표는 그대로다

    def test_with_real_taxonomy(self):
        result = RuleClarifyPolicy(TaxonomyService.from_directory()).build_options(intent())
        self.assertEqual(result.options, ["메인 로프", "브레이크 라이닝", "도어 센서", "비상정지장치", "권상기"])


class QAServiceClarifyTest(unittest.TestCase):
    def test_ambiguous_question_returns_clarify_without_search(self):
        calls = []
        qa = QAService(
            analyzer=SimpleNamespace(analyze=lambda q, cid, first: intent(["[모델 A]", "[모델 B]"], ["권상기"]),
                                     validate_ids=lambda i: i),
            clarify_policy=policy(),
            retriever=SimpleNamespace(search_manual=lambda q, i: calls.append("search") or [],
                                      search_safety=lambda q, i: calls.append("search") or []),
            generator=None,
            history=None,
        )
        result = qa.answer("권상기 점검 방법", None, 1)
        self.assertEqual(result, Clarify(MODEL_QUESTION, ["[모델 A]", "[모델 B]"]))
        self.assertEqual(calls, [])  # 되묻기면 검색·생성을 하지 않는다


if __name__ == "__main__":
    unittest.main()