"""Deterministic-first edit runtime.

1. (optional, paid, off by default) generate B-roll through OpenRouter on the worker;
2. (talking-head cleanup) best-take selection: transcribe -> group repeated takes -> Qwen (via OpenRouter)
   picks the best take of each line -> keep-ranges with retakes / off-script talk / dead air / fillers removed;
3. hand the timeline work to `local_edit_runner` (OpenMontage video_trimmer + FFmpeg) in a
   separate, secret-free process.

Progress is reported through the same checkpoint files the monitor already understands.
"""

from __future__ import annotations

import importlib.util
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
from server.providers.openrouter import OpenRouterProvider, ProviderError
from server.runtime.base import Abort, JobContext, RuntimeOrchestrator, RuntimeResult
from server.runtime.mock_runtime import _write_checkpoint
from server.services.edit_planner import EditPlan, plan_edit
from server.services.take_llm import decide_takes

log = structlog.get_logger(__name__)

LOCAL_EDIT_STAGES = ["ingest", "broll", "analyze", "plan", "edit", "captions", "render"]
TERM_GRACE_SECONDS = 8
MIN_SPEECH_WORDS = 4


class _Proc:
    """Result of one supervised subprocess."""

    def __init__(self):
        self.event: dict = {}
        self.abort: Abort | None = None
        self.timed_out = False
        self.returncode: int | None = None
        self.stderr = ""


