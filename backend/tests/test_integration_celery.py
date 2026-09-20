"""API -> Celery (real worker, in-process, memory broker) -> DB roundtrip.

Exercises the real task registration, queue routing (`generations`), JSON serialization of
the task message, `send_task` by name from the API, and the worker consuming it - the
pieces the unit tests replace with fakes. Uses the mock runtime (no cost)."""

from __future__ import annotations

import shutil
import time

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe required")


def test_api_enqueue_is_consumed_by_a_celery_worker_and_completes(env, fake_redis, monkeypatch, valid_body):
    from celery.contrib.testing.worker import start_worker
    from fastapi.testclient import TestClient

    from server.api.main import create_app
    from server.services.ratelimit import RateLimiter
    from server.worker.celery_app import celery_app
    from tests.conftest import TEST_TOKEN

    monkeypatch.setenv("MOCK_RUNTIME_STAGE_DELAY", "0.05")
    saved = dict(broker_url=celery_app.conf.broker_url, broker_transport_options=celery_app.conf.broker_transport_options)
    celery_app.conf.update(broker_url="memory://", broker_transport_options={})
    celery_app._pool = None  # drop any cached producer pool bound to the previous broker
    try:
        app = create_app(env["settings"])  # real enqueue_generation (no fake)
        limiter = RateLimiter(fake_redis)
        app.state.get_redis = lambda: fake_redis
        app.state.get_rate_limiter = lambda: limiter
        with start_worker(celery_app, pool="solo", perform_ping_check=False, queues=["generations"], loglevel="WARNING"):
            with TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}) as c:
                r = c.post("/v1/generations", json=valid_body, headers={"Idempotency-Key": "roundtrip-1"})
                assert r.status_code == 202
                gid = r.json()["id"]
                deadline, seen = time.monotonic() + 90, []
                while time.monotonic() < deadline:
                    st = c.get(f"/v1/generations/{gid}").json()
                    seen.append((st["status"], st["progress"]))
                    if st["status"] in ("completed", "failed", "cancelled"):
                        break
                    time.sleep(0.1)
                assert st["status"] == "completed", (st, seen[-5:])
                assert st["progress"] == 100 and st["display_stage"] == "Ready"
                assert st["output_url"].endswith(f"/generations/{gid}/final.mp4")
                progresses = [p for _, p in seen]
                assert progresses == sorted(progresses)
                # the stored object really exists and is servable in dev mode
                media = c.get(st["output_url"], headers={"Authorization": ""})
                assert media.status_code == 200 and len(media.content) > 1000
    finally:
        celery_app.conf.update(**saved)
        celery_app._pool = None
