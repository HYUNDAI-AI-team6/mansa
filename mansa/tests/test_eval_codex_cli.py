import subprocess
import unittest
from unittest import mock

from features.evaluation.codex_cli import CodexError, find_codex, parse_jsonl, run_codex

# codex exec --json 실제 출력(Codex CLI 0.164.0, 질문 "1+1"). 형식이 바뀌면 새 출력으로 교체한다.
CODEX_OUTPUT = "\n".join([
    '{"type":"thread.started","thread_id":"01a17b5e-6177-7360-82fb-0c3f8c8ab178"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"2"}}',
    '{"type":"turn.completed","usage":{"input_tokens":20340,"cached_input_tokens":13440,'
    '"cache_write_input_tokens":0,"output_tokens":59,"reasoning_output_tokens":52}}',
])


def fake_runner(stdout="", returncode=0, stderr=""):
    """subprocess.run 대신 쓰는 가짜 실행 함수. 받은 인자를 calls에 남긴다."""
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    run.calls = calls
    return run


class ParseJsonlTest(unittest.TestCase):
    def test_real_output(self):
        text, tokens = parse_jsonl(CODEX_OUTPUT)
        self.assertEqual(text, "2")
        self.assertEqual(tokens, 20340 + 59)

    def test_no_message(self):
        with self.assertRaises(CodexError):
            parse_jsonl('{"type":"turn.started"}\nnot json\n')

    def test_no_usage_gives_none(self):
        line = '{"type":"item.completed","item":{"type":"agent_message","text":"a"}}'
        self.assertEqual(parse_jsonl(line), ("a", None))


class RunCodexTest(unittest.TestCase):
    def test_success_uses_stdin_and_readonly(self):
        runner = fake_runner(CODEX_OUTPUT)
        result = run_codex("질문", runner=runner, executable="codex", model="m1")
        args, kwargs = runner.calls[0]
        self.assertEqual(result.text, "2")
        self.assertEqual(kwargs["input"], "질문")
        self.assertIn("read-only", args)
        self.assertEqual(args[-1], "-")
        self.assertIn("m1", args)
        self.assertGreaterEqual(result.latency_sec, 0)

    def test_output_schema_file_passed(self):
        runner = fake_runner(CODEX_OUTPUT)
        run_codex("q", runner=runner, executable="codex", output_schema={"type": "object"})
        self.assertIn("--output-schema", runner.calls[0][0])

    def test_nonzero_exit(self):
        runner = fake_runner(returncode=1, stderr="line1\nauth failed")
        with self.assertRaisesRegex(CodexError, "code 1: auth failed"):
            run_codex("q", runner=runner, executable="codex")

    def test_timeout(self):
        def runner(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        with self.assertRaisesRegex(CodexError, "timed out"):
            run_codex("q", runner=runner, executable="codex", timeout=1)

    def test_not_installed(self):
        with mock.patch("features.evaluation.codex_cli.shutil.which", return_value=None):
            with self.assertRaisesRegex(CodexError, "not found"):
                find_codex()


if __name__ == "__main__":
    unittest.main()
