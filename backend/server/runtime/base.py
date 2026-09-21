"""Orchestrator contract. The rest of the backend depends only on this module,
never on a concrete agent SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal


@dataclass(frozen=True)
class Abort:
    """Returned by a poll callback to stop the run."""

    code: str  # an ErrorCode value, or "CANCELLED" / "WORKER_SHUTDOWN"
    reason: str  # internal, logged only


PollFn = Callable[[], "Abort | None"]


@dataclass
class JobContext:
    generation_id: str
    project_id: str
    project_dir: Path  # <engine>/projects/<project_id>
    engine_dir: Path
    pipeline: str
    stages: list[str]
    prompt: str  # untrusted end-user brief
    duration_seconds: int
    aspect_ratio: str
    style: str | None
    voice_enabled: bool
    captions_enabled: bool
    quality: str
    budget_usd: float
    poll: PollFn = field(default=lambda: None)
    poll_interval_seconds: float = 3.0
    # --- edit jobs (kind != "generation"): footage-in, video-out ---
    kind: str = "generation"  # generation | edit | revision | variant
    source_files: list[Path] = field(default_factory=list)
    platform: str | None = None
    cta_text: str | None = None
    variant_label: str | None = None
    hook_text: str | None = None
    duration_explicit: bool = True  # False => duration_seconds is only a default, not a client target
    restore_ranges: list[dict] = field(default_factory=list)


RuntimeStatus = Literal["completed", "aborted", "failed", "timeout"]


@dataclass
class RuntimeResult:
    status: RuntimeStatus
    abort: Abort | None = None
    error_code: str | None = None
    detail: str = ""  # internal diagnostics only (never sent to clients)
    llm_cost_usd: float | None = None
    turns: int | None = None
    provider: str = ""
    warnings: list[str] = field(default_factory=list)  # safe, machine-readable codes only
    insights: dict = field(default_factory=dict)  # safe summary numbers for the client (e.g. retakes removed)
    kept_ranges: list[dict] = field(default_factory=list)  # source-relative ranges used in the rendered cut


class RuntimeOrchestrator(ABC):
    """Drives one OpenMontage production to completion.

    Implementations must be safe to call from a worker process, honour
    ``ctx.poll`` (cancel/budget/shutdown) at least every few seconds, and never
    raise for expected failures (return a ``RuntimeResult`` instead).
    """

    name: str

    def plan_stages(self, ctx: JobContext) -> list[str] | None:
        """Stage list this runtime will report checkpoints for (None = use the pipeline manifest's)."""
        return None

    @abstractmethod
    def run_generation(self, ctx: JobContext) -> RuntimeResult: ...
