"""Shared fixtures. Every test runs against an isolated SQLite DB, fakeredis,
local storage in a tmp dir, and the mock runtime. Nothing here can reach a paid
provider or the network."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import fakeredis
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEST_TOKEN = "test-token-0123456789abcdef0123456789"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    (engine / "pipeline_defs").mkdir(parents=True)
    shutil.copy(BACKEND / "openmontage" / "pipeline_defs" / "app-cinematic.yaml", engine / "pipeline_defs")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEV_API_TOKEN", TEST_TOKEN)
    # TEST_DATABASE_URL lets the whole suite run against a real Postgres (tables are dropped/recreated).
    external_db = os.environ.get("TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", external_db or f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399/0")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("OPENMONTAGE_DIR", str(engine))
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "agent-logs"))
    monkeypatch.setenv("CANCEL_POLL_SECONDS", "0.05")

    from server.core import config
    from server.db import session as dbsession
    from server.services import ratelimit, storage

    def reset():
        config.reset_settings_cache()
        dbsession.reset_engine_cache()
        storage.reset_storage_cache()
        ratelimit.get_rate_limiter.cache_clear()
        ratelimit.get_redis.cache_clear()

    reset()
    from server.db.base import Base
    from server.db import models  # noqa: F401

    if external_db:
        Base.metadata.drop_all(dbsession.get_engine())
    Base.metadata.create_all(dbsession.get_engine())
    yield {"tmp": tmp_path, "engine": engine, "settings": config.get_settings()}
    reset()


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def enqueued():
    return []


@pytest.fixture()
def client(env, fake_redis, enqueued):
    from fastapi.testclient import TestClient

    from server.api.main import create_app
    from server.services.ratelimit import RateLimiter

    app = create_app(env["settings"])
    limiter = RateLimiter(fake_redis)
    app.state.get_redis = lambda: fake_redis
    app.state.get_rate_limiter = lambda: limiter
    app.state.enqueue = lambda gid: enqueued.append(gid) or "task"
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
        c.app_ = app
        yield c


VALID_BODY = {
    "prompt": "Create a cinematic short about a futuristic city waking up at sunrise.",
    "duration_seconds": 30,
    "aspect_ratio": "9:16",
    "style": "cinematic",
    "pipeline": "app-cinematic",
    "voice_enabled": True,
    "captions_enabled": True,
    "quality": "standard",
}


@pytest.fixture()
def valid_body():
    return dict(VALID_BODY)


FIXTURE_VIDEO = Path(__file__).parent / "fixtures" / "test_ugc.mp4"


@pytest.fixture()
def real_engine(env, monkeypatch):
    """Point the worker at the real OpenMontage engine dir (needed by the deterministic editor).
    Job workspaces created by the test are removed afterwards."""
    from server.core import config

    real = BACKEND / "openmontage"
    monkeypatch.setenv("OPENMONTAGE_DIR", str(real))
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "local_edit")
    config.reset_settings_cache()
    before = set((real / "projects").glob("*")) if (real / "projects").exists() else set()
    yield {**env, "engine": real, "settings": config.get_settings()}
    for d in set((real / "projects").glob("*")) - before:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def upload_asset(client):
    """Upload a local file through the real presign -> PUT -> complete flow; returns the asset json."""

    def _upload(path: Path = FIXTURE_VIDEO, content_type: str = "video/mp4", project_id: str | None = None) -> dict:
        body = {"filename": path.name, "content_type": content_type, "purpose": "source_video", "size_bytes": path.stat().st_size}
        if project_id:
            body["project_id"] = project_id
        pre = client.post("/v1/uploads/presign", json=body)
        assert pre.status_code == 200, pre.text
        p = pre.json()
        put = client.put(p["url"], content=path.read_bytes(), headers={**p["headers"], "Authorization": ""})
        assert put.status_code == 200, put.text
        done = client.post(f"/v1/uploads/{p['asset_id']}/complete")
        assert done.status_code == 200, done.text
        return done.json()

    return _upload
