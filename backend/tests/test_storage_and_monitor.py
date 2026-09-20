from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.core.errors import sanitize_text
from server.core.logging import redact_text
from server.services.checkpoint_monitor import PIPELINE_CEILING, CheckpointMonitor
from server.services.storage import LocalStorage, R2Storage, UnsafeKeyError, output_key, sanitize_filename, validate_key

STAGES = ["research", "proposal", "script", "scene_plan", "assets", "edit", "compose"]


# -- storage -----------------------------------------------------------------

def test_local_storage_roundtrip(tmp_path):
    st = LocalStorage(tmp_path / "root")
    src = tmp_path / "v.mp4"
    src.write_bytes(b"video")
    st.put_file("generations/abc/final.mp4", src, "video/mp4")
    assert st.exists("generations/abc/final.mp4")
    assert (tmp_path / "root" / "generations" / "abc" / "final.mp4").read_bytes() == b"video"
    assert st.url_for("generations/abc/final.mp4") == "/media/generations/abc/final.mp4"
    st.delete("generations/abc/final.mp4")
    assert not st.exists("generations/abc/final.mp4")


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a/../../b", "a//b", "a/b/", "", "a\\b", "a/./b", "x" * 500, "a b/c", "ünï/c"])
def test_unsafe_keys_rejected(key, tmp_path):
    with pytest.raises(UnsafeKeyError):
        validate_key(key)
    with pytest.raises(UnsafeKeyError):
        LocalStorage(tmp_path).resolve(key)


def test_filename_sanitization_and_output_key():
    assert sanitize_filename("../../evil name.mov") == "evil_name.mov"
    assert sanitize_filename("C:\\Users\\x\\clip.mp4") == "clip.mp4"
    assert sanitize_filename("...") == "file"
    assert output_key("11111111-1111-1111-1111-111111111111", "final.mp4") == "generations/11111111-1111-1111-1111-111111111111/final.mp4"


def test_r2_public_and_signed_urls(env):
    class Stub:
        def __init__(self):
            self.uploaded = []

        def upload_file(self, path, bucket, key, ExtraArgs):
            self.uploaded.append((bucket, key, ExtraArgs))

        def generate_presigned_url(self, op, Params, ExpiresIn):
            return f"https://signed.example/{Params['Key']}?sig=1&ttl={ExpiresIn}"

    stub = Stub()
    s = env["settings"].model_copy(update={"r2_bucket": "bkt", "r2_public_base_url": "https://cdn.example.com/"})
    pub = R2Storage(s, client=stub)
    assert pub.url_for("generations/a/final.mp4") == "https://cdn.example.com/generations/a/final.mp4"
    pub.put_file("generations/a/final.mp4", Path(__file__), "video/mp4")
    assert stub.uploaded == [("bkt", "generations/a/final.mp4", {"ContentType": "video/mp4"})]

    signed = R2Storage(s.model_copy(update={"r2_public_base_url": None, "signed_url_ttl_seconds": 60}), client=stub)
    assert signed.url_for("generations/a/final.mp4").startswith("https://signed.example/generations/a/final.mp4")


# -- checkpoints -------------------------------------------------------------

def _cp(d: Path, stage: str, status: str, **extra):
    (d / f"checkpoint_{stage}.json").write_text(json.dumps({"stage": stage, "status": status, **extra}), encoding="utf-8")


def test_progress_is_zero_ish_without_checkpoints(tmp_path):
    snap = CheckpointMonitor(tmp_path, STAGES).snapshot()
    assert snap.current_stage == "research" and snap.progress == 5 and not snap.completed_stages


def test_progress_maps_completed_stages(tmp_path):
    for st in STAGES[:3]:
        _cp(tmp_path, st, "completed")
    snap = CheckpointMonitor(tmp_path, STAGES).snapshot()
    assert snap.current_stage == "scene_plan" and snap.completed_stages == STAGES[:3]
    assert snap.progress == round(5 + 85 * 3 / 7)


def test_partial_progress_is_used_within_a_stage(tmp_path):
    for st in STAGES[:4]:
        _cp(tmp_path, st, "completed")
    base = CheckpointMonitor(tmp_path, STAGES).snapshot().progress
    _cp(tmp_path, "assets", "in_progress", metadata={"partial_progress": {"completed_scene_ids": ["s1", "s2"], "pending_scene_ids": ["s3", "s4"]}})
    mid = CheckpointMonitor(tmp_path, STAGES).snapshot()
    assert mid.current_stage == "assets" and mid.progress > base
    assert mid.progress == round(5 + 85 * (4 + 0.5) / 7)


def test_completion_never_reaches_100_from_pipeline_alone(tmp_path):
    for st in STAGES:
        _cp(tmp_path, st, "completed")
    snap = CheckpointMonitor(tmp_path, STAGES).snapshot()
    assert snap.progress == PIPELINE_CEILING and snap.compose_completed and snap.current_stage == "compose"


def test_monitor_extracts_cost_gate_and_failure_and_ignores_garbage(tmp_path):
    _cp(tmp_path, "research", "completed", cost_snapshot={"total_spent_usd": 0.4})
    _cp(tmp_path, "proposal", "awaiting_human", cost_snapshot={"total_spent_usd": 1.25})
    (tmp_path / "checkpoint_script.json").write_text("{not json", encoding="utf-8")
    snap = CheckpointMonitor(tmp_path, STAGES).snapshot()
    assert snap.total_spent_usd == 1.25 and snap.awaiting_human is True
    _cp(tmp_path, "script", "failed", error="boom")
    assert CheckpointMonitor(tmp_path, STAGES).snapshot().failed_error == "boom"


def test_real_manifest_stage_order(env):
    from server.services.pipelines import stage_order

    assert stage_order("app-cinematic") == STAGES


# -- sanitization ------------------------------------------------------------

def test_sanitize_text_strips_paths_and_secrets():
    raw = "failed at /app/openmontage/tools/x.py with key=abc123 and Bearer sk-ant-api03-SECRETSECRET in C:\\Users\\me\\a.py"
    out = sanitize_text(raw)
    assert "/app/" not in out and "abc123" not in out and "SECRETSECRET" not in out and "C:\\Users" not in out


def test_log_redaction_processor():
    from server.core.logging import _redact

    event = {"event": "x", "authorization": "Bearer abc", "nested": {"api_key": "k", "note": "hi sk-ant-abcdefgh12345"},
             "url": "https://u:pw@host/x?X-Amz-Signature=deadbeef"}
    out = _redact(event)
    assert out["authorization"] == "[redacted]" and out["nested"]["api_key"] == "[redacted]"
    assert "sk-ant" not in out["nested"]["note"] and "pw@" not in out["url"] and "deadbeef" not in out["url"]
    assert "[redacted]" in redact_text("Bearer abc.def")
