"""Zero-cost test runtime: no LLM, no providers.

Writes the same checkpoint files OpenMontage would (so CheckpointMonitor,
progress mapping, upload and validation are exercised end to end) and renders a
short real MP4 with ffmpeg's built-in test sources. Enabled only with
``ORCHESTRATOR_PROVIDER=mock``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from server.core.errors import ErrorCode
from server.runtime.base import JobContext, RuntimeOrchestrator, RuntimeResult


def _write_checkpoint(project_dir: Path, project_id: str, pipeline: str, stage: str, status: str, spent: float = 0.0) -> None:
    cp = {
        "version": "1.0",
        "project_id": project_id,
        "pipeline_type": pipeline,
        "stage": stage,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "human_approval_required": False,
        "human_approved": False,
        "artifacts": {},
        "cost_snapshot": {"total_spent_usd": spent, "total_reserved_usd": 0.0, "budget_remaining_usd": 3.0 - spent},
    }
    tmp = project_dir / f"checkpoint_{stage}.json.tmp"
    tmp.write_text(json.dumps(cp), encoding="utf-8")
    os.replace(tmp, project_dir / f"checkpoint_{stage}.json")


class MockRuntime(RuntimeOrchestrator):
    name = "mock"

    def __init__(self, stage_delay_seconds: float | None = None):
        self.stage_delay = (
            stage_delay_seconds
            if stage_delay_seconds is not None
            else float(os.environ.get("MOCK_RUNTIME_STAGE_DELAY", "0.2"))
        )

    def _sleep(self, ctx: JobContext, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            abort = ctx.poll()
            if abort:
                return abort
            time.sleep(min(0.1, max(end - time.monotonic(), 0)))
        return ctx.poll()

    def run_generation(self, ctx: JobContext) -> RuntimeResult:
        ctx.project_dir.mkdir(parents=True, exist_ok=True)
        (ctx.project_dir / "renders").mkdir(exist_ok=True)
        if "MOCK_FAIL" in ctx.prompt:
            return RuntimeResult("failed", error_code=ErrorCode.GENERATION_FAILED.value,
                                 detail="mock failure requested (/secret/path/x.py sk-ant-abc123456789)", provider=self.name)

        for i, stage in enumerate(ctx.stages):
            _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, stage, "in_progress", 0.01 * i)
            abort = self._sleep(ctx, self.stage_delay)
            if abort:
                return RuntimeResult("aborted", abort=abort, provider=self.name)
            _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, stage, "completed", 0.01 * (i + 1))

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return RuntimeResult("failed", error_code=ErrorCode.GENERATION_FAILED.value, detail="ffmpeg missing", provider=self.name)
        w, h = {"9:16": (360, 640), "1:1": (480, 480), "16:9": (640, 360)}[ctx.aspect_ratio]
        cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=24:duration=2"]
        if ctx.voice_enabled:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(ctx.project_dir / "renders" / "final.mp4")]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0:
            return RuntimeResult("failed", error_code=ErrorCode.GENERATION_FAILED.value,
                                 detail=proc.stderr.decode()[-300:], provider=self.name)
        return RuntimeResult("completed", llm_cost_usd=0.0, turns=0, provider=self.name)
