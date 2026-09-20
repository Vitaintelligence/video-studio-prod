from __future__ import annotations

import re
import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Response

from server.api.dependencies import (
    get_db,
    get_enqueue,
    get_principal,
    get_rate_limiter_dep,
    get_redis_dep,
    get_settings_dep,
    get_storage_dep,
)
from server.core.errors import AppError, ErrorCode
from server.core.security import Principal
from server.schemas.generation import (
    GenerationAccepted,
    GenerationCreate,
    GenerationList,
    GenerationOut,
    StatusLiteral,
)
from server.services import generation_service as svc
from server.services.capabilities import read_snapshot
from server.services.queue import QueueUnavailable

router = APIRouter(prefix="/v1/generations", tags=["generations"])
log = structlog.get_logger(__name__)

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def _accepted(gen) -> GenerationAccepted:
    return GenerationAccepted(
        id=gen.id,
        status=gen.status,
        progress=gen.progress,
        current_stage=gen.current_stage,
        created_at=svc._aware(gen.created_at),
        poll_url=f"/v1/generations/{gen.id}",
    )


@router.post("", status_code=202, response_model=GenerationAccepted)
def create_generation(
    body: GenerationCreate,
    response: Response,
    principal: Principal = Depends(get_principal),
    session=Depends(get_db),
    settings=Depends(get_settings_dep),
    limiter=Depends(get_rate_limiter_dep),
    redis_client=Depends(get_redis_dep),
    enqueue=Depends(get_enqueue),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    if idempotency_key is not None and not _IDEMPOTENCY_RE.match(idempotency_key):
        raise AppError(ErrorCode.INVALID_REQUEST, "Idempotency-Key must be 1-128 chars: letters, digits, . _ : -", 422)

    limiter.hit("generations", principal.user_id, settings.rate_limit_generations_per_minute)

    # If a worker has reported that it cannot generate, refuse instead of queueing
    # a job that is certain to fail. No report at all => queue anyway.
    snap = read_snapshot(redis_client)
    if snap is not None and not snap.get("generation_available", False):
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "Video creation is temporarily unavailable.", 503)

    gen, created = svc.create_generation(
        session, body, user_id=principal.user_id, idempotency_key=idempotency_key, settings=settings
    )
    if not created:
        response.headers["Idempotent-Replay"] = "true"
        return _accepted(gen)

    try:
        enqueue(gen.id)
    except QueueUnavailable:
        log.error("enqueue_failed", generation_id=str(gen.id), exc_info=True)
        svc.mark_failed(session, gen.id, ErrorCode.QUEUE_UNAVAILABLE.value, "queue unavailable")
        raise AppError(ErrorCode.QUEUE_UNAVAILABLE, "Video creation is temporarily unavailable.", 503)

    log.info("generation_enqueued", generation_id=str(gen.id), pipeline=gen.pipeline)
    return _accepted(gen)


@router.get("", response_model=GenerationList)
def list_generations(
    principal: Principal = Depends(get_principal),
    session=Depends(get_db),
    storage=Depends(get_storage_dep),
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None, max_length=200),
    status: StatusLiteral | None = Query(None),
):
    rows, next_cursor = svc.list_generations(session, principal.user_id, limit=limit, cursor=cursor, status=status)
    return GenerationList(items=[svc.to_out(r, storage) for r in rows], next_cursor=next_cursor)


@router.get("/{generation_id}", response_model=GenerationOut)
def get_generation(
    generation_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session=Depends(get_db),
    storage=Depends(get_storage_dep),
):
    return svc.to_out(svc.get_generation(session, generation_id, principal.user_id), storage)


@router.post("/{generation_id}/cancel", response_model=GenerationOut)
def cancel_generation(
    generation_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session=Depends(get_db),
    storage=Depends(get_storage_dep),
):
    gen = svc.request_cancel(session, generation_id, principal.user_id)
    log.info("generation_cancel_requested", generation_id=str(gen.id), status=gen.status)
    return svc.to_out(gen, storage)

