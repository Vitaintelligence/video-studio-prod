"""Runtime selection by ORCHESTRATOR_PROVIDER. Add new providers here only."""

from __future__ import annotations

from server.core.config import Settings
from server.runtime.base import RuntimeOrchestrator


def build_runtime(settings: Settings) -> RuntimeOrchestrator:
    provider = settings.orchestrator_provider
    if provider == "claude_agent_sdk":
        from server.runtime.claude_agent_runtime import ClaudeAgentRuntime

        return ClaudeAgentRuntime(settings)
    if provider == "mock":
        from server.runtime.mock_runtime import MockRuntime

        return MockRuntime()
    raise ValueError(f"Unknown ORCHESTRATOR_PROVIDER {provider!r}")
