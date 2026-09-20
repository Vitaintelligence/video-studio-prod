"""Deterministic UGC editor. Runs in its own process with cwd = the OpenMontage engine dir.

Uses OpenMontage's `video_trimmer` tool (cut / speed / concat) for the timeline operations and
plain FFmpeg for the parts OpenMontage has no dedicated tool for here (silence detection,
reframing/normalising, drawtext hook + CTA). No network, no provider keys, no LLM.

    python -m server.runtime.local_edit_runner < spec.json      (cwd = engine dir)

stdout: JSON lines. Final line: {"event":"result","ok":bool,...}. Never prints paths or secrets.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from server.runtime.mock_runtime import _write_checkpoint

DIMS = {"9:16": (720, 1280), "1:1": (720, 720), "16:9": (1280, 720)}
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
OPENING_SECONDS = 4.0
OPENING_SPEED = 1.3
MIN_KEEP = 0.4
CTA_SECONDS = 2.0


class EditError(Exception):
    pass


def emit(**event) -> None:
    print(json.dumps(event, default=str), flush=True)


def ff(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if proc.returncode != 0:
        raise EditError(f"{Path(cmd[0]).name} failed: {proc.stderr.strip()[-300:]}")
    return proc


def probe(path: Path) -> dict:
    proc = ff(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(proc.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise EditError("source has no video stream")
    return {
        "duration": float(info.get("format", {}).get("duration") or video.get("duration") or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video.get("width"),
        "height": video.get("height"),
    }


def detect_silences(path: Path, noise_db: int = -35, min_len: float = 0.6) -> list[tuple[float, float]]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    )
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", proc.stderr)]
    out = []
    for i, s in enumerate(starts):
        out.append((max(s, 0.0), ends[i] if i < len(ends) else float("inf")))
    return out


def keep_ranges(duration: float, silences: list[tuple[float, float]], pad: float = 0.12) -> list[tuple[float, float]]:
    keeps, cursor = [], 0.0
    for s, e in silences:
        s_keep_end = min(s + pad, duration)
        if s_keep_end - cursor >= MIN_KEEP:
            keeps.append((cursor, s_keep_end))
        cursor = max(cursor, min(e - pad, duration)) if e != float("inf") else duration
    if duration - cursor >= MIN_KEEP:
        keeps.append((cursor, duration))
    return keeps or [(0.0, duration)]


@dataclass
class Seg:
    src: Path
    start: float
    end: float
    speed: float = 1.0
    is_broll: bool = False

    @property
    def out_len(self) -> float:
        return (self.end - self.start) / self.speed


def build_timeline(sources: list[tuple[Path, dict]], broll: list[tuple[Path, dict]], plan: dict, silences: dict) -> list[Seg]:
    segs: list[Seg] = []
    for path, meta in sources:
        ranges = keep_ranges(meta["duration"], silences.get(str(path), [])) if plan["remove_silence"] else [(0.0, meta["duration"])]
        segs += [Seg(path, a, b) for a, b in ranges]

    # drop the first N seconds of the timeline
    skip = float(plan["trim_start_seconds"] or 0)
    while skip > 0 and segs:
        length = segs[0].end - segs[0].start
        if length <= skip + 0.3:
            skip -= length
            segs.pop(0)
        else:
            segs[0].start += skip
            skip = 0
    if not segs:
        raise EditError("nothing left after trimming")

    # generated / supplied B-roll goes after the opening segment
    for i, (path, meta) in enumerate(broll):
        segs.insert(min(1 + i * 2, len(segs)), Seg(path, 0.0, min(meta["duration"], 4.0), is_broll=True))

    # target length: explicit target wins; "shorter" without a target means 80%
    total = sum(s.out_len for s in segs)
    limit = plan["target_duration_seconds"]
    if limit is None and plan["shorten"]:
        limit = max(total * 0.8, 3.0)
    if plan["cta_text"] and limit:
        limit = max(limit - CTA_SECONDS, 2.0)

    if plan["speed_all"] and plan["speed_all"] != 1.0:
        for s in segs:
            s.speed *= plan["speed_all"]
    if plan["speed_opening"]:
        acc = 0.0
        for s in segs:
            if acc >= OPENING_SECONDS:
                break
            s.speed *= OPENING_SPEED
            acc += s.out_len

    if limit:
        acc, kept = 0.0, []
        for s in segs:
            if acc >= limit - 0.05:
                break
            room = limit - acc
            if s.out_len > room:
                s.end = s.start + room * s.speed
            kept.append(s)
            acc += s.out_len
        segs = kept
    return segs


def build_explicit_timeline(sources: list[tuple[Path, dict]], broll: list[tuple[Path, dict]], explicit: list[dict], plan: dict) -> list[Seg]:
    """Segments chosen by best-take selection. Speed / target length still apply, but a target length only ever
    drops WHOLE segments from the end - it never cuts a sentence in half."""
    segs = [Seg(sources[int(t["source"])][0], float(t["start"]), float(t["end"])) for t in explicit]
    if not segs:
        raise EditError("no segments to keep")
    for i, (path, meta) in enumerate(broll):
        segs.insert(min(1 + i * 2, len(segs)), Seg(path, 0.0, min(meta["duration"], 4.0), is_broll=True))
    if plan["speed_all"] and plan["speed_all"] != 1.0:
        for s in segs:
            s.speed *= plan["speed_all"]
    if plan["speed_opening"]:
        acc = 0.0
        for s in segs:
            if acc >= OPENING_SECONDS:
                break
            s.speed *= OPENING_SPEED
            acc += s.out_len
    limit = plan["target_duration_seconds"]
    if limit and plan["cta_text"]:
        limit = max(limit - CTA_SECONDS, 2.0)
    if limit:
        kept, acc = [], 0.0
        for s in segs:
            if kept and acc + s.out_len > limit + 0.5:
                break
            kept.append(s)
            acc += s.out_len
        segs = kept
    return segs


def find_font(workdir: Path) -> str | None:
    for cand in FONT_CANDIDATES:
        if Path(cand).is_file():
            dest = workdir / "font.ttf"
            shutil.copyfile(cand, dest)
            return dest.name
    return None


def normalize(src: Path, dst: Path, w: int, h: int, has_audio: bool, speed: float = 1.0, fade_seconds: float = 0.0,
              out_len: float = 0.0) -> None:
    """Reframe (centre-crop) + fps/pixel-format/audio normalisation so segments concat losslessly.
    `speed` is applied here only for silent sources (video_trimmer's speed op always filters audio)."""
    pre = f"setpts=PTS/{speed:.4f}," if abs(speed - 1.0) > 1e-3 else ""
    vf = f"{pre}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-vf", vf]
    if fade_seconds > 0 and out_len > 4 * fade_seconds:  # tiny fades stop clicks where speech cuts are joined
        cmd += ["-af", f"afade=t=in:d={fade_seconds},afade=t=out:st={out_len - fade_seconds:.3f}:d={fade_seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
    cmd += ["-shortest"] if not has_audio else []
    cmd += [str(dst)]
    ff(cmd)


def make_end_card(dst: Path, text: str, w: int, h: int, workdir: Path, font: str | None) -> None:
    (workdir / "cta.txt").write_text(text, encoding="utf-8")
    size = max(h // 18, 28)
    draw = f"drawtext=textfile=cta.txt:fontfile={font}:fontsize={size}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2" if font else "null"
    ff(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x1b1b2e:s={w}x{h}:r=30:d={CTA_SECONDS}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-vf", f"{draw},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", str(CTA_SECONDS), str(dst)],
       cwd=workdir)


def run(spec: dict) -> dict:
    from tools.video.video_trimmer import VideoTrimmer

    project_dir = Path(spec["project_dir"])
    project_id, pipeline = spec["project_id"], spec["pipeline"]
    plan = spec["plan"]
    w, h = DIMS[spec["aspect_ratio"]]
    work = project_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    (project_dir / "renders").mkdir(exist_ok=True)
    final = project_dir / "renders" / "final.mp4"
    warnings: list[str] = list(spec.get("warnings", []))

    def stage(name: str, status: str) -> None:
        _write_checkpoint(project_dir, project_id, pipeline, name, status, spec.get("spent_usd", 0.0))
        emit(event="stage", stage=name, status=status)

    trimmer = VideoTrimmer()

    def trim(op: dict) -> None:
        res = trimmer.execute(op)
        if not res.success:
            raise EditError(f"video_trimmer {op['operation']} failed")

    # ---- analyze
    stage("analyze", "in_progress")
    sources = [(Path(p), probe(Path(p))) for p in spec["sources"]]
    broll = [(Path(p), probe(Path(p))) for p in spec.get("broll", [])]
    silences = {str(p): detect_silences(p) for p, m in sources if plan["remove_silence"] and m["has_audio"]}
    if plan["remove_silence"] and not silences:
        warnings.append("pause_removal_skipped_no_audio")
    stage("analyze", "completed")

    # ---- plan
    stage("plan", "in_progress")
    explicit = spec.get("timeline")
    if explicit:  # decided upstream (best-take selection): cut exactly these ranges, in this order
        segs = build_explicit_timeline(sources, broll, explicit, plan)
    else:
        segs = build_timeline(sources, broll, plan, silences)
    planned = sum(s.out_len for s in segs) + (CTA_SECONDS if plan["cta_text"] else 0)
    emit(event="plan", segments=len(segs), planned_seconds=round(planned, 2))
    stage("plan", "completed")

    # ---- edit
    stage("edit", "in_progress")
    parts: list[str] = []
    meta_for = {str(p): m for p, m in [*sources, *broll]}
    for i, s in enumerate(segs):
        cut = work / f"s{i:03d}_cut.mp4"
        trim({"operation": "cut", "input_path": str(s.src), "output_path": str(cut),
              "start_seconds": round(s.start, 3), "end_seconds": round(s.end, 3), "codec": "libx264"})
        cur, silent_speed = cut, 1.0
        has_audio = meta_for[str(s.src)]["has_audio"]
        if abs(s.speed - 1.0) > 1e-3:
            if has_audio:
                fast = work / f"s{i:03d}_spd.mp4"
                trim({"operation": "speed", "input_path": str(cur), "output_path": str(fast), "speed_factor": round(s.speed, 3)})
                cur = fast
            else:
                silent_speed = s.speed
        norm = work / f"s{i:03d}_n.mp4"
        normalize(cur, norm, w, h, has_audio=has_audio, speed=silent_speed,
                  fade_seconds=0.015 if explicit else 0.0, out_len=s.out_len)
        parts.append(str(norm))
    font = find_font(work)
    if plan["cta_text"]:
        card = work / "cta.mp4"
        make_end_card(card, plan["cta_text"], w, h, work, font)
        parts.append(str(card))
    joined = work / "joined.mp4"
    trim({"operation": "concat", "segments": [{"input_path": p} for p in parts], "output_path": str(joined)})

    if plan.get("hook_text") and font:
        (work / "hook.txt").write_text(plan["hook_text"], encoding="utf-8")
        size = max(h // 20, 30)
        draw = (f"drawtext=textfile=hook.txt:fontfile={font}:fontsize={size}:fontcolor=white:borderw=4:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*0.12:enable='lt(t,3)'")
        ff(["ffmpeg", "-y", "-v", "error", "-i", "joined.mp4", "-vf", draw, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "21", "-c:a", "copy", "-movflags", "+faststart", str(final)], cwd=work)
    else:
        if plan.get("hook_text") and not font:
            warnings.append("hook_text_skipped_no_font")
        ff(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(final)])
    stage("edit", "completed")

    # ---- captions (needs speech-to-text; not silently faked)
    stage("captions", "in_progress")
    if plan["captions"]:
        warnings.append("captions_unavailable")
    stage("captions", "completed")

    # ---- render
    stage("render", "in_progress")
    out = probe(final)
    if out["duration"] <= 0:
        raise EditError("rendered output has zero duration")
    stage("render", "completed")
    shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "warnings": sorted(set(warnings)), "output_seconds": round(out["duration"], 2), "segments": len(segs)}


def main() -> int:
    spec = json.loads(sys.stdin.read())
    try:
        result = run(spec)
    except EditError as exc:
        print(f"edit error: {exc}", file=sys.stderr)
        emit(event="result", ok=False, error="edit_failed")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"runner exception: {exc!r}", file=sys.stderr)
        emit(event="result", ok=False, error=f"runner_exception:{type(exc).__name__}")
        return 3
    emit(event="result", **result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
