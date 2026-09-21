"""END-TO-END on real speech: upload a messy multi-take clip through the API, let the worker transcribe it
(real faster-whisper), select takes, cut it with FFmpeg / OpenMontage video_trimmer, and then RE-TRANSCRIBE the
output to prove which takes actually survived. Free: no provider calls (the Qwen step uses a scripted stub)."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr

from server.runtime.local_edit_runtime import LocalEditRuntime
from server.runtime.router_runtime import EditRouterRuntime
from server.services.output_validation import validate_output
from server.services.storage import LocalStorage
from server.worker.tasks import execute_generation
from tests.conftest import FIXTURE_VIDEO
from tests.test_edit_planner import APP_CLEAN_INSTRUCTION

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or importlib.util.find_spec("faster_whisper") is None,
    reason="ffmpeg + faster-whisper required",
)

MESSY = Path(__file__).parent / "fixtures" / "messy_takes.mp4"
BRIEF = "Say it five times and post the best one: remove all retakes, mistakes and dead air."


def _create(client, asset_id, instruction=BRIEF, **kw):
    body = {"asset_ids": [asset_id], "instruction": instruction, "aspect_ratio": "9:16", **kw}
    r = client.post("/v1/edits", json=body, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _run(env, eid, settings=None, provider=None):
    settings = settings or env["settings"]
    rt = EditRouterRuntime(settings, LocalEditRuntime(settings, provider_factory=(lambda: provider) if provider else None), None)
    return execute_generation(str(eid), settings=settings, runtime=rt, shutdown_requested=lambda: False)


def _output(env, st):
    return LocalStorage(env["settings"].local_storage_path).resolve(st["output_url"].split("/media/", 1)[1])


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


_MODEL = None


def _speech(path: Path) -> str:
    """What is actually spoken in the produced video (independent of the edit engine's own analysis)."""
    global _MODEL
    from faster_whisper import WhisperModel

    _MODEL = _MODEL or WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = _MODEL.transcribe(str(path), language="en", vad_filter=True, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs).lower()


class StubProvider:
    """Stands in for OpenRouter/Qwen: returns scripted editorial decisions."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat(self, messages, **kw):
        self.calls.append((messages, kw))
        return self.reply


@pytest.mark.parametrize("instruction", [BRIEF, APP_CLEAN_INSTRUCTION], ids=["typed-brief", "app-clean-button"])
def test_messy_37s_clip_becomes_a_clean_cut_with_only_the_best_takes(client, upload_asset, real_engine, instruction):
    a = upload_asset(MESSY)
    eid = _create(client, a["id"], instruction=instruction)
    assert _run(real_engine, eid) == "completed"

    st = client.get(f"/v1/edits/{eid}").json()
    assert st["status"] == "completed" and st["error"] is None
    path = _output(real_engine, st)
    validate_output(path, expect_audio=True)
    dur = _duration(path)
    assert 5.0 < dur < 13.0, dur  # 37 s of mess -> the two good lines with breathing room

    ins = st["insights"]
    assert ins["retakes_removed"] == 4 and ins["off_script_removed"] == 1 and ins["repeated_lines"] == 2
    assert ins["source_seconds"] > 37 and ins["output_seconds"] < 10 and ins["llm_used"] is False
    assert st["warnings"] == []

    said = _speech(path)
    assert "amazing" in said and "code glow" in said and "today" in said  # the complete serum take + the clean code take
    for mess in ("wait", "start again", "um", "twin", "sorry"):
        assert not re.search(r"\b" + re.escape(mess) + r"\b", said), (mess, said)  # whole words: "serum" is not "um"
    assert said.count("serum") == 1  # said once, not five times


def test_qwen_cannot_swap_in_worse_takes_or_invent_ids(client, upload_asset, real_engine):
    """The model's picks are a tie-break among comparable takes: a clearly worse take, a deleted line and an invented
    id are all ignored, and the engine's own choice stands."""
    provider = StubProvider(
        '```json\n{"decisions":[{"group":"g1","keep":"u3","reason":"test"},{"group":"g2","keep":null},'
        '{"group":"g9","keep":"u404"}],"drop_meta":["u2","u999"]}\n```')
    settings = real_engine["settings"].model_copy(update={
        "openrouter_api_key": SecretStr("test-key"), "openrouter_editing_model": "qwen/qwen3.7-flash"})
    a = upload_asset(MESSY)
    eid = _create(client, a["id"])
    assert _run(real_engine, eid, settings, provider) == "completed"

    st = client.get(f"/v1/edits/{eid}").json()
    assert st["status"] == "completed" and st["insights"]["llm_used"] is True
    said = _speech(_output(real_engine, st))
    assert "amazing" in said and "today" in said  # the engine's clean takes stayed
    assert not re.search(r"\bum\b", said) and said.count("serum") == 1, said  # the flubbed take was not let back in
    assert len(provider.calls) == 1
    messages, kw = provider.calls[0]
    assert kw["model"] == "qwen/qwen3.7-flash" and "test-key" not in json.dumps(messages)
    assert "messy_takes" not in json.dumps(messages) and "/" not in messages[1]["content"].split("DATA>>>")[0].split("<<<DATA")[1].replace("\\/", "")


def test_unusable_model_output_falls_back_to_the_engines_own_choice(client, upload_asset, real_engine):
    provider = StubProvider("I'm sorry, I can't help with that request.")
    settings = real_engine["settings"].model_copy(update={
        "openrouter_api_key": SecretStr("test-key"), "openrouter_editing_model": "qwen/qwen3.7-flash"})
    a = upload_asset(MESSY)
    eid = _create(client, a["id"])
    assert _run(real_engine, eid, settings, provider) == "completed"
    st = client.get(f"/v1/edits/{eid}").json()
    assert "takes_llm_unavailable" in st["warnings"] and st["insights"]["llm_used"] is False
    said = _speech(_output(real_engine, st))
    assert "amazing" in said and "today" in said


def test_footage_without_speech_still_delivers_an_edit_with_an_honest_warning(client, upload_asset, real_engine):
    a = upload_asset(FIXTURE_VIDEO)  # a tone, no speech
    eid = _create(client, a["id"], instruction="Clean up the retakes and mistakes please.")
    assert _run(real_engine, eid) == "completed"
    st = client.get(f"/v1/edits/{eid}").json()
    assert st["status"] == "completed" and st["output_url"]
    assert "no_speech_detected" in st["warnings"] or st["insights"].get("retakes_removed", 0) == 0


def test_without_the_take_keywords_nothing_is_transcribed(client, upload_asset, real_engine):
    """Pause removal alone stays fast and free: no Whisper, no model, no insights."""
    a = upload_asset(MESSY)
    eid = _create(client, a["id"], instruction="Remove awkward pauses and keep the pacing tight.")
    assert _run(real_engine, eid) == "completed"
    st = client.get(f"/v1/edits/{eid}").json()
    assert st["insights"] == {} and st["status"] == "completed"
    assert _duration(_output(real_engine, st)) > 15  # all the speech is still there
