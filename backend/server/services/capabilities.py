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
        # Whether OUR pipeline can actually burn in captions (needs ffmpeg's libass), not just whether an
        # unused upstream OpenMontage tool happens to be installed.
        "captions": bool(raw.get("libass")),
        "music": _configured(caps, "music_generation") or _configured(caps, "music_search"),
        "stock_video": _configured(caps, "clip_acquisition"),
    }
    pipelines_enabled = enabled_pipelines()
    composition_ok = bool(runtimes.get("ffmpeg"))
    visuals = features["text_to_video"] or features["image_generation"]
    # Mock renders locally and intentionally needs no paid visual or agent provider.
    # Real prompt-to-video generation requires both a visual provider and the Claude agent runtime.
    runtime_ready = settings.orchestrator_provider == "mock" or (
        settings.orchestrator_provider == "claude_agent_sdk" and visuals and bool(settings.anthropic_api_key)
    )
    available = bool(raw.get("registry_ok")) and composition_ok and bool(pipelines_enabled) and runtime_ready
    # Product capabilities. Deterministic editing needs only FFmpeg: it works with no provider keys at all.
    editing = composition_ok and bool(pipelines_enabled)
    has_video_model = bool(settings.openrouter_video_model or settings.openrouter_video_profiles)
    video_generation = bool(settings.openrouter_api_key) and has_video_model
    ai_broll = editing and settings.enable_generative_broll and video_generation
    return {
        "status": "ok" if raw.get("registry_ok") else "degraded",
        "generation_available": available,
        "editing": editing,
        "ai_broll": ai_broll,
        "video_generation": video_generation,
        "variants": editing,
        "revisions": editing,
        "best_takes": editing and bool(raw.get("whisper")),  # transcription available on the worker
        "takes_llm": bool(settings.openrouter_api_key and settings.openrouter_editing_model and settings.takes_llm_enabled),
        "audio_cleanup": editing,  # noise/rumble reduction + loudness normalisation: pure FFmpeg, always on
        "smart_crop": editing and bool(raw.get("opencv")),  # face-aware reframing; falls back to a centre crop
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
        "uploads": settings.uses_object_storage or not settings.is_production,
    }
    if snap is None:
        # No worker has reported yet (or the snapshot expired): say so honestly.
        return {
            "status": "unknown",
            "generation_available": False,
            "editing": False,
            "ai_broll": False,
            "video_generation": False,
            "variants": False,
            "revisions": False,
            "best_takes": False,
            "takes_llm": False,
            "audio_cleanup": False,
            "smart_crop": False,
            "pipelines": [{"id": pid, "enabled": False} for pid in enabled_pipelines()],
            "features": {k: False for k in ("text_to_video", "image_generation", "tts", "captions", "music", "stock_video")},
            "limits": base_limits,
        }
    snap.pop("generated_at", None)
    snap["limits"] = base_limits
    return snap
