"""Edits API: projects, upload flow, edits, revisions, variants - plus the REAL deterministic editor
(OpenMontage video_trimmer + FFmpeg) run end to end on the synthetic fixture. No paid calls."""

from __future__ import annotations

import shutil
import subprocess
import uuid

import pytest

from server.runtime.local_edit_runtime import LocalEditRuntime
from server.runtime.router_runtime import EditRouterRuntime
from server.services.output_validation import validate_output
from server.services.storage import LocalStorage
from server.worker.tasks import execute_generation
from tests.conftest import FIXTURE_VIDEO, TEST_TOKEN

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")

INSTRUCTION = ("Turn this footage into a short vertical UGC ad. Remove awkward pauses, keep the pacing tight, "
               "add clear captions, and create a clean CTA ending.")


def _create(client, asset_ids, **over):
    key = over.pop("key", uuid.uuid4().hex)
    body = {"asset_ids": asset_ids, "instruction": INSTRUCTION, "platform": "tiktok", "aspect_ratio": "9:16", **over}
    return client.post("/v1/edits", json=body, headers={"Idempotency-Key": key})


def _run(env, edit_id, runtime=None):
    settings = env["settings"]
    rt = runtime or EditRouterRuntime(settings, LocalEditRuntime(settings), None)
    return execute_generation(str(edit_id), settings=settings, runtime=rt, shutdown_requested=lambda: False)


def _probe(path):
    import json

    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return float(info["format"]["duration"]), v["width"], v["height"]


def _output_path(env, edit_json):
    key = edit_json["output_url"].split("/media/", 1)[1]
    return LocalStorage(env["settings"].local_storage_path).resolve(key)


# ----------------------------------------------------------------------------- upload flow
def test_upload_flow_local_dev(client, upload_asset, env):
    a = upload_asset()
    assert a["status"] == "uploaded" and a["size_bytes"] == FIXTURE_VIDEO.stat().st_size and a["content_type"] == "video/mp4"
    # completing twice is idempotent
    assert client.post(f"/v1/uploads/{a['id']}/complete").json()["status"] == "uploaded"


def test_upload_rejects_bad_signature_expired_and_oversize(client, env):
    pre = client.post("/v1/uploads/presign", json={"filename": "a.mp4", "content_type": "video/mp4", "purpose": "source_video"}).json()
    url = pre["url"]
    assert client.put(url.split("sig=")[0] + "sig=deadbeef", content=b"x").status_code == 401
    assert client.put(url.replace("exp=", "exp=1&x="), content=b"x").status_code == 401
    # incomplete upload cannot be completed
    assert client.post(f"/v1/uploads/{pre['asset_id']}/complete").status_code == 409
    from server.core import config

    config.get_settings().max_upload_bytes_video = 10
    assert client.put(url, content=b"x" * 50).status_code == 413


def test_upload_forbids_other_users_and_wrong_types(client):
    assert client.post("/v1/uploads/presign", json={"filename": "a.exe", "content_type": "application/octet-stream",
                                                    "purpose": "source_video"}).status_code == 422
    assert client.post(f"/v1/uploads/{uuid.uuid4()}/complete").status_code == 404


# ----------------------------------------------------------------------------- projects & validation
def test_projects_crud_and_isolation(client):
    p = client.post("/v1/projects", json={"name": "UGC Test"})
    assert p.status_code == 201 and p.json()["name"] == "UGC Test" and p.json()["edit_count"] == 0
    assert [x["name"] for x in client.get("/v1/projects").json()["items"]] == ["UGC Test"]
    assert client.get(f"/v1/projects/{p.json()['id']}").json()["assets"] == []
    assert client.get(f"/v1/projects/{uuid.uuid4()}").status_code == 404
    assert client.post("/v1/projects", json={"name": ""}).status_code == 422


def test_create_edit_validation(client, upload_asset, enqueued):
    a = upload_asset()
    good = {"asset_ids": [a["id"]], "instruction": INSTRUCTION}
    assert client.post("/v1/edits", json={**good, "asset_ids": []}).status_code == 422
    assert client.post("/v1/edits", json={**good, "asset_ids": [str(uuid.uuid4())]}).json()["error"]["code"] == "INVALID_REQUEST"
    assert client.post("/v1/edits", json={**good, "instruction": "short"}).status_code == 422
    assert client.post("/v1/edits", json={**good, "platform": "myspace"}).status_code == 422
    assert client.post("/v1/edits", json={**good, "duration_target_seconds": 500}).status_code == 422
    assert client.post("/v1/edits", json={**good, "cmd": "rm -rf /"}).status_code == 422
    r = client.post("/v1/edits", json={**good, "brand_kit_id": str(uuid.uuid4())})
    assert r.status_code == 422 and "not available" in r.json()["error"]["message"]
    assert enqueued == []  # nothing was queued by any rejected request

    pre = client.post("/v1/uploads/presign", json={"filename": "x.mp4", "content_type": "video/mp4", "purpose": "source_video"}).json()
    r = client.post("/v1/edits", json={**good, "asset_ids": [pre["asset_id"]]})
    assert r.status_code == 422 and "finished uploading" in r.json()["error"]["message"]


