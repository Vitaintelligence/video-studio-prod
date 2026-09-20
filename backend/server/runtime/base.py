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


class RuntimeOrchestrator(ABC):
    """Drives one OpenMontage production to completion.

    Implementations must be safe to call from a worker process, honour
    ``ctx.poll`` (cancel/budget/shutdown) at least every few seconds, and never
    raise for expected failures (return a ``RuntimeResult`` instead).
    """

    name: str

    @abstractmethod
    def run_generation(self, ctx: JobContext) -> RuntimeResult: ...
