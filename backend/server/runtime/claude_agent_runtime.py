"""RuntimeOrchestrator backed by the Claude Agent SDK.

The SDK runs in a separate process (``claude_agent_runner``) with a minimal
environment. This class supervises it: enforces the wall-clock timeout, polls
for cancel/budget/shutdown via ``ctx.poll``, and terminates the whole process
group on abort.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import structlog

from server.core.config import Settings
from server.core.errors import ErrorCode
from server.runtime.base import Abort, JobContext, RuntimeOrchestrator, RuntimeResult
from server.runtime.openmontage_runtime import build_agent_env
from server.runtime.prompt_builder import build_continuation_prompt, build_system_prompt, build_user_prompt

log = structlog.get_logger(__name__)

TERM_GRACE_SECONDS = 10


class ClaudeAgentRuntime(RuntimeOrchestrator):
    name = "claude_agent_sdk"
    # Overridable (tests substitute a fake runner); default is the real SDK runner.
    runner_cmd: list[str] | None = None

    def __init__(self, settings: Settings):
        self.settings = settings

    def _spec(self, ctx: JobContext) -> dict:
        s = self.settings
        transcript = s.agent_transcript_dir / f"{ctx.generation_id}.jsonl" if s.agent_transcript_dir else None
        return {
            "engine_dir": str(ctx.engine_dir),
            "project_dir": str(ctx.project_dir),
            "project_id": ctx.project_id,
            "last_stage": ctx.stages[-1],
            "system_prompt": build_system_prompt(),
            "user_prompt": build_user_prompt(ctx),
            "continuation_prompt": build_continuation_prompt(ctx),
            "model": s.agent_model,
            "max_turns": s.agent_max_turns,
            "llm_budget_usd": s.agent_max_llm_budget_usd,
            "max_continuations": s.agent_max_continuations,
            "allow_web_search": s.agent_allow_web_search,
            "transcript_path": str(transcript) if transcript else None,
        }

    def run_generation(self, ctx: JobContext) -> RuntimeResult:
        s = self.settings
        if not s.anthropic_api_key:
            return RuntimeResult("failed", error_code=ErrorCode.PROVIDER_UNAVAILABLE.value,
                                 detail="ANTHROPIC_API_KEY is not configured on this worker", provider=self.name)

        home = Path(tempfile.gettempdir()) / "agent-home" / ctx.project_id
        home.mkdir(parents=True, exist_ok=True)
        env = build_agent_env(s, ctx.engine_dir, ctx.generation_id, home)

        stderr_file = tempfile.TemporaryFile()
        proc = subprocess.Popen(
            self.runner_cmd or [sys.executable, "-m", "server.runtime.claude_agent_runner"],
            cwd=ctx.engine_dir,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            start_new_session=True,  # own process group => kill the CLI and its children together
        )
        state = {"result": None, "turns": 0}

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") == "heartbeat":
                    state["turns"] = ev.get("turns", state["turns"])
                elif ev.get("event") == "result":
                    state["result"] = ev

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(self._spec(ctx)))
        proc.stdin.close()

        deadline = time.monotonic() + max(s.generation_soft_timeout_seconds - 120, 60)
        abort: Abort | None = None
        timed_out = False
        try:
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                try:
                    abort = ctx.poll()
                except Exception:
                    log.exception("runtime_poll_failed")
                    abort = None
                if abort:
                    break
                time.sleep(ctx.poll_interval_seconds)
        finally:
            if proc.poll() is None:
                self._terminate(proc)
            reader.join(timeout=5)

        stderr_tail = self._stderr_tail(stderr_file)
        stderr_file.close()
        result = state["result"] or {}
        turns = result.get("turns") or state["turns"]
        cost = result.get("cost")

        if abort:
            return RuntimeResult("aborted", abort=abort, llm_cost_usd=cost, turns=turns, provider=self.name)
        if timed_out:
            return RuntimeResult("timeout", error_code=ErrorCode.TIMEOUT.value, detail="wall-clock timeout",
                                 llm_cost_usd=cost, turns=turns, provider=self.name)
        if result.get("done"):
            return RuntimeResult("completed", llm_cost_usd=cost, turns=turns, provider=self.name)

        code = ErrorCode.GENERATION_FAILED.value
        err = str(result.get("error") or "")
        if err.startswith("error_max_budget"):
            code = ErrorCode.BUDGET_EXCEEDED.value
        elif "rate_limit" in err or "overloaded" in err:
            code = ErrorCode.PROVIDER_UNAVAILABLE.value
        detail = f"runner exit={proc.returncode} error={err or 'none'} stderr_tail={stderr_tail!r}"
        return RuntimeResult("failed", error_code=code, detail=detail, llm_cost_usd=cost, turns=turns, provider=self.name)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, AttributeError):
            proc.terminate()
        try:
            proc.wait(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                proc.kill()
            proc.wait(timeout=5)

    @staticmethod
    def _stderr_tail(fh, limit: int = 600) -> str:
        try:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - limit, 0))
            from server.core.logging import redact_text

            return redact_text(fh.read().decode("utf-8", "replace"))
        except Exception:
            return ""
