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
