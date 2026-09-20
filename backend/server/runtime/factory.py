"""Runtime selection by ORCHESTRATOR_PROVIDER. Add new providers here only."""

from __future__ import annotations

from server.core.config import Settings
from server.runtime.base import RuntimeOrchestrator


def build_runtime(settings: Settings) -> RuntimeOrchestrator:
    provider = settings.orchestrator_provider
    if provider == "claude_agent_sdk":
        from server.runtime.claude_agent_runtime import ClaudeAgentRuntime
        from server.runtime.local_edit_runtime import LocalEditRuntime
        from server.runtime.router_runtime import EditRouterRuntime

        agent = ClaudeAgentRuntime(settings)
        if not settings.local_edit_first:
            return agent
        return EditRouterRuntime(settings, LocalEditRuntime(settings), agent)
    if provider == "local_edit":
        # Deterministic editing only (no LLM control plane): edits work, text-to-video reports unavailable.
        from server.runtime.local_edit_runtime import LocalEditRuntime
        from server.runtime.router_runtime import EditRouterRuntime

        return EditRouterRuntime(settings, LocalEditRuntime(settings), None)
    if provider == "mock":
        from server.runtime.mock_runtime import MockRuntime

        return MockRuntime()
    raise ValueError(f"Unknown ORCHESTRATOR_PROVIDER {provider!r}")