def test_create_edit_202_idempotent_and_creates_project(client, upload_asset, enqueued):
    a = upload_asset()
    body = {"asset_ids": [a["id"]], "instruction": INSTRUCTION, "platform": "tiktok", "aspect_ratio": "9:16",
            "duration_target_seconds": 25}
    r1 = client.post("/v1/edits", json=body, headers={"Idempotency-Key": "k1"})
    r2 = client.post("/v1/edits", json=body, headers={"Idempotency-Key": "k1"})
    assert r1.status_code == r2.status_code == 202 and r1.json()["id"] == r2.json()["id"]
    assert r2.headers["idempotent-replay"] == "true" and len(enqueued) == 1
    assert r1.json()["status"] == "queued" and r1.json()["poll_url"] == f"/v1/edits/{r1.json()['id']}"
    assert client.post("/v1/edits", json={**body, "duration_target_seconds": 30}, headers={"Idempotency-Key": "k1"}).status_code == 409
    proj = client.get(f"/v1/projects/{r1.json()['project_id']}").json()
    assert proj["edit_count"] == 1 and proj["assets"][0]["id"] == a["id"] and proj["latest_edit"]["id"] == r1.json()["id"]
    st = client.get(f"/v1/edits/{r1.json()['id']}").json()
    assert st["status"] == "queued" and st["kind"] == "edit" and st["version"] == 1 and st["duration_target_seconds"] == 25


def test_edits_are_isolated_per_user_and_not_visible_as_generations(client, upload_asset):
    a = upload_asset()
    eid = _create(client, [a["id"]]).json()["id"]
    assert client.get("/v1/generations").json()["items"] == []
    assert client.get(f"/v1/edits/{uuid.uuid4()}").status_code == 404
    from server.db.models import Generation
    from server.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        s.get(Generation, uuid.UUID(eid)).user_id = "other"
        s.commit()
    assert client.get(f"/v1/edits/{eid}").status_code == 404
    assert client.post(f"/v1/edits/{eid}/cancel").status_code == 404


