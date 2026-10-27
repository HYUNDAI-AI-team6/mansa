"""임시 LLM으로 쓰는 OpenAI Codex CLI(`codex exec`) 호출과 출력 해석.

shortcut: 실제 Q&A 파이프라인 대신 쓰는 임시 호출이다. 파이프라인이 완성되면 응답기는
features.dashboard.evaluation.answerer에 새 구현을 추가하고, 채점 LLM도 정식 모델로 바꾼다.
"""

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CODEX_TIMEOUT_SEC = 180


class CodexError(RuntimeError):
    """Codex CLI 실행 실패(미설치, 시간 초과, 오류 종료, 출력 해석 실패)."""


@dataclass(frozen=True)
class CodexResult:
    """Codex 호출 한 번의 결과. tokens는 input+output 합이며 사용량 이벤트가 없으면 None이다."""

    text: str
    tokens: int | None
    latency_sec: float


# 테스트에서 subprocess.run을 바꿔 넣을 수 있게 실행 함수 형태를 맞춘다.
Runner = Callable[..., subprocess.CompletedProcess]


def find_codex() -> str:
    """PATH에서 codex 실행 파일 경로를 찾는다. 없으면 CodexError를 발생시킨다."""
    path = shutil.which("codex")
    if path is None:
        raise CodexError("codex CLI not found in PATH; install it and run 'codex login'")
    return path


def run_codex(
    prompt: str,
    *,
    model: str | None = None,
    output_schema: dict | None = None,
    timeout: float = CODEX_TIMEOUT_SEC,
    runner: Runner = subprocess.run,
    executable: str | None = None,
) -> CodexResult:
    """프롬프트를 stdin으로 `codex exec`에 보내고 마지막 답변과 토큰 수를 반환한다.

    매 호출 빈 임시 폴더에서 read-only sandbox로 실행해 Codex가 저장소 파일을 읽거나 바꾸지 않게 한다.
    output_schema를 주면 `--output-schema`로 최종 답변 JSON 형식을 강제한다.
    외부 프로세스를 실행하며(Codex 사용량 소모), 실패는 모두 CodexError로 알린다.
    지연 시간에는 CLI 기동 시간이 포함된다.
    """
    exe = executable or find_codex()
    with tempfile.TemporaryDirectory(prefix="mansa_codex_") as workdir:
        args = [exe, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", "read-only"]
        if model:
            args += ["-m", model]
        if output_schema is not None:
            schema_path = Path(workdir) / "schema.json"
            schema_path.write_text(json.dumps(output_schema), encoding="utf-8")
            args += ["--output-schema", str(schema_path)]
        args.append("-")

        started = time.perf_counter()
        try:
            proc = runner(
                args,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=workdir,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexError(f"codex timed out after {timeout}s") from exc
        except OSError as exc:
            raise CodexError(f"failed to start codex: {exc}") from exc
        latency = time.perf_counter() - started

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        raise CodexError(f"codex exited with code {proc.returncode}: {tail[0][:200]}")
    text, tokens = parse_jsonl(proc.stdout or "")
    return CodexResult(text=text, tokens=tokens, latency_sec=latency)


def parse_jsonl(stdout: str) -> tuple[str, int | None]:
    """`codex exec --json` 출력에서 마지막 agent_message 텍스트와 토큰 합을 꺼낸다.

    JSON이 아닌 줄은 무시한다. agent_message가 하나도 없으면 CodexError를 발생시킨다.
    turn.completed가 여러 번이면 사용량을 모두 더한다.
    """
    text: str | None = None
    tokens: int | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
        ):
            text = str(item.get("text", ""))
        usage = event.get("usage")
        if event.get("type") == "turn.completed" and isinstance(usage, dict):
            used = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            tokens = used if tokens is None else tokens + used
    if text is None:
        raise CodexError("codex output had no agent_message")
    return text, tokens
