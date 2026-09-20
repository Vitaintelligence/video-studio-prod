#!/usr/bin/env python
"""Self-contained local stack for end-to-end runs without Docker/Redis/Postgres.

One process: the real FastAPI app served over HTTP (uvicorn), a real Celery worker running the real
`run_generation` task over an in-memory broker, SQLite (migrated with Alembic), local storage, and an
in-process Redis stand-in for rate limits / capability snapshot.

    python scripts/dev_stack.py --port 8010 --provider local_edit

Providers: local_edit (real deterministic editing: FFmpeg + OpenMontage video_trimmer) | mock.
Prints `READY <url> <token>` when serving. Ctrl+C to stop. Development only - never deploy this.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--provider", default="local_edit", choices=["local_edit", "mock"])
    ap.add_argument("--token", default="dev-stack-token-0123456789abcdef0123")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()

    data = Path(args.data_dir or tempfile.mkdtemp(prefix="devstack-"))
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "APP_ENV": "development", "LOG_LEVEL": "WARNING", "DEV_API_TOKEN": args.token,
        "DATABASE_URL": f"sqlite+pysqlite:///{data / 'dev.db'}", "ORCHESTRATOR_PROVIDER": args.provider,
        "STORAGE_BACKEND": "local", "LOCAL_STORAGE_PATH": str(data / "storage"),
        "AGENT_TRANSCRIPT_DIR": str(data / "agent-logs"), "CANCEL_POLL_SECONDS": "0.3",
        "MOCK_RUNTIME_STAGE_DELAY": "0.8",
    })

    import fakeredis
    import uvicorn
    from alembic import command
    from alembic.config import Config
    from celery.contrib.testing.worker import start_worker

    from server.api.main import create_app
    from server.core.config import get_settings
    from server.services.capabilities import SNAPSHOT_KEY, normalize
    from server.services.ratelimit import RateLimiter
    from server.worker.celery_app import celery_app

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")

    settings = get_settings()
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    raw = {"registry_ok": True, "capabilities": {}, "composition_runtimes": {"ffmpeg": True}}
    redis_client.set(SNAPSHOT_KEY, json.dumps(normalize(raw, settings)))  # what a real worker would publish

    celery_app.conf.update(broker_url="memory://", broker_transport_options={})
    app = create_app(settings)
    limiter = RateLimiter(redis_client)
    app.state.get_redis = lambda: redis_client
    app.state.get_rate_limiter = lambda: limiter

    with start_worker(celery_app, pool="solo", perform_ping_check=False, queues=["generations"], loglevel="WARNING"):
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            thread.join(0.1)
        print(f"READY http://127.0.0.1:{args.port} {args.token}", flush=True)
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
