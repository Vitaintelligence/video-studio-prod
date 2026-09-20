"""Subprocess entrypoint that drives OpenMontage with the Claude Agent SDK.

Runs in its OWN process with an explicit, minimal environment (see
``build_agent_env``) so the agent never inherits database/Redis/R2 secrets from
the worker. Job parameters arrive as JSON on stdin; progress/result events go to
stdout as JSON lines. Agent text and reasoning are never emitted.

    python -m server.runtime.claude_agent_runner < job.json   (cwd = engine dir)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path


def emit(**event) -> None:
    print(json.dumps(event, default=str), flush=True)


BUILTIN_TOOLS = ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "Bash", "TodoWrite"]
DISALLOWED = ["WebFetch", "Task", "Agent", "NotebookEdit", "SlashCommand", "Skill", "ExitPlanMode", "KillShell", "BashOutput"]


def _transcript(path: Path | None, tool: str, tool_input: dict, allowed: bool, reason: str = "") -> None:
    if path is None:
        return
    from server.core.logging import redact_text

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "t": round(time.time(), 1),
            "tool": tool,
            "allowed": allowed,
            "reason": reason,
            "input": redact_text(json.dumps(tool_input, default=str)[:400]),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


async def run(spec: dict) -> int:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        HookMatcher,
        ResultMessage,
        ToolUseBlock,
        query,
    )

    from server.runtime.openmontage_runtime import compose_completed, find_final_output
    from server.runtime.policy import ToolPolicy
    from server.runtime.prompt_builder import SYSTEM_PROMPT

    engine_dir = Path(spec["engine_dir"])
    project_dir = Path(spec["project_dir"])
    project_id = spec["project_id"]
    last_stage = spec["last_stage"]
    transcript = Path(spec["transcript_path"]) if spec.get("transcript_path") else None
    policy = ToolPolicy(engine_dir, project_id, allow_web_search=spec["allow_web_search"])

    async def guard(input_data, tool_use_id, context):
        tool = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {}) or {}
        decision = policy.check(tool, tool_input)
        _transcript(transcript, tool, tool_input, decision.allow, decision.reason)
        if decision.allow:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.reason,
            }
        }

    tools = list(BUILTIN_TOOLS) + (["WebSearch"] if spec["allow_web_search"] else [])
    base = ClaudeAgentOptions(
        system_prompt=spec["system_prompt"] or SYSTEM_PROMPT,
        cwd=str(engine_dir),
        model=spec["model"],
        max_turns=spec["max_turns"],
        tools=tools,
        allowed_tools=tools,
        disallowed_tools=DISALLOWED + ([] if spec["allow_web_search"] else ["WebSearch"]),
        permission_mode="dontAsk",
        setting_sources=[],  # ignore any CLAUDE.md / .claude settings in the engine tree
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard])]},
    )

    session_id: str | None = None
    llm_cost = 0.0
    turns = 0
    prompts = [spec["user_prompt"]] + [spec["continuation_prompt"]] * spec["max_continuations"]
    last_error: str | None = None

    for attempt, prompt in enumerate(prompts):
        remaining = max(spec["llm_budget_usd"] - llm_cost, 0.0)
        if remaining <= 0.01:
            last_error = "llm_budget_exhausted"
            break
        options = replace(base, max_budget_usd=remaining, resume=session_id)
        result_seen = False
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turns += 1
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        emit(event="tool", name=block.name)
                emit(event="heartbeat", turns=turns)
            elif isinstance(message, ResultMessage):
                result_seen = True
                session_id = message.session_id or session_id
                llm_cost += float(message.total_cost_usd or 0.0)
                last_error = message.subtype if message.is_error else None
                emit(event="attempt_result", attempt=attempt, subtype=message.subtype,
                     is_error=bool(message.is_error), cost=llm_cost, turns=turns)
        if not result_seen:
            last_error = "no_result"
            break
        if compose_completed(project_dir, last_stage) and find_final_output(project_dir, last_stage):
            last_error = None
            break
        if last_error and last_error.startswith("error_max_budget"):
            break

    done = compose_completed(project_dir, last_stage) and find_final_output(project_dir, last_stage) is not None
    emit(event="result", done=done, error=last_error, cost=llm_cost, turns=turns, session_id=session_id)
    return 0 if done else 2


def main() -> int:
    spec = json.loads(sys.stdin.read())
    try:
        return asyncio.run(run(spec))
    except Exception as exc:  # report class only on stdout; parent logs stderr tail
        emit(event="result", done=False, error=f"runner_exception:{type(exc).__name__}", cost=0.0, turns=0)
        print(f"runner exception: {exc!r}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
