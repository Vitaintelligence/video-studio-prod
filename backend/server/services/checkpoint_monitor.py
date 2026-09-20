"""Translate OpenMontage checkpoints into mobile-safe progress.

OpenMontage writes ``projects/<id>/checkpoint_<stage>.json`` (atomic replace).
We read those files, never the agent's messages, and derive:

* the current stage (first stage that is not completed),
* an overall progress percentage (completed stages + partial progress),
* the latest cost snapshot,
* whether the pipeline stalled on a human gate (a contract violation for the
  autonomous app pipeline).

Progress is deliberately conservative: the pipeline accounts for at most
``PIPELINE_CEILING`` percent; validation and upload own the rest, so the bar
never reads 100 before the video is actually deliverable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PIPELINE_FLOOR = 5
PIPELINE_CEILING = 90


@dataclass
class ProgressSnapshot:
    current_stage: str | None
    progress: int
    completed_stages: list[str] = field(default_factory=list)
    stage_status: str | None = None
    total_spent_usd: float | None = None
    awaiting_human: bool = False
    failed_error: str | None = None
    compose_completed: bool = False


def _read_checkpoint(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # partially written / vanishing: ignore this tick
    return data if isinstance(data, dict) else None


def _partial_fraction(checkpoint: dict[str, Any]) -> float:
    """Best-effort 0..1 within-stage progress from ``metadata.partial_progress``.

    OpenMontage documents ``completed_scene_ids`` plus a draft of the artifact.
    If a total is derivable we use it; otherwise each completed unit nudges
    progress with diminishing returns so we never claim the stage is done
    before its own checkpoint says so.
    """
    meta = checkpoint.get("metadata")
    partial = meta.get("partial_progress") if isinstance(meta, dict) else None
    if not isinstance(partial, dict):
        return 0.0
    done = partial.get("completed_scene_ids")
    done_n = len(done) if isinstance(done, list) else 0
    total = None
    for key in ("total_scenes", "total", "scene_count"):
        if isinstance(partial.get(key), int) and partial[key] > 0:
            total = partial[key]
            break
    if total is None:
        for key in ("pending_scene_ids", "remaining_scene_ids"):
            if isinstance(partial.get(key), list):
                total = done_n + len(partial[key])
                break
    if total:
        return max(0.0, min(0.95, done_n / total))
    if done_n:
        return min(0.9, 1 - 1 / (1 + done_n * 0.35))
    return 0.05  # in_progress but nothing measurable yet


class CheckpointMonitor:
    def __init__(self, project_dir: Path, stages: list[str]):
        if not stages:
            raise ValueError("pipeline has no stages")
        self.project_dir = Path(project_dir)
        self.stages = list(stages)

    def snapshot(self) -> ProgressSnapshot:
        checkpoints: dict[str, dict[str, Any]] = {}
        for stage in self.stages:
            cp = _read_checkpoint(self.project_dir / f"checkpoint_{stage}.json")
            if cp and cp.get("stage", stage) == stage:
                checkpoints[stage] = cp

        completed = [s for s in self.stages if checkpoints.get(s, {}).get("status") == "completed"]
        current: str | None = None
        current_status: str | None = None
        partial = 0.0
        for stage in self.stages:
            cp = checkpoints.get(stage)
            if cp and cp.get("status") == "completed":
                continue
            current = stage
            current_status = cp.get("status") if cp else "pending"
            if cp and cp.get("status") == "in_progress":
                partial = _partial_fraction(cp)
            break

        n = len(self.stages)
        fraction = (len(completed) + partial) / n
        progress = round(PIPELINE_FLOOR + (PIPELINE_CEILING - PIPELINE_FLOOR) * fraction)
        progress = max(0, min(PIPELINE_CEILING, progress))

        spent: float | None = None
        for cp in checkpoints.values():
            snap = cp.get("cost_snapshot")
            if isinstance(snap, dict) and isinstance(snap.get("total_spent_usd"), (int, float)):
                spent = max(spent or 0.0, float(snap["total_spent_usd"]))

        awaiting = any(cp.get("status") == "awaiting_human" for cp in checkpoints.values())
        failed = next(
            (str(cp.get("error") or "stage failed") for cp in checkpoints.values() if cp.get("status") == "failed"),
            None,
        )
        return ProgressSnapshot(
            current_stage=current if current else "compose",
            progress=progress if current else PIPELINE_CEILING,
            completed_stages=completed,
            stage_status=current_status,
            total_spent_usd=spent,
            awaiting_human=awaiting,
            failed_error=failed,
            compose_completed=self.stages[-1] in completed,
        )
