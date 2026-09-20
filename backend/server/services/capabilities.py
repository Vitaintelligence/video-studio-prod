"""Capabilities: worker computes them from the real OpenMontage registry and
publishes a sanitized snapshot to Redis; the API (which holds no provider keys
and cannot detect providers itself) serves that snapshot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

import structlog

from server.core.config import Settings, get_settings
from server.services.pipelines import enabled_pipelines

log = structlog.get_logger(__name__)

SNAPSHOT_KEY = "openmontage:capabilities:v1"
SNAPSHOT_TTL_SECONDS = 900


def run_probe(settings: Settings, timeout: int = 240) -> dict[str, Any]:
    """Execute the registry probe in the engine dir; returns the raw sanitized dict."""
    env = os.environ.copy()
    backend_dir = str(settings.openmontage_dir.parent)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(settings.openmontage_dir), backend_dir, env.get("PYTHONPATH", "")]))
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "server.runtime.preflight_probe"],
            cwd=settings.openmontage_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.warning("preflight_probe_timeout", timeout_seconds=timeout)
        return {"registry_ok": False, "error": "probe_timeout"}
    except OSError as exc:
        log.warning("preflight_probe_unrunnable", error=type(exc).__name__)
        return {"registry_ok": False, "error": "probe_unrunnable"}
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        data = json.loads(line)
    except ValueError:
        data = {"registry_ok": False, "error": "probe_output_invalid"}
    if proc.returncode != 0:
        log.warning("preflight_probe_failed", rc=proc.returncode, stderr=proc.stderr[-300:])
    return data


def _configured(caps: dict, name: str) -> bool:
    return caps.get(name, {}).get("configured", 0) > 0


def normalize(raw: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Client-facing capability document derived from a probe result."""
    caps = raw.get("capabilities", {})
    runtimes = raw.get("composition_runtimes", {})
    features = {
        "text_to_video": _configured(caps, "video_generation"),
        "image_generation": _configured(caps, "image_generation"),
        "tts": _configured(caps, "tts"),
        "captions": _configured(caps, "subtitle"),
        "music": _configured(caps, "music_generation") or _configured(caps, "music_search"),
        "stock_video": _configured(caps, "clip_acquisition"),
    }
    pipelines_enabled = enabled_pipelines()
    composition_ok = bool(runtimes.get("ffmpeg"))
    visuals = features["text_to_video"] or features["image_generation"]
    agent_ok = settings.orchestrator_provider == "mock" or bool(settings.anthropic_api_key)
    available = bool(raw.get("registry_ok")) and composition_ok and visuals and bool(pipelines_enabled) and agent_ok
    return {
        "status": "ok" if raw.get("registry_ok") else "degraded",
        "generation_available": available,
        "pipelines": [{"id": pid, "enabled": pid in pipelines_enabled and available} for pid in pipelines_enabled],
        "features": features,
        "generated_at": int(time.time()),
    }


def publish_snapshot(redis_client, settings: Settings) -> dict[str, Any]:
    raw = run_probe(settings)
    doc = normalize(raw, settings)
    if not raw.get("registry_ok") and read_snapshot(redis_client) is not None:
        # A transient probe failure (slow npx, timeout) must not overwrite a good snapshot.
        log.warning("capabilities_probe_failed_keeping_previous_snapshot")
        return doc
    redis_client.set(SNAPSHOT_KEY, json.dumps(doc), ex=SNAPSHOT_TTL_SECONDS)
    return doc


def read_snapshot(redis_client) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(SNAPSHOT_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def capabilities_document(redis_client, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    snap = read_snapshot(redis_client)
    base_limits = {
        "durations_seconds": [15, 30, 45, 60],
        "aspect_ratios": ["9:16", "1:1", "16:9"],
        "quality": ["standard", "cinematic"],
        "max_prompt_chars": 2000,
        "uploads": settings.storage_backend == "r2",
    }
    if snap is None:
        # No worker has reported yet (or the snapshot expired): say so honestly.
        return {
            "status": "unknown",
            "generation_available": False,
            "pipelines": [{"id": pid, "enabled": False} for pid in enabled_pipelines()],
            "features": {k: False for k in ("text_to_video", "image_generation", "tts", "captions", "music", "stock_video")},
            "limits": base_limits,
        }
    snap.pop("generated_at", None)
    snap["limits"] = base_limits
    return snap
