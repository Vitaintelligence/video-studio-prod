"""Final-output validation with ffprobe (and thumbnail extraction with ffmpeg).

The agent's own compose stage runs OpenMontage's checks; this is the server's
independent gate before anything is uploaded or marked completed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class OutputInvalid(Exception):
    """Raised with an internal (never client-facing) reason."""


@dataclass
class ProbeResult:
    duration_seconds: float
    size_bytes: int
    video_codec: str
    width: int | None
    height: int | None
    has_audio: bool
    audio_codec: str | None


def run_ffprobe(path: Path, timeout: int = 60) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise OutputInvalid("ffprobe not installed")
    proc = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise OutputInvalid(f"ffprobe failed: {proc.stderr.strip()[:200]}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise OutputInvalid("ffprobe returned invalid JSON") from exc


def validate_output(path: Path, *, expect_audio: bool) -> ProbeResult:
    if not path.is_file():
        raise OutputInvalid("output file missing")
    size = path.stat().st_size
    if size <= 0:
        raise OutputInvalid("output file is empty")

    info = run_ffprobe(path)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("codec_name")), None)
    if video is None:
        raise OutputInvalid("no readable video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    try:
        duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise OutputInvalid("output duration is zero")
    if expect_audio and audio is None:
        raise OutputInvalid("expected an audio track but none was found")

    return ProbeResult(
        duration_seconds=duration,
        size_bytes=size,
        video_codec=str(video["codec_name"]),
        width=video.get("width"),
        height=video.get("height"),
        has_audio=audio is not None,
        audio_codec=audio.get("codec_name") if audio else None,
    )


def extract_thumbnail(video: Path, dest: Path, at_seconds: float) -> bool:
    """Best-effort JPEG frame grab. Returns False instead of raising."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-y", "-v", "error", "-ss", f"{max(at_seconds, 0):.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale='min(720,iw)':-2", "-q:v", "3", str(dest)],
            capture_output=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0
