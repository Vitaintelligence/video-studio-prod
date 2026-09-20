from __future__ import annotations

import uuid

from sqlalchemy import select

from tests.conftest import TEST_TOKEN


def _create(client, body, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/v1/generations", json=body, headers=headers)


# -- health / auth -----------------------------------------------------------

def test_health_is_shallow_and_unauthenticated(client):
    r = client.get("/health", headers={"Authorization": ""})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-request-id"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_ready_checks_db_and_redis(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok" and r.json()["checks"]["redis"] == "ok"


def test_ready_reports_unavailable_when_redis_down(client):
    class Down:
        def ping(self):
            raise ConnectionError("nope")

        def get(self, *_):
            raise ConnectionError("nope")

    client.app_.state.get_redis = lambda: Down()
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["redis"] == "unavailable"


def test_auth_required_for_v1(client):
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}):
        r = client.get("/v1/generations", headers=headers)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"
        assert r.headers["www-authenticate"] == "Bearer"
    assert client.get("/v1/generations", headers={"Authorization": f"Bearer {TEST_TOKEN}"}).status_code == 200


def test_production_requires_strong_token(env, monkeypatch):
    import pytest

    from server.api.main import create_app
    from server.core.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "local_edit")
    monkeypatch.delenv("DEV_API_TOKEN")
    settings = Settings(_env_file=None)  # the worker never holds a client token, so loading settings must succeed
    with pytest.raises(ValueError, match="DEV_API_TOKEN"):
        create_app(settings)
    monkeypatch.setenv("DEV_API_TOKEN", "short")
    with pytest.raises(ValueError, match="DEV_API_TOKEN"):
        create_app(Settings(_env_file=None))


def test_mock_runtime_is_refused_in_production_so_a_test_clip_can_never_be_served_as_a_result(env, monkeypatch):
    """Regression: a worker running the mock runtime returned a 2-second test pattern for a real upload."""
    import pytest

    from server.core.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "mock")
    with pytest.raises(ValueError, match="ORCHESTRATOR_PROVIDER=mock"):
        Settings(_env_file=None)
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "local_edit")
    assert Settings(_env_file=None).orchestrator_provider == "local_edit"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "mock")
    assert Settings(_env_file=None).orchestrator_provider == "mock"  # still fine for local development


def test_docs_disabled_in_production(env, monkeypatch):
    from server.api.main import create_app
    from server.core.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "local_edit")
    s = Settings(_env_file=None)
    assert s.docs_enabled is False
    app = create_app(s)
    assert app.docs_url is None and app.openapi_url is None


def test_no_unrestricted_agent_endpoints(client):
    forbidden = ("agent", "shell", "execute", "run-command", "exec", "command")
    schema = client.app_.openapi()
    for path in schema["paths"]:
        assert not any(word in path.lower() for word in forbidden), path
    assert set(schema["paths"]) == {
        "/health", "/ready", "/v1/capabilities", "/v1/generations", "/v1/generations/{generation_id}",
        "/v1/generations/{generation_id}/cancel", "/v1/uploads/presign", "/v1/uploads/{asset_id}/complete",
        "/v1/projects", "/v1/projects/{project_id}", "/v1/edits", "/v1/edits/{edit_id}", "/v1/edits/{edit_id}/cancel",
        "/v1/edits/{edit_id}/instructions", "/v1/edits/{edit_id}/variants",
    }


# -- creation ----------------------------------------------------------------

def test_create_returns_202_and_enqueues(client, valid_body, enqueued, env):
    r = _create(client, valid_body)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["progress"] == 0 and body["current_stage"] is None
    assert body["poll_url"] == f"/v1/generations/{body['id']}"
    assert enqueued == [uuid.UUID(body["id"])]

    from server.db.models import Generation
    from server.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        gen = s.scalar(select(Generation))
        assert str(gen.id) == body["id"] and gen.pipeline == "app-cinematic"
        assert gen.status == "queued" and gen.duration_seconds_requested == 30 and gen.quality_profile == "standard"


def test_validation_rejections(client, valid_body):
    cases = [
        {"prompt": "short"},
        {"prompt": "x" * 2001},
        {"duration_seconds": 47},
        {"duration_seconds": 3600},
        {"aspect_ratio": "4:3"},
        {"quality": "ultra"},
        {"style": "a; rm -rf /"},
        {"voice_enabled": "maybe"},
        {"max_budget_usd": 500},  # unknown/untrusted client field
        {"shell": "ls"},
    ]
    for override in cases:
        r = _create(client, {**valid_body, **override})
        assert r.status_code == 422, override
        assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_invalid_pipeline_rejected(client, valid_body):
    for name in ("cinematic", "../../etc/passwd", "animated-explainer", "nope"):
        r = _create(client, {**valid_body, "pipeline": name})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "PIPELINE_UNAVAILABLE"


