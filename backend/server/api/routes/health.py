from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from server.api.dependencies import get_db, get_redis_dep
from server.schemas.misc import HealthOut
from server.services.capabilities import read_snapshot

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Shallow liveness probe (Railway healthcheck). No dependencies touched."""
    return HealthOut(status="ok")


@router.get("/ready")
def ready(session=Depends(get_db), redis_client=Depends(get_redis_dep)):
    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        log.warning("ready_database_unreachable", exc_info=True)
        checks["database"] = "unavailable"
    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        log.warning("ready_redis_unreachable", exc_info=True)
        checks["redis"] = "unavailable"

    # Informational only: the API holds no provider keys, so it reports what the
    # worker last published. Never fails readiness.
    snap = read_snapshot(redis_client) if checks["redis"] == "ok" else None
    checks["worker_capabilities"] = "ok" if snap and snap.get("status") == "ok" else "unknown"

    healthy = checks["database"] == "ok" and checks["redis"] == "ok"
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status_code=200 if healthy else 503,
    )
