"""Routes a job to the cheapest capable runtime.

* text-to-video generation (no source footage)      -> agent runtime
* footage edit whose plan is fully deterministic      -> LocalEditRuntime (FFmpeg / OpenMontage tools)
* footage edit needing creative judgement             -> agent runtime *if configured*, else the
  deterministic subset with an explicit warning code (never a silent downgrade)

Generative video is never chosen here: it is an explicit, capped, flag-gated step inside
LocalEditRuntime, used only when the instruction asks for newly generated footage.
"""

from __future__ import annotations

from dataclasses import replace

from server.core.config import Settings
from server.runtime.base import JobContext, RuntimeOrchestrator, RuntimeResult
from server.runtime.local_edit_runtime import LocalEditRuntime

EDIT_KINDS = ("edit", "revision", "variant")


class EditRouterRuntime(RuntimeOrchestrator):
    name = "edit_router"

    def __init__(self, settings: Settings, local: LocalEditRuntime, agent: RuntimeOrchestrator | None):
        self.settings = settings
        self.local = local
        self.agent = agent

    def _agent_usable(self) -> bool:
        return self.agent is not None and bool(self.settings.anthropic_api_key)

    def _choose(self, ctx: JobContext) -> tuple[RuntimeOrchestrator | None, list[str]]:
        if ctx.kind not in EDIT_KINDS or not ctx.source_files:
            return self.agent, []
        plan = self.local.build_plan(ctx)
        if plan.needs_agent and self._agent_usable():
            return self.agent, []
        notes = ["agent_unavailable"] if plan.needs_agent else []
        return self.local, notes

    def plan_stages(self, ctx: JobContext) -> list[str] | None:
        rt, _ = self._choose(ctx)
        return rt.plan_stages(ctx) if rt is not None else None

    def run_generation(self, ctx: JobContext) -> RuntimeResult:
        rt, notes = self._choose(ctx)
        if rt is None:
            return RuntimeResult("failed", error_code="PROVIDER_UNAVAILABLE", detail="no runtime available for this job",
                                 provider=self.name)
        result = rt.run_generation(replace(ctx))
        result.warnings = sorted(set([*result.warnings, *notes]))
        return result
