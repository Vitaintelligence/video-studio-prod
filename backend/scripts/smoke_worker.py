#!/usr/bin/env python
"""Worker smoke test.

Default (no broker needed): runs the full worker pipeline in-process with the
zero-cost mock runtime against the configured DATABASE_URL/storage, then reports.

    python scripts/smoke_worker.py            # in-process
    python scripts/smoke_worker.py --ping     # also check a live Celery worker answers over Redis
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from server.core.config import get_settings
    from server.core.logging import configure_logging
    from server.db.models import Generation
    from server.db.session import get_sessionmaker
    from server.runtime.mock_runtime import MockRuntime
    from server.schemas.generation import GenerationCreate
    from server.services import generation_service as svc
    from server.worker.tasks import execute_generation

    settings = get_settings()
    configure_logging("WARNING", json_logs=False)

    if "--ping" in sys.argv:
        from server.worker.celery_app import celery_app

        replies = celery_app.control.ping(timeout=5)
        print(f"celery workers responding: {len(replies)}")
        if not replies:
            return 1

    req = GenerationCreate(prompt="Smoke test: a paper boat drifting down a rainy street.", duration_seconds=15)
    with get_sessionmaker()() as s:
        gen, _ = svc.create_generation(s, req, user_id="smoke", idempotency_key=None, settings=settings)
        gid = gen.id
    outcome = execute_generation(str(gid), settings=settings, runtime=MockRuntime(0.1), shutdown_requested=lambda: False)
    with get_sessionmaker()() as s:
        gen = s.get(Generation, gid)
        print(f"outcome={outcome} status={gen.status} progress={gen.progress} key={gen.output_storage_key}")
        print(f"output meta={gen.meta.get('output')}")
        return 0 if gen.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