def test_requires_json_content_type(client, valid_body):
    r = client.post("/v1/generations", content="prompt=hello", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_body_size_limit(client, valid_body):
    r = client.post("/v1/generations", json={**valid_body, "prompt": "y" * 200_000})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_idempotency_replay_does_not_double_enqueue(client, valid_body, enqueued):
    a = _create(client, valid_body, key="abc-123")
    b = _create(client, valid_body, key="abc-123")
    assert a.status_code == b.status_code == 202
    assert a.json()["id"] == b.json()["id"]
    assert b.headers["idempotent-replay"] == "true"
    assert len(enqueued) == 1


def test_idempotency_key_with_different_payload_conflicts(client, valid_body):
    _create(client, valid_body, key="same")
    r = _create(client, {**valid_body, "duration_seconds": 60}, key="same")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_bad_idempotency_key_rejected(client, valid_body):
    assert _create(client, valid_body, key="has space").status_code == 422


def test_queue_failure_returns_503_and_marks_failed(client, valid_body):
    from server.services.queue import QueueUnavailable

    def boom(_):
        raise QueueUnavailable("x")

    client.app_.state.enqueue = boom
    r = _create(client, valid_body)
    assert r.status_code == 503 and r.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    listed = client.get("/v1/generations").json()["items"]
    assert listed[0]["status"] == "failed"


def test_refuses_when_worker_reports_unavailable(client, valid_body, fake_redis):
    import json

    from server.services.capabilities import SNAPSHOT_KEY

    fake_redis.set(SNAPSHOT_KEY, json.dumps({"status": "degraded", "generation_available": False, "pipelines": [], "features": {}}))
    r = _create(client, valid_body)
    assert r.status_code == 503 and r.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"


def test_rate_limit_on_creation(client, valid_body):
    limit = client.app_.state.settings.rate_limit_generations_per_minute
    codes = [_create(client, valid_body).status_code for _ in range(limit + 2)]
    assert codes[:limit] == [202] * limit and codes[-1] == 429


# -- status / cancel / list ----------------------------------------------------

def test_status_running_completed_failed(client, valid_body, env):
    from server.db.session import get_sessionmaker
    from server.services import generation_service as svc
    from server.services.storage import get_storage

    gid = uuid.UUID(_create(client, valid_body).json()["id"])
    with get_sessionmaker()() as s:
        svc.mark_starting(s, gid, "projects/x", "mock")
        svc.mark_running(s, gid)
        svc.update_progress(s, gid, 58, "assets")
    r = client.get(f"/v1/generations/{gid}").json()
    assert r["status"] == "running" and r["progress"] == 58
    assert r["current_stage"] == "assets" and r["display_stage"] == "Creating visuals"
    assert r["output_url"] is None and r["error"] is None

    with get_sessionmaker()() as s:
        svc.mark_completed(s, gid, output_key=f"generations/{gid}/final.mp4", thumbnail_key=f"generations/{gid}/thumbnail.jpg",
                           output_url=None, thumbnail_url=None, actual_cost_usd=1.0)
    r = client.get(f"/v1/generations/{gid}").json()
    assert r["status"] == "completed" and r["progress"] == 100
    assert r["display_stage"] == "Ready" and r["output_url"].endswith("/final.mp4") and r["thumbnail_url"]
    assert "actual_cost" not in r and "project_path" not in r
    assert get_storage().backend == "local"

    gid2 = uuid.UUID(_create(client, valid_body).json()["id"])
    with get_sessionmaker()() as s:
        svc.mark_starting(s, gid2, "projects/y", "mock")
        svc.mark_failed(s, gid2, "GENERATION_FAILED", "internal /app/x.py Traceback sk-ant-secret")
    r = client.get(f"/v1/generations/{gid2}").json()
    assert r["status"] == "failed"
    assert r["error"] == {"code": "GENERATION_FAILED", "message": "We couldn't finish this video."}
    assert "Traceback" not in str(r) and "sk-ant" not in str(r)


def test_status_404_and_bad_id(client):
    assert client.get(f"/v1/generations/{uuid.uuid4()}").json()["error"]["code"] == "GENERATION_NOT_FOUND"
    assert client.get("/v1/generations/not-a-uuid").status_code == 422


def test_cancel_queued_is_immediate(client, valid_body):
    gid = _create(client, valid_body).json()["id"]
    r = client.post(f"/v1/generations/{gid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_cancel_running_sets_cancel_requested_and_completed_not_overwritten(client, valid_body):
    from server.db.session import get_sessionmaker
    from server.services import generation_service as svc

    gid = uuid.UUID(_create(client, valid_body).json()["id"])
    with get_sessionmaker()() as s:
        svc.mark_starting(s, gid, "projects/x", "mock")
        svc.mark_running(s, gid)
    r = client.post(f"/v1/generations/{gid}/cancel")
    assert r.json()["status"] == "cancel_requested"

    gid2 = uuid.UUID(_create(client, valid_body).json()["id"])
    with get_sessionmaker()() as s:
        svc.mark_starting(s, gid2, "projects/x", "mock")
        svc.mark_completed(s, gid2, output_key="generations/a/final.mp4", thumbnail_key=None, output_url=None,
                           thumbnail_url=None, actual_cost_usd=0)
    assert client.post(f"/v1/generations/{gid2}/cancel").json()["status"] == "completed"


def test_list_newest_first_pagination_and_filter(client, valid_body):
    ids = [_create(client, {**valid_body, "prompt": f"Video number {i} about the ocean at night"}).json()["id"] for i in range(5)]
    client.post(f"/v1/generations/{ids[0]}/cancel")
    page1 = client.get("/v1/generations", params={"limit": 2}).json()
    assert [i["id"] for i in page1["items"]] == ids[::-1][:2] and page1["next_cursor"]
    page2 = client.get("/v1/generations", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
    assert [i["id"] for i in page2["items"]] == ids[::-1][2:4]
    page3 = client.get("/v1/generations", params={"limit": 2, "cursor": page2["next_cursor"]}).json()
    assert [i["id"] for i in page3["items"]] == [ids[0]] and page3["next_cursor"] is None
    cancelled = client.get("/v1/generations", params={"status": "cancelled"}).json()["items"]
    assert [i["id"] for i in cancelled] == [ids[0]]
    assert client.get("/v1/generations", params={"status": "bogus"}).status_code == 422
    assert client.get("/v1/generations", params={"cursor": "garbage!!"}).status_code == 422


def test_generations_are_scoped_to_user(client, valid_body):
    from server.db.models import Generation
    from server.db.session import get_sessionmaker

    gid = _create(client, valid_body).json()["id"]
    with get_sessionmaker()() as s:
        g = s.get(Generation, uuid.UUID(gid))
        g.user_id = "someone-else"
        s.commit()
    assert client.get(f"/v1/generations/{gid}").status_code == 404
    assert client.get("/v1/generations").json()["items"] == []


def test_capabilities_unknown_then_published(client, fake_redis, env):
    r = client.get("/v1/capabilities").json()
    assert r["status"] == "unknown" and r["generation_available"] is False

    from server.services.capabilities import normalize, SNAPSHOT_KEY
    import json

    raw = {"registry_ok": True, "capabilities": {"video_generation": {"configured": 1, "total": 26},
           "tts": {"configured": 1, "total": 10}, "subtitle": {"configured": 2, "total": 2}},
           "composition_runtimes": {"ffmpeg": True}}
    fake_redis.set(SNAPSHOT_KEY, json.dumps(normalize(raw, env["settings"])))
    r = client.get("/v1/capabilities").json()
    assert r["generation_available"] is True
    assert r["pipelines"] == [{"id": "app-cinematic", "enabled": True}]
    assert r["features"]["text_to_video"] and r["features"]["tts"] and r["features"]["captions"]
    assert "key" not in json.dumps(r).lower().replace("keys", "")


# -- uploads -----------------------------------------------------------------

def test_uploads_local_dev_returns_signed_put_to_api(client):
    r = client.post("/v1/uploads/presign", json={"filename": "a.mov", "content_type": "video/quicktime", "purpose": "reference"})
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "PUT" and "/v1/uploads/" in body["url"] and "sig=" in body["url"] and body["asset_id"]


def test_uploads_unavailable_with_local_storage_in_production(env, monkeypatch, fake_redis):
    from fastapi.testclient import TestClient

    from server.api.main import create_app
    from server.core.config import Settings
    from server.services.ratelimit import RateLimiter
    from tests.conftest import TEST_TOKEN

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "local_edit")
    app = create_app(Settings(_env_file=None))
    limiter = RateLimiter(fake_redis)
    app.state.get_redis = lambda: fake_redis
    app.state.get_rate_limiter = lambda: limiter
    with TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}) as c:
        r = c.post("/v1/uploads/presign", json={"filename": "a.mov", "content_type": "video/quicktime", "purpose": "reference"})
    assert r.status_code == 501 and r.json()["error"]["code"] == "UPLOADS_UNAVAILABLE"


