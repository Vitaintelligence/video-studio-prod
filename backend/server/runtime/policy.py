"""Tool-use policy for the headless agent (defence in depth).

Real isolation comes from the OS (non-root user, read-only source tree, scrubbed
child env). This module adds a best-effort application-level guard, applied via
a PreToolUse hook, so a prompt-injected brief cannot easily read other jobs,
edit engine/server code, or dump credentials. It is a denylist for Bash and an
allowlist for file paths; it is NOT a sandbox and the docs say so.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""


ALLOW = Decision(True)


def _deny(reason: str) -> Decision:
    return Decision(False, reason)


READ_TOOLS = {"Read", "Glob", "Grep"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PASSTHROUGH_TOOLS = {"TodoWrite"}

_SECRET_FILE_RE = re.compile(r"(^|/)(\.env[^/]*|.*\.pem|.*\.key|id_rsa[^/]*|credentials[^/]*|\.netrc|\.aws|\.ssh)$", re.I)

_BASH_DENY: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|[\s;&|(`])(env|printenv|export\s+-p|declare\s+-x|compgen\s+-e)(\s|$|;|\|)"), "environment inspection"),
    (re.compile(r"/proc/|/sys/|/etc/(passwd|shadow|hosts)"), "system introspection"),
    (re.compile(r"os\.environ|getenv|environ\b|subprocess\.[a-z_]*environ"), "environment access"),
    (re.compile(r"(^|[\s;&|(`])\.?env(\.[\w-]+)?(\s|$)|\.env\b"), "env file access"),
    (re.compile(r"\$\{?[A-Za-z_]*(KEY|SECRET|TOKEN|PASSWORD|DATABASE_URL|REDIS_URL|CREDENTIAL)"), "secret variable reference"),
    (re.compile(r"(^|[\s;&|(`])(curl|wget|nc|ncat|socat|ssh|scp|sftp|ftp|telnet|rsync)(\s|$)"), "raw network tooling"),
    (re.compile(r"(^|[\s;&|(`])(sudo|su|chown|chmod|mount|kill|pkill|killall|crontab|nohup|systemctl|docker)(\s|$)"), "privileged/process control"),
    (re.compile(r"(^|[\s;&|(`])(pip3?|python3?\s+-m\s+pip|npm|pnpm|yarn|apt(-get)?)\s+(install|add|i|uninstall|remove)\b"), "package installation"),
    (re.compile(r"(^|[\s;&|(`])git(\s|$)"), "git"),
    (re.compile(r"(^|[\s;&|(`])rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|\.\.|\*)"), "destructive delete"),
    (re.compile(r"\bbase64\b.*(-d|--decode)|(^|[\s;&|(`])(eval|exec)\s"), "obfuscated execution"),
    (re.compile(r"(^|[\s'\"=])(\.\./|~/|/root|/home/|/workspace/(?!storage)|/app/server|/app/scripts|/app/migrations)"), "path outside job scope"),
    (re.compile(r"python3?\s+-m\s+(server|celery|alembic|uvicorn)|celery\s|alembic\s|uvicorn\s"), "server control"),
]
_PROJECTS_REF = re.compile(r"projects/([A-Za-z0-9_.\-]+)")


class ToolPolicy:
    def __init__(self, engine_dir: Path, project_id: str, allow_web_search: bool = True):
        self.engine_dir = Path(os.path.realpath(engine_dir))
        self.project_id = project_id
        self.projects_root = self.engine_dir / "projects"
        self.project_dir = self.projects_root / project_id
        self.allow_web_search = allow_web_search

    # -- paths ---------------------------------------------------------
    def _resolve(self, raw: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = self.engine_dir / p
        return Path(os.path.realpath(p))

    def _within(self, p: Path, root: Path) -> bool:
        return p == root or root in p.parents

    def check_read_path(self, raw: str | None) -> Decision:
        if not raw:
            return ALLOW  # Glob/Grep default to cwd (the engine dir)
        p = self._resolve(raw)
        if not self._within(p, self.engine_dir):
            return _deny("reading outside the engine workspace is not allowed")
        if _SECRET_FILE_RE.search(p.as_posix()):
            return _deny("credential files are not readable")
        if self._within(p, self.projects_root) and not self._within(p, self.project_dir) and p != self.projects_root:
            return _deny("other jobs' workspaces are not accessible")
        if p == self.projects_root:
            return _deny("listing the projects root is not allowed")
        return ALLOW

    def check_write_path(self, raw: str | None) -> Decision:
        if not raw:
            return _deny("missing path")
        p = self._resolve(raw)
        if not self._within(p, self.project_dir):
            return _deny("writes are limited to this job's project directory")
        if _SECRET_FILE_RE.search(p.as_posix()):
            return _deny("refusing to write credential-like files")
        return ALLOW

    # -- bash ----------------------------------------------------------
    def check_bash(self, command: str | None) -> Decision:
        if not command or not command.strip():
            return _deny("empty command")
        if len(command) > 20000:
            return _deny("command too long")
        for pattern, why in _BASH_DENY:
            if pattern.search(command):
                return _deny(f"blocked: {why}")
        for m in _PROJECTS_REF.finditer(command):
            if m.group(1) != self.project_id:
                return _deny("other jobs' workspaces are not accessible")
        return ALLOW

    # -- entrypoint ----------------------------------------------------
    def check(self, tool_name: str, tool_input: dict) -> Decision:
        if tool_name in PASSTHROUGH_TOOLS:
            return ALLOW
        if tool_name in READ_TOOLS:
            for key in ("file_path", "path"):
                d = self.check_read_path(tool_input.get(key))
                if not d.allow:
                    return d
            return ALLOW
        if tool_name in WRITE_TOOLS:
            return self.check_write_path(tool_input.get("file_path") or tool_input.get("notebook_path"))
        if tool_name == "Bash":
            return self.check_bash(tool_input.get("command"))
        if tool_name == "WebSearch":
            return ALLOW if self.allow_web_search else _deny("web search disabled")
        return _deny(f"tool {tool_name!r} is not permitted in this runtime")
