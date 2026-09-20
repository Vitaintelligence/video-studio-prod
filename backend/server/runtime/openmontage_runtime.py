"""OpenMontage-specific plumbing shared by runtime adapters: job workspace,
final-output discovery, completion detection, and the agent process environment.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from server.core.config import Settings

_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class WorkspaceError(Exception):
    pass


def safe_project_id(generation_id: object) -> str:
    """Project id is the generation UUID: never derived from user text."""
    pid = str(generation_id).lower()
    if not _PROJECT_ID_RE.match(pid):
        raise WorkspaceError("invalid project id")
    return pid


def projects_root(engine_dir: Path) -> Path:
    return Path(engine_dir) / "projects"


def prepare_workspace(engine_dir: Path, project_id: str) -> Path:
    root = projects_root(engine_dir)
    root.mkdir(parents=True, exist_ok=True)
    project_dir = (root / project_id).resolve()
    if project_dir.parent != root.resolve():
        raise WorkspaceError("workspace escapes projects root")
    project_dir.mkdir(exist_ok=True)
    return project_dir


def remove_workspace(project_dir: Path) -> None:
    shutil.rmtree(project_dir, ignore_errors=True)


def purge_old_workspaces(engine_dir: Path, retention_hours: int, keep: set[str] | None = None) -> int:
    """Delete job workspaces older than the retention window. Returns count."""
    root = projects_root(engine_dir)
    if not root.is_dir():
        return 0
    cutoff = time.time() - retention_hours * 3600
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() or not _PROJECT_ID_RE.match(child.name) or (keep and child.name in keep):
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def compose_completed(project_dir: Path, last_stage: str) -> bool:
    cp = _load_json(project_dir / f"checkpoint_{last_stage}.json")
    return bool(cp and cp.get("status") == "completed")


def find_final_output(project_dir: Path, last_stage: str = "compose") -> Path | None:
    """Locate the deliverable: canonical path first, then the render_report."""
    project_dir = project_dir.resolve()
    canonical = project_dir / "renders" / "final.mp4"
    if canonical.is_file():
        return canonical

    cp = _load_json(project_dir / f"checkpoint_{last_stage}.json") or {}
    report = (cp.get("artifacts") or {}).get("render_report") or {}
    for out in report.get("outputs", []) if isinstance(report, dict) else []:
        raw = out.get("path") if isinstance(out, dict) else None
        if not raw:
            continue
        p = Path(raw)
        p = (p if p.is_absolute() else project_dir / p).resolve()
        if (project_dir in p.parents) and p.suffix.lower() == ".mp4" and p.is_file():
            return p

    renders = project_dir / "renders"
    if renders.is_dir():
        candidates = sorted(renders.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return None


# Variables the agent process always needs (and nothing else from the worker env).
_BASE_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "VIRTUAL_ENV")


def provider_env_names(engine_dir: Path) -> list[str]:
    """Provider credential/config variable names, read from the engine's own
    .env.example so we forward exactly what OpenMontage documents (no invented names)."""
    names: list[str] = []
    example = Path(engine_dir) / ".env.example"
    try:
        text = example.read_text(encoding="utf-8")
    except OSError:
        return names
    for line in text.splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=", line.strip())
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


# Documented aliases accepted by OpenMontage tools but absent from .env.example.
_EXTRA_PROVIDER_ENV = ("ATLASCLOUD_API_KEY", "ATLAS_CLOUD_API_KEY", "ATLAS_API_KEY", "GEMINI_API_KEY")


def build_agent_env(settings: Settings, engine_dir: Path, generation_id: str, home: Path) -> dict[str, str]:
    """Minimal, explicit environment for the agent process.

    Deliberately excludes DATABASE_URL, REDIS_URL, R2_*, DEV_API_TOKEN and every
    other worker-only secret. Provider keys are included because OpenMontage tools
    read them from the environment.
    """
    env: dict[str, str] = {k: os.environ[k] for k in _BASE_ENV if k in os.environ}
    for name in [*provider_env_names(engine_dir), *_EXTRA_PROVIDER_ENV]:
        if name in os.environ and os.environ[name] != "":
            env[name] = os.environ[name]
    if settings.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key.get_secret_value()
    env.update(
        {
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join([str(engine_dir), str(engine_dir.parent)]),
            "OPENMONTAGE_PROJECTS_DIR": str(projects_root(engine_dir)),
            "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "0",  # =1 needs bubblewrap (user namespaces), unavailable on Railway; we scrub via an env allowlist instead
            "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK": "1",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "GENERATION_ID": generation_id,
        }
    )
    return env