def test_uploads_presign_with_r2_stub(client, env):
    from server.services.storage import R2Storage

    class Stub:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            return f"https://r2.example/{Params['Key']}?X-Amz-Signature=abc&op={op}"

    settings = env["settings"].model_copy(update={"r2_bucket": "b", "r2_public_base_url": None})
    client.app_.state.get_storage = lambda: R2Storage(settings, client=Stub())
    ok = client.post("/v1/uploads/presign", json={"filename": "My Clip (1).mov", "content_type": "video/quicktime", "purpose": "reference", "size_bytes": 1000})
    assert ok.status_code == 200
    body = ok.json()
    assert body["method"] == "PUT" and body["key"].startswith("uploads/dev/") and body["key"].endswith("/My_Clip_1_.mov")
    assert body["headers"] == {"Content-Type": "video/quicktime"}

    bad = [
        {"filename": "a.exe", "content_type": "application/x-msdownload", "purpose": "reference"},
        {"filename": "a.png", "content_type": "image/png", "purpose": "source_video"},
        {"filename": "a.mov", "content_type": "video/quicktime", "purpose": "hack"},
        {"filename": "a.mov", "content_type": "video/quicktime", "purpose": "reference", "size_bytes": 10**11},
    ]
    assert [client.post("/v1/uploads/presign", json=b).status_code for b in bad] == [422, 422, 422, 413]