class LocalEditRuntime(RuntimeOrchestrator):
    name = "local_edit"
    runner_cmd: list[str] | None = None  # test seam (render runner only)

    def __init__(self, settings: Settings, provider_factory=None):
        self.settings = settings
        self._provider_factory = provider_factory or (lambda: OpenRouterProvider(settings))

    def plan_stages(self, ctx: JobContext) -> list[str]:
        return list(LOCAL_EDIT_STAGES)

    def build_plan(self, ctx: JobContext) -> EditPlan:
        return plan_edit(ctx.prompt, duration_target_seconds=ctx.duration_seconds if ctx.duration_explicit else None,
                         cta_text=ctx.cta_text, hook_text=ctx.hook_text)

    # ------------------------------------------------------------------------------------
    def run_generation(self, ctx: JobContext) -> RuntimeResult:
        plan = self.build_plan(ctx)
        warnings: list[str] = []
        insights: dict = {}
        pdir, pid, pipe = ctx.project_dir, ctx.project_id, ctx.pipeline
        pdir.mkdir(parents=True, exist_ok=True)

        _write_checkpoint(pdir, pid, pipe, "ingest", "in_progress")
        missing = [p for p in ctx.source_files if not Path(p).is_file()]
        if not ctx.source_files or missing:
            return RuntimeResult("failed", error_code=ErrorCode.GENERATION_FAILED.value, detail="source footage missing",
                                 provider=self.name)
        _write_checkpoint(pdir, pid, pipe, "ingest", "completed")

        # ---- optional generative B-roll (only when the instruction asked for new footage)
        _write_checkpoint(pdir, pid, pipe, "broll", "in_progress")
        broll_files: list[str] = []
        spent = 0.0
        if plan.generative_prompts:
            abort = self._maybe_generate_broll(ctx, plan, broll_files, warnings)
            if isinstance(abort, Abort):
                return RuntimeResult("aborted", abort=abort, provider=self.name)
            spent = abort or 0.0
        _write_checkpoint(pdir, pid, pipe, "broll", "completed", spent)

        # ---- best-take selection (talking-head cleanup)
        timeline: list[dict] | None = None
        _write_checkpoint(pdir, pid, pipe, "analyze", "in_progress", spent)
        if plan.best_takes:
            outcome = self._select_takes(ctx, plan, warnings)
            if isinstance(outcome, Abort):
                return RuntimeResult("aborted", abort=outcome, provider=self.name)
            timeline, insights = outcome
        _write_checkpoint(pdir, pid, pipe, "analyze", "completed", spent)

        # ---- deterministic timeline edit in a separate process
        spec = {
            "project_dir": str(pdir), "project_id": pid, "pipeline": pipe, "aspect_ratio": ctx.aspect_ratio,
            "sources": [str(p) for p in ctx.source_files], "broll": broll_files, "plan": plan.to_dict(),
            "warnings": warnings, "spent_usd": spent, "timeline": timeline,
        }
        result = self._render(ctx, spec)
        result.insights = insights
        return result

    # ------------------------------------------------------------------------------------
    def _select_takes(self, ctx: JobContext, plan: EditPlan, warnings: list[str]):
        """Returns (timeline, insights), or (None, {}) after adding a warning, or an Abort."""
        s = self.settings
        if importlib.util.find_spec("faster_whisper") is None:
            warnings.append("takes_unavailable")
            log.warning("take_selection_skipped", reason="faster_whisper_not_installed")
            return None, {}

        work = ctx.project_dir / "work" / "takes"
        timeline: list[dict] = []
        totals = {"retakes_removed": 0, "off_script_removed": 0, "repeated_lines": 0, "source_seconds": 0.0,
                  "output_seconds": 0.0, "llm_used": False}
        for idx, src in enumerate(ctx.source_files):
            p = self._spawn(ctx, "server.runtime.take_runner", {
                "op": "analyze", "source": str(src), "work_dir": str(work / f"s{idx}"),
                "model": s.transcribe_model, "language": s.transcribe_language,
            }, timeout=max(s.generation_soft_timeout_seconds - 300, 120))
            if p.abort:
                return p.abort
            if not p.event.get("ok") or not p.event.get("word_level"):
                warnings.append("take_analysis_failed")
                log.warning("take_analysis_failed", stderr=p.stderr[-300:])
                return None, {}
            summary = p.event["summary"]
            if summary["utterances"] == 0:
                warnings.append("no_speech_detected")
                return None, {}

            decisions = None
            if s.takes_llm_enabled and s.openrouter_api_key and s.openrouter_editing_model and summary["groups"] > 0:
                try:
                    decisions = decide_takes(self._provider_factory(), s.openrouter_editing_model, p.event["llm_view"], ctx.prompt)
                except ProviderError:
                    decisions = None
                if decisions is None:
                    warnings.append("takes_llm_unavailable")  # engine's own recommendation is used instead
                else:
                    totals["llm_used"] = True

            e = self._spawn(ctx, "server.runtime.take_runner", {
                "op": "edl", "analysis_path": p.event["analysis_path"], "decisions": decisions, "silences": p.event["silences"],
            }, timeout=120)
            if e.abort:
                return e.abort
            if not e.event.get("ok") or not e.event.get("segments"):
                warnings.append("take_analysis_failed")
                return None, {}
            for seg in e.event["segments"]:
                timeline.append({"source": idx, "start": seg["start"], "end": seg["end"]})
            st = e.event["stats"]
            totals["retakes_removed"] += st["dropped_takes"]
            totals["off_script_removed"] += st["off_script_removed"]
            totals["repeated_lines"] += summary["repeated_lines"]
            totals["source_seconds"] += st["source_seconds"]
            totals["output_seconds"] += st["output_seconds"]
        totals["source_seconds"] = round(totals["source_seconds"], 1)
        totals["output_seconds"] = round(totals["output_seconds"], 1)
        return timeline, totals

    # ------------------------------------------------------------------------------------
    def _maybe_generate_broll(self, ctx: JobContext, plan: EditPlan, out: list[str], warnings: list[str]):
        """Returns spend (float) on success/skip, or an Abort."""
        s = self.settings
        if not s.enable_generative_broll or not s.openrouter_api_key:
            warnings.append("broll_unavailable")
            log.info("broll_skipped", reason="generative_broll_disabled_or_no_key")
            return 0.0
        try:
            provider = self._provider_factory()
        except ProviderError:
            warnings.append("broll_unavailable")
            return 0.0
        spent = 0.0
        aborted: list[Abort] = []

        def should_cancel() -> bool:
            a = ctx.poll()
            if a:
                aborted.append(a)
            return bool(a)

        for i, prompt in enumerate(plan.generative_prompts[: s.max_broll_clips_per_edit]):
            dest = ctx.project_dir / "assets" / "broll" / f"broll_{i}.mp4"
            try:
                cost, _plan = provider.generate_video_clip(
                    prompt, dest, profile="ugc_broll", duration=4, aspect_ratio=ctx.aspect_ratio, should_cancel=should_cancel)
            except ProviderError as exc:
                if exc.code == "CANCELLED" and aborted:
                    return aborted[0]
                log.warning("broll_generation_failed", code=exc.code)
                warnings.append("broll_failed")
                continue
            spent += cost or 0.0
            out.append(str(dest))
            _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, "broll", "in_progress", spent)
            if spent >= ctx.budget_usd:
                warnings.append("broll_budget_reached")
                break
        return spent

    # ------------------------------------------------------------------------------------
    def _render(self, ctx: JobContext, spec: dict) -> RuntimeResult:
        p = self._spawn(ctx, "server.runtime.local_edit_runner", spec,
                        timeout=max(self.settings.generation_soft_timeout_seconds - 120, 60), cmd_override=self.runner_cmd)
        if p.abort:
            return RuntimeResult("aborted", abort=p.abort, provider=self.name)
        if p.timed_out:
            return RuntimeResult("timeout", error_code=ErrorCode.TIMEOUT.value, detail="edit timed out", provider=self.name)
        if p.event.get("ok"):
            return RuntimeResult("completed", provider=self.name, warnings=list(p.event.get("warnings", [])), turns=0,
                                 llm_cost_usd=0.0)
        return RuntimeResult("failed", error_code=ErrorCode.GENERATION_FAILED.value,
                             detail=f"runner exit={p.returncode} error={p.event.get('error')} stderr={p.stderr!r}",
                             provider=self.name)

    def _spawn(self, ctx: JobContext, module: str, spec: dict, *, timeout: float, cmd_override: list[str] | None = None) -> _Proc:
        """Run a secret-free helper process in the engine dir, supervised (cancel / timeout / process-group kill)."""
        home = Path(tempfile.gettempdir()) / "edit-home" / ctx.project_id
        home.mkdir(parents=True, exist_ok=True)
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SYSTEMROOT", "HF_HOME",
                                          "HUGGINGFACE_HUB_CACHE", "OMP_NUM_THREADS") if k in os.environ}
        # The helper gets a scratch HOME, so the speech model cache must be pointed at explicitly
        # (in Docker HF_HOME is set at build time; locally fall back to the parent's default cache).
        env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
        env.update({"HOME": str(home), "USERPROFILE": str(home), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                    "PYTHONPATH": os.pathsep.join([str(ctx.engine_dir), str(ctx.engine_dir.parent)])})
        stderr_file = tempfile.TemporaryFile()
        proc = subprocess.Popen(
            cmd_override or [sys.executable, "-m", module],
            cwd=ctx.engine_dir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file, text=True,
            start_new_session=True,
        )
        out = _Proc()

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") == "result":
                    out.event = ev

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(spec))
        proc.stdin.close()

        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    out.timed_out = True
                    break
                try:
                    out.abort = ctx.poll()
                except Exception:  # noqa: BLE001
                    log.exception("runtime_poll_failed")
                    out.abort = None
                if out.abort:
                    break
                time.sleep(min(ctx.poll_interval_seconds, 0.5))
        finally:
            if proc.poll() is None:
                self._terminate(proc)
            reader.join(timeout=5)
        out.returncode = proc.returncode
        out.stderr = self._stderr_tail(stderr_file)
        stderr_file.close()
        return out

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
    def _stderr_tail(fh, limit: int = 500) -> str:
        try:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - limit, 0))
            from server.core.logging import redact_text

            return redact_text(fh.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return ""
