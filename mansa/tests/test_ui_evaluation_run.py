"""평가 실행 버튼(_run)이 로딩 레이어를 띄우고 거두는 순서를 확인한다. LLM·파일은 가짜로 바꾼다."""

import unittest
from unittest import mock

import gradio as gr

from features.evaluation.models import EvalProgress, EvalReport
from features.evaluation.testset import TestSetError
from ui import evaluation


def report():
    return EvalReport(
        run_id="r1", testset_title="t", answerer="a", total=2, finished_at="2026-10-30T10:00:00",
        metrics={}, failures=[], latency={},
    )


def collect(generator) -> list:
    return list(generator)


class RunTest(unittest.TestCase):
    def setUp(self):
        mock.patch.object(evaluation, "LLM_API_KEY", "key").start()
        mock.patch.object(evaluation, "LLM_MODEL", "model").start()
        mock.patch.object(evaluation, "QaAnswerer").start()
        mock.patch.object(evaluation, "LlmJudge").start()
        self.warn = mock.patch.object(evaluation.ui, "warn").start()
        self.notify = mock.patch.object(evaluation.ui, "notify").start()
        self.hold = mock.patch.object(evaluation.busy, "hold").start()  # 최소 노출 시간은 기다리지 않는다
        mock.patch.object(evaluation.storage, "load_latest", return_value=None).start()
        mock.patch.object(evaluation, "_view", return_value=("card", "m", "f", "l", None)).start()
        self.events = mock.patch.object(evaluation, "run_evaluation").start()
        self.addCleanup(mock.patch.stopall)

    def test_the_layer_appears_before_any_progress_arrives_and_goes_away_with_the_result(self):
        self.events.return_value = iter([EvalProgress(1, 2), EvalProgress(2, 2, "judge"), report()])
        steps = collect(evaluation._run())
        self.assertEqual([len(step) for step in steps], [7, 7, 7, 7])
        first, *middle, last = steps
        self.assertTrue(first[-1].visible)
        self.assertIn(evaluation.BUSY_TITLE, first[-1].value)
        self.assertEqual(first[1].value, "실행 중")
        self.assertFalse(last[-1].visible)
        # 진행 중에는 레이어를 다시 그리지 않는다(다시 그리면 도는 빛이 처음부터 다시 시작한다)
        self.assertEqual([step[-1] for step in middle], [gr.skip(), gr.skip()])

    def test_the_layer_stays_for_the_minimum_time_before_the_result_is_announced(self):
        calls = []
        self.hold.side_effect = lambda started: calls.append("hold")
        self.notify.side_effect = lambda *a: calls.append("notify")
        self.events.return_value = iter([report()])
        collect(evaluation._run())
        self.assertEqual(calls, ["hold", "notify"])

    def test_a_missing_llm_setting_shows_no_layer(self):
        with mock.patch.object(evaluation, "LLM_API_KEY", ""), mock.patch.object(evaluation.busy, "show") as show:
            steps = collect(evaluation._run())
        show.assert_not_called()
        self.assertEqual([len(step) for step in steps], [7])
        self.warn.assert_called_once()

    def test_a_second_run_while_one_is_running_shows_no_layer(self):
        self.assertTrue(evaluation._RUN_LOCK.acquire(blocking=False))
        self.addCleanup(evaluation._RUN_LOCK.release)
        with mock.patch.object(evaluation.busy, "show") as show:
            steps = collect(evaluation._run())
        show.assert_not_called()
        self.assertEqual([len(step) for step in steps], [7])

    def test_a_broken_test_set_removes_the_layer_after_the_minimum_time(self):
        self.events.side_effect = TestSetError("문항이 없어요")
        steps = collect(evaluation._run())
        self.hold.assert_called_once()
        self.assertTrue(steps[0][-1].visible)
        self.assertFalse(steps[-1][-1].visible)
        self.warn.assert_called_once_with("문항이 없어요")

    def test_an_unexpected_error_removes_the_layer_and_releases_the_lock(self):
        self.events.side_effect = RuntimeError("boom")
        with self.assertLogs("ui.evaluation", level="ERROR"):
            steps = collect(evaluation._run())
        self.assertFalse(steps[-1][-1].visible)
        self.assertTrue(evaluation._RUN_LOCK.acquire(blocking=False))
        evaluation._RUN_LOCK.release()


if __name__ == "__main__":
    unittest.main()
