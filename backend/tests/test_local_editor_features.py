"""Unit + real-ffmpeg checks for the three "clean" add-ons to the deterministic local editor:
speech cleanup / loudness normalisation, face-aware auto-crop, and caption burn-in.

Kept separate from test_worker.py / test_best_takes_e2e.py, which already cover the rest of
local_edit_runner.py end to end; this file focuses on the new pieces themselves."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest

from server.runtime.local_edit_runner import (
    EditError,
    _crop_offset_for_face,
    _escape_filter_path,
    _scaled_frame_size,
    build_caption_cues,
    detect_face_crop_offset,
    normalize,
    write_srt,
)
from server.runtime.local_edit_runtime import LocalEditRuntime
from server.runtime.router_runtime import EditRouterRuntime
from server.services.output_validation import validate_output
from server.worker.tasks import execute_generation
from tests.conftest import FIXTURE_VIDEO

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")

MESSY = Path(__file__).parent / "fixtures" / "messy_takes.mp4"  # real (SAPI) speech, no face - a moving test pattern


# --------------------------------------------------------------------------- pure functions


def test_caption_cues_never_split_a_word_or_reorder_and_respect_the_length_cap():
    words = [
        {"text": "So", "start": 0.0, "end": 0.2}, {"text": "I", "start": 0.25, "end": 0.35},
        {"text": "have", "start": 0.4, "end": 0.55}, {"text": "been", "start": 0.6, "end": 0.75},
        {"text": "using", "start": 0.8, "end": 1.0}, {"text": "this", "start": 1.05, "end": 1.2},
        {"text": "serum", "start": 1.25, "end": 1.6}, {"text": "for", "start": 1.65, "end": 1.8},
        {"text": "two", "start": 1.85, "end": 2.0}, {"text": "weeks", "start": 2.05, "end": 2.4},
        {"text": "and", "start": 3.5, "end": 3.6},  # a 1.1s pause: must always force a new cue
        {"text": "my", "start": 3.65, "end": 3.8}, {"text": "skin", "start": 3.85, "end": 4.1},
        {"text": "looks", "start": 4.15, "end": 4.4}, {"text": "amazing", "start": 4.45, "end": 5.0},
    ]
    cues = build_caption_cues(words)
    assert len(cues) >= 2
    assert " ".join(c["text"] for c in cues) == "So I have been using this serum for two weeks and my skin looks amazing"
    assert cues[0]["start"] == 0.0 and cues[-1]["end"] == 5.0
    for a, b in zip(cues, cues[1:]):
        assert a["end"] <= b["start"]  # contiguous or gapped, never overlapping or reordered
    for c in cues:
        assert len(c["text"]) <= 42
        assert c["text"] == c["text"].strip()
    assert build_caption_cues([]) == []
    assert build_caption_cues([{"text": "  ", "start": 0, "end": 1}]) == []  # blank tokens are dropped, not cued


def test_srt_timestamps_and_file_format():
    from server.runtime.local_edit_runner import _srt_timestamp

    assert _srt_timestamp(0) == "00:00:00,000"
    assert _srt_timestamp(3661.234) == "01:01:01,234"
    assert _srt_timestamp(-1) == "00:00:00,000"  # never a negative timestamp

    cues = [{"start": 0.0, "end": 1.5, "text": "hello there"}, {"start": 2.0, "end": 3.25, "text": "world"}]
    out = Path(__file__).parent / "fixtures" / f"_scratch_{uuid.uuid4().hex}.srt"
    try:
        write_srt(cues, out)
        text = out.read_text(encoding="utf-8")
        assert text.startswith("1\n00:00:00,000 --> 00:00:01,500\nhello there\n\n2\n00:00:02,000 --> 00:00:03,250\nworld")
    finally:
        out.unlink(missing_ok=True)


def test_filter_path_escaping_matches_ffmpegs_own_escaping_rules():
    win_path = "C:" + chr(92) + "clips" + chr(92) + "captions.srt"
    assert _escape_filter_path("/tmp/captions.srt") == "/tmp/captions.srt"
    assert _escape_filter_path(win_path) == "C" + chr(92) + ":/clips/captions.srt"
    with pytest.raises(EditError):
        _escape_filter_path("it's/unsafe.srt")  # a single quote would break out of force_style='...'


def test_crop_math_keeps_the_face_in_frame_and_clamps_at_the_edges():
    # 1920x1080 landscape source -> 720x1280 portrait target: ffmpeg's "increase" scale overflows in width.
    scaled_w, scaled_h = _scaled_frame_size(1920, 1080, 720, 1280)
    assert scaled_h == 1280 and scaled_w == round(1280 * 1920 / 1080) and scaled_w > 720

    cx, cy = _crop_offset_for_face(0.5, 0.3, 1920, 1080, 720, 1280)
    assert 0 <= cx <= scaled_w - 720 and 0 <= cy <= scaled_h - 1280

    # a face pinned at the extreme edge must clamp to the frame boundary, never go negative or overflow
    left_x, _ = _crop_offset_for_face(0.0, 0.5, 1920, 1080, 720, 1280)
    right_x, _ = _crop_offset_for_face(1.0, 0.5, 1920, 1080, 720, 1280)
    assert left_x == 0 and right_x == scaled_w - 720

    # a source that already matches the target aspect ratio has no room to crop either way
    sw2, sh2 = _scaled_frame_size(720, 1280, 720, 1280)
    assert (sw2, sh2) == (720, 1280)
    cx3, cy3 = _crop_offset_for_face(0.5, 0.5, 720, 1280, 720, 1280)
    assert (cx3, cy3) == (0, 0)


def test_face_detection_degrades_gracefully_when_there_is_no_face():
    """The safety-critical path: content with zero faces (or no OpenCV) must never crash or hang the edit."""
    # Deliberately mismatched aspect (16:9 source, 9:16 target) so there is real crop margin to search - this
    # forces an actual OpenCV scan of the (faceless) fixture, not the "aspect already matches" short-circuit below.
    meta = {"width": 1280, "height": 720}
    assert detect_face_crop_offset(MESSY, meta, 720, 1280) is None  # a moving test pattern, no face in it
    assert detect_face_crop_offset(Path("/does/not/exist.mp4"), meta, 720, 1280) is None
    assert detect_face_crop_offset(MESSY, {"width": None, "height": None}, 720, 1280) is None
    # The fixture is actually 360x640 (already 9:16): no crop margin exists, so this returns None without any scan.
    assert detect_face_crop_offset(MESSY, {"width": 360, "height": 640}, 720, 1280) is None


# --------------------------------------------------------------------------- normalize(): real ffmpeg


def _make_gradient_clip(path: Path, w: int, h: int, seconds: int = 2) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size={w}x{h}:rate=10:duration={seconds}", str(path)], check=True)


def _mean_frame(path: Path) -> np.ndarray:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vframes", "1", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.uint8)


def test_normalize_applies_the_requested_crop_offset_not_just_a_centred_one(tmp_path):
    src = tmp_path / "src.mp4"
    _make_gradient_clip(src, 1920, 1080)
    centred = tmp_path / "centred.mp4"
    offset = tmp_path / "offset.mp4"
    normalize(src, centred, 720, 1280, has_audio=False, crop_xy=None)
    normalize(src, offset, 720, 1280, has_audio=False, crop_xy=(400, 0))
    a, b = _mean_frame(centred), _mean_frame(offset)
    assert a.shape == b.shape and a.size > 0
    assert not np.array_equal(a, b)  # cropping a different region of a gradient must change the pixels


def test_normalize_cleans_and_normalises_real_speech_without_breaking_intelligibility(tmp_path):
    """Regression-style: the noise/rumble filter + final loudnorm must not mangle actual words."""
    if importlib.util.find_spec("faster_whisper") is None:
        pytest.skip("faster-whisper not installed")
    from faster_whisper import WhisperModel

    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(MESSY), "-t", "6", "-c", "copy", str(src)], check=True)
    out = tmp_path / "clean.mp4"
    normalize(src, out, 360, 640, has_audio=True, out_len=6.0)

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(out), language="en", vad_filter=True, condition_on_previous_text=False)
    said = " ".join(s.text.strip() for s in segs).lower()
    assert "serum" in said or "code" in said, said  # whichever half of the clip the first 6s landed on, speech survives


# --------------------------------------------------------------------------- end-to-end: captions burn-in


def _run_edit(env, instruction: str):
    from tests.test_best_takes_e2e import _create, _output

    rt = EditRouterRuntime(env["settings"], LocalEditRuntime(env["settings"]), None)
    eid = _create(env["client"], env["asset"]["id"], instruction=instruction)
    status = execute_generation(str(eid), settings=env["settings"], runtime=rt, shutdown_requested=lambda: False)
    assert status == "completed", status
    st = env["client"].get(f"/v1/edits/{eid}").json()
    return st, _output(env, st)


@pytest.mark.skipif(importlib.util.find_spec("faster_whisper") is None, reason="faster-whisper required")
def test_captions_are_really_burned_in_not_just_reported(client, upload_asset, real_engine):
    a = upload_asset(MESSY)
    env = {**real_engine, "client": client, "asset": a}

    plain_st, plain_out = _run_edit(env, "Remove awkward pauses and keep the pacing tight.")
    assert plain_st["warnings"] == [] or "captions_unavailable" not in plain_st["warnings"]

    cap_st, cap_out = _run_edit(env, "Add bold captions.")
    assert "captions_unavailable" not in cap_st["warnings"], cap_st["warnings"]
    validate_output(cap_out, expect_audio=True)

    # Same source, same "keep the pacing tight"-free instruction shape, captioned vs not: sample a handful of
    # frames and confirm at least one of them actually changed where captions are drawn (lower-third).
    def lower_third(path: Path, t: float) -> np.ndarray:
        proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-vframes", "1",
                               "-vf", "crop=iw:ih*0.28:0:ih*0.68", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              capture_output=True, check=True)
        return np.frombuffer(proc.stdout, dtype=np.uint8)

    import subprocess as sp

    def duration(path: Path) -> float:
        out = sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                     capture_output=True, text=True, check=True).stdout
        return float(out.strip())

    dur = min(duration(plain_out), duration(cap_out))
    sample_points = [dur * f for f in (0.15, 0.35, 0.55, 0.75)]
    changed = False
    for t in sample_points:
        try:
            f1, f2 = lower_third(plain_out, t), lower_third(cap_out, t)
        except sp.CalledProcessError:
            continue
        if f1.shape == f2.shape and f1.size and np.abs(f1.astype(int) - f2.astype(int)).mean() > 8:
            changed = True
            break
    assert changed, "no sampled frame in the lower third differed between the captioned and uncaptioned renders"

    # Regression: an earlier Fontsize (scaled from the video's pixel height, like drawtext's) rendered ~4x too
    # large on a portrait video and covered nearly the entire frame in one-word-per-line text (checked visually
    # against a live render). libass' ASS Fontsize is not scaled like that; verify captions stay a caption, not
    # a takeover, by bounding how much of the frame's *height* actually has caption-sized text drawn on it.
    # Scans only the bottom half (where Alignment=2 + a small MarginV places captions) so the fixture's own
    # white-on-black timecode overlay near the top of the frame is never mistaken for caption text.
    w_out, h_out = 720, 1280  # DIMS["9:16"] in local_edit_runner.py - the edit's default aspect ratio
    lower_half_h = h_out // 2
    for t in sample_points:
        proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(cap_out), "-vframes", "1",
                               "-vf", f"crop={w_out}:{lower_half_h}:0:{lower_half_h}",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
        frame = np.frombuffer(proc.stdout, dtype=np.uint8)
        if frame.size != w_out * lower_half_h * 3:
            continue
        rgb = frame.reshape(lower_half_h, w_out, 3)
        near_white_per_row = (rgb.min(axis=2) > 230).sum(axis=1)  # caption text is white-on-black-outline
        text_rows = np.flatnonzero(near_white_per_row > w_out * 0.05)
        if text_rows.size:  # nothing found just means this exact frame had no caption text on screen; try the next
            span = (text_rows.max() - text_rows.min() + 1) / lower_half_h
            assert span < 0.45, f"captions span {span:.0%} of the lower half at t={t:.1f}s - looks oversized"


def test_captions_are_skipped_honestly_when_there_is_no_speech(client, upload_asset, real_engine):
    a = upload_asset(FIXTURE_VIDEO)  # a tone, no speech
    st, _ = _run_edit({**real_engine, "client": client, "asset": a}, "Add captions please.")
    assert st["status"] == "completed"
    assert "captions_unavailable" in st["warnings"]