def test_cancel_edit_and_active_job_cap(client, upload_asset):
    a = upload_asset()
    eid = _create(client, [a["id"]]).json()["id"]
    r = client.post(f"/v1/edits/{eid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    from server.services import edit_service

    for _ in range(edit_service.MAX_ACTIVE_JOBS_PER_USER):
        assert _create(client, [a["id"]]).status_code == 202
    assert _create(client, [a["id"]]).status_code == 429


def test_capabilities_expose_product_features(client, fake_redis, env):
    import json

    from server.services.capabilities import SNAPSHOT_KEY, normalize

    raw = {"registry_ok": True, "capabilities": {}, "composition_runtimes": {"ffmpeg": True}, "whisper": True}
    fake_redis.set(SNAPSHOT_KEY, json.dumps(normalize(raw, env["settings"])))
    caps = client.get("/v1/capabilities").json()
    assert caps["best_takes"] is True and caps["takes_llm"] is False  # transcription present, no editing model configured
    assert caps["editing"] is True and caps["variants"] is True and caps["revisions"] is True
    assert caps["ai_broll"] is False and caps["video_generation"] is False  # no OpenRouter configured
    assert caps["limits"]["uploads"] is True


def test_edit_creation_blocked_only_when_worker_says_editing_unavailable(client, upload_asset, fake_redis):
    import json

    from server.services.capabilities import SNAPSHOT_KEY

    a = upload_asset()
    fake_redis.set(SNAPSHOT_KEY, json.dumps({"status": "degraded", "generation_available": True, "editing": False}))
    assert _create(client, [a["id"]]).status_code == 503


# ----------------------------------------------------------------------------- variants / revisions API guards
def test_revision_requires_completed_edit_and_variant_limits(client, upload_asset):
    a = upload_asset()
    eid = _create(client, [a["id"]]).json()["id"]
    r = client.post(f"/v1/edits/{eid}/instructions", json={"instruction": "Make the opening faster"})
    assert r.status_code == 409  # still queued
    assert client.post(f"/v1/edits/{eid}/variants", json={"count": 6}).status_code == 422
    assert client.post(f"/v1/edits/{eid}/variants", json={"count": 2, "strategy": "nonsense"}).status_code == 422
    assert client.post(f"/v1/edits/{eid}/variants", json={"count": 2, "strategy": "problem"}).status_code == 422
    v = client.post(f"/v1/edits/{eid}/variants", json={"count": 5}, headers={"Idempotency-Key": "vv"})
    assert v.status_code == 202 and len(v.json()["items"]) == 5
    assert len({i["variant"]["strategy"] for i in v.json()["items"]}) == 5
    again = client.post(f"/v1/edits/{eid}/variants", json={"count": 5}, headers={"Idempotency-Key": "vv"})
    assert again.headers["idempotent-replay"] == "true" and {i["id"] for i in again.json()["items"]} == {i["id"] for i in v.json()["items"]}
    assert client.post(f"/v1/edits/{eid}/variants", json={"count": 5}).status_code in (422, 429)  # per-edit / active caps


def test_restore_range_creates_idempotent_revision(client, upload_asset):
    from server.db.models import Generation
    from server.db.session import get_sessionmaker

    asset = upload_asset()
    eid = _create(client, [asset["id"]]).json()["id"]
    with get_sessionmaker()() as session:
        root = session.get(Generation, uuid.UUID(eid))
        root.status = "completed"
        session.commit()

    bad = client.post(f"/v1/edits/{eid}/restore", json={"source": 0, "start": 4.0, "end": 3.0})
    assert bad.status_code == 422
    body = {"source": 0, "start": 4.0, "end": 6.25}
    restored = client.post(f"/v1/edits/{eid}/restore", json=body, headers={"Idempotency-Key": "restore-1"})
    assert restored.status_code == 202
    replay = client.post(f"/v1/edits/{eid}/restore", json=body, headers={"Idempotency-Key": "restore-1"})
    assert replay.headers["idempotent-replay"] == "true" and replay.json()["id"] == restored.json()["id"]
    with get_sessionmaker()() as session:
        revision = session.get(Generation, uuid.UUID(restored.json()["id"]))
        assert revision.kind == "revision" and revision.revision_number == 2
        assert revision.meta["restore_ranges"] == [body]


def test_restored_ranges_are_merged_into_the_source_timeline():
    merged = LocalEditRuntime._merge_ranges(
        [{"source": 0, "start": 2.0, "end": 4.0}, {"source": 0, "start": 8.0, "end": 10.0}],
        [{"source": 0, "start": 3.5, "end": 8.5}],
        1,
    )
    assert merged == [{"source": 0, "start": 2.0, "end": 10.0}]


# ----------------------------------------------------------------------------- REAL deterministic editing
@needs_ffmpeg
def test_first_product_test_upload_edit_poll_output_playback(client, upload_asset, real_engine):
    a = upload_asset()
    r = _create(client, [a["id"]], instruction=INSTRUCTION)
    assert r.status_code == 202
    eid = r.json()["id"]
    assert _run(real_engine, eid) == "completed"

    st = client.get(f"/v1/edits/{eid}").json()
    assert st["status"] == "completed" and st["progress"] == 100 and st["display_stage"] == "Ready"
    assert st["output_url"] and st["thumbnail_url"] and st["error"] is None
    assert st["warnings"] == ["captions_unavailable"]  # honest: no speech-to-text in this environment
    # the "playback" URL is really servable and is a valid 9:16 H.264 file shorter than the source
    media = client.get(st["output_url"], headers={"Authorization": ""})
    assert media.status_code == 200 and media.headers["content-type"].startswith("video/mp4")
    path = _output_path(real_engine, st)
    validate_output(path, expect_audio=True)
    dur, w, h = _probe(path)
    assert (w, h) == (720, 1280)
    assert 7.0 < dur < 9.5, dur  # 8 s source: 1.5 s pause removed + 2 s CTA card + 1.12x pacing
    assert st["duration_seconds"] == pytest.approx(dur, abs=0.1)


@needs_ffmpeg
def test_deterministic_operations_target_duration_and_aspect(client, upload_asset, real_engine):
    a = upload_asset()
    eid = _create(client, [a["id"]], instruction="Cut it down to 5 seconds and remove the first 1 seconds.",
                  aspect_ratio="16:9").json()["id"]
    assert _run(real_engine, eid) == "completed"
    st = client.get(f"/v1/edits/{eid}").json()
    dur, w, h = _probe(_output_path(real_engine, st))
    assert (w, h) == (1280, 720) and dur == pytest.approx(5.0, abs=0.5), dur
    assert st["warnings"] == []


@needs_ffmpeg
def test_revision_preserves_original_and_creates_new_output(client, upload_asset, real_engine):
    a = upload_asset()
    eid = _create(client, [a["id"]], instruction=INSTRUCTION).json()["id"]
    assert _run(real_engine, eid) == "completed"
    original = client.get(f"/v1/edits/{eid}").json()
    orig_path = _output_path(real_engine, original)
    orig_dur = _probe(orig_path)[0]

    rev = client.post(f"/v1/edits/{eid}/instructions", json={"instruction": "Make the opening faster and cut the final video shorter."},
                      headers={"Idempotency-Key": "rev1"})
    assert rev.status_code == 202
    rid = rev.json()["id"]
    assert rid != eid
    assert _run(real_engine, rid) == "completed"

    r = client.get(f"/v1/edits/{rid}").json()
    assert r["kind"] == "revision" and r["parent_id"] == eid and r["version"] == 2 and r["status"] == "completed"
    new_path = _output_path(real_engine, r)
    assert new_path != orig_path and orig_path.is_file() and new_path.is_file()
    assert _probe(new_path)[0] < orig_dur - 0.5  # cumulative instructions: original ops + shorter
    # original untouched and version history lists both, newest last
    again = client.get(f"/v1/edits/{eid}").json()
    assert again["output_url"] == original["output_url"] and again["status"] == "completed"
    assert [v["version"] for v in again["versions"]] == [1, 2]
    assert again["versions"][1]["instruction"].startswith("Make the opening faster")
    # revising the revision keeps numbering going
    rev2 = client.post(f"/v1/edits/{rid}/instructions", json={"instruction": "Add a CTA ending please"}).json()
    assert client.get(f"/v1/edits/{rev2['id']}").json()["version"] == 3


@needs_ffmpeg
def test_three_hook_variants_are_separate_jobs_and_outputs(client, upload_asset, real_engine):
    a = upload_asset()
    eid = _create(client, [a["id"]], instruction="Remove awkward pauses and keep the pacing tight.").json()["id"]
    assert _run(real_engine, eid) == "completed"
    v = client.post(f"/v1/edits/{eid}/variants", json={"count": 3, "strategy": "hooks"})
    assert v.status_code == 202
    items = v.json()["items"]
    assert [i["variant"]["label"] for i in items] == ["Problem Hook", "Curiosity Hook", "Benefit Hook"]
    for i in items:
        assert _run(real_engine, i["id"]) == "completed"
    listed = client.get(f"/v1/edits/{eid}/variants").json()["items"]
    assert len(listed) == 3 and all(i["status"] == "completed" and i["output_url"] and i["thumbnail_url"] for i in listed)
    assert len({i["output_url"] for i in listed}) == 3
    for i in listed:
        validate_output(_output_path(real_engine, i), expect_audio=True)
    assert "ctr" not in str(listed).lower() and "score" not in str(listed).lower()  # no fabricated analytics


@needs_ffmpeg
def test_generative_broll_is_never_triggered_by_local_edits_and_needs_flag(client, upload_asset, real_engine):
    a = upload_asset()
    eid = _create(client, [a["id"]],
                  instruction="Tighten the pacing. Generate a new shot of the serum bottle on a marble vanity.").json()["id"]
    assert _run(real_engine, eid) == "completed"  # generation disabled by default -> edit still delivered
    st = client.get(f"/v1/edits/{eid}").json()
    assert st["warnings"] == ["broll_unavailable"] and st["status"] == "completed"


@needs_ffmpeg
def test_worker_failure_on_corrupt_source_is_sanitized(client, upload_asset, real_engine, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video" * 100)
    a = upload_asset(bad)
    eid = _create(client, [a["id"]]).json()["id"]
    assert _run(real_engine, eid) == "failed"
    st = client.get(f"/v1/edits/{eid}").json()
    assert st["status"] == "failed" and st["error"] == {"code": "GENERATION_FAILED", "message": "We couldn't finish this video."}
    assert "ffprobe" not in str(st) and "/" not in st["error"]["message"]


@needs_ffmpeg
def test_cancel_during_edit_stops_the_runner(client, upload_asset, real_engine):
    from server.db.session import get_sessionmaker
    from server.services import generation_service as svc

    a = upload_asset()
    eid = uuid.UUID(_create(client, [a["id"]]).json()["id"])
    settings = real_engine["settings"]

    class CancellingRuntime(LocalEditRuntime):
        def _render(self, ctx, spec):
            with get_sessionmaker()() as s:
                svc.request_cancel(s, eid, "dev")
            return super()._render(ctx, spec)

    rt = EditRouterRuntime(settings, CancellingRuntime(settings), None)
    assert _run(real_engine, eid, rt) == "cancelled"
    assert client.get(f"/v1/edits/{eid}").json()["status"] == "cancelled"


def test_mock_runtime_edit_flow_for_api_tests(client, upload_asset, env):
    """ORCHESTRATOR_PROVIDER=mock also serves edits (zero cost): queued -> completed with a real URL."""
    a = upload_asset()
    eid = _create(client, [a["id"]]).json()["id"]
    assert execute_generation(eid, settings=env["settings"], shutdown_requested=lambda: False) == "completed"
    st = client.get(f"/v1/edits/{eid}").json()
    assert st["status"] == "completed" and st["output_url"]
    assert "Bearer" not in str(st) and TEST_TOKEN not in str(st)
