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
from server.schemas.edit import (
    EditAccepted,
    EditCreate,
    EditList,
    EditOut,
    InstructionCreate,
    RestoreRangeCreate,
    VariantsCreate,
)
from server.services import edit_service as es
from server.services import generation_service as gsvc
from server.services.capabilities import read_snapshot
from server.services.queue import QueueUnavailable

router = APIRouter(prefix="/v1/edits", tags=["edits"])
log = structlog.get_logger(__name__)
_IDEM = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def _idem(key: str | None) -> str | None:
    if key is not None and not _IDEM.match(key):
        raise AppError(ErrorCode.INVALID_REQUEST, "Idempotency-Key must be 1-128 chars: letters, digits, . _ : -", 422)
    return key


def _require_editing(redis_client) -> None:
    snap = read_snapshot(redis_client)
    if snap is not None and not snap.get("editing", snap.get("generation_available", False)):
        raise AppError(ErrorCode.PIPELINE_UNAVAILABLE, "Editing is temporarily unavailable.", 503)


def _accepted(gen) -> EditAccepted:
    return EditAccepted(id=gen.id, project_id=gen.project_id, status=gen.status, progress=gen.progress,
                        poll_url=f"/v1/edits/{gen.id}")


def _enqueue(session, enqueue, gen) -> None:
    try:
        enqueue(gen.id)
    except QueueUnavailable:
        log.error("enqueue_failed", edit_id=str(gen.id), exc_info=True)
        gsvc.mark_failed(session, gen.id, ErrorCode.QUEUE_UNAVAILABLE.value, "queue unavailable")
        raise AppError(ErrorCode.QUEUE_UNAVAILABLE, "Editing is temporarily unavailable.", 503)
    log.info("edit_enqueued", edit_id=str(gen.id), project_id=str(gen.project_id), kind=gen.kind)


@router.post("", status_code=202, response_model=EditAccepted)
def create_edit(body: EditCreate, response: Response, principal: Principal = Depends(get_principal), session=Depends(get_db),
                settings=Depends(get_settings_dep), limiter=Depends(get_rate_limiter_dep), redis_client=Depends(get_redis_dep),
                enqueue=Depends(get_enqueue), idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    _idem(idempotency_key)
    limiter.hit("generations", principal.user_id, settings.rate_limit_generations_per_minute)
    _require_editing(redis_client)
    gen, created = es.create_edit(session, body, user_id=principal.user_id, idempotency_key=idempotency_key, settings=settings)
    if not created:
        response.headers["Idempotent-Replay"] = "true"
        return _accepted(gen)
    _enqueue(session, enqueue, gen)
    return _accepted(gen)


@router.get("", response_model=EditList)
def list_edits(principal: Principal = Depends(get_principal), session=Depends(get_db), storage=Depends(get_storage_dep),
               project_id: uuid.UUID | None = Query(None)):
    return EditList(items=[es.edit_out(session, g, storage) for g in es.list_root_edits(session, principal.user_id, project_id)])


@router.get("/{edit_id}", response_model=EditOut)
def get_edit(edit_id: uuid.UUID, principal: Principal = Depends(get_principal), session=Depends(get_db),
             storage=Depends(get_storage_dep)):
    return es.edit_out(session, es.get_edit(session, edit_id, principal.user_id), storage)


@router.post("/{edit_id}/cancel", response_model=EditOut)
def cancel_edit(edit_id: uuid.UUID, principal: Principal = Depends(get_principal), session=Depends(get_db),
                storage=Depends(get_storage_dep)):
    es.get_edit(session, edit_id, principal.user_id)
    gen = gsvc.request_cancel(session, edit_id, principal.user_id)
    return es.edit_out(session, gen, storage)


@router.post("/{edit_id}/instructions", status_code=202, response_model=EditAccepted)
def add_instruction(edit_id: uuid.UUID, body: InstructionCreate, response: Response,
                    principal: Principal = Depends(get_principal), session=Depends(get_db), settings=Depends(get_settings_dep),
                    limiter=Depends(get_rate_limiter_dep), redis_client=Depends(get_redis_dep), enqueue=Depends(get_enqueue),
                    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    _idem(idempotency_key)
    limiter.hit("generations", principal.user_id, settings.rate_limit_generations_per_minute)
    _require_editing(redis_client)
    gen, created = es.create_revision(session, edit_id, body.instruction, user_id=principal.user_id,
                                      idempotency_key=idempotency_key, settings=settings)
    if not created:
        response.headers["Idempotent-Replay"] = "true"
        return _accepted(gen)
    _enqueue(session, enqueue, gen)
    return _accepted(gen)


@router.post("/{edit_id}/restore", status_code=202, response_model=EditAccepted)
def restore_range(edit_id: uuid.UUID, body: RestoreRangeCreate, response: Response,
                  principal: Principal = Depends(get_principal), session=Depends(get_db), settings=Depends(get_settings_dep),
                  limiter=Depends(get_rate_limiter_dep), redis_client=Depends(get_redis_dep), enqueue=Depends(get_enqueue),
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    _idem(idempotency_key)
    limiter.hit("generations", principal.user_id, settings.rate_limit_generations_per_minute)
    _require_editing(redis_client)
    gen, created = es.create_restore_revision(session, edit_id, body.model_dump(), user_id=principal.user_id,
                                               idempotency_key=idempotency_key, settings=settings)
    if not created:
        response.headers["Idempotent-Replay"] = "true"
        return _accepted(gen)
    _enqueue(session, enqueue, gen)
    return _accepted(gen)


@router.post("/{edit_id}/variants", status_code=202, response_model=EditList)
def create_variants(edit_id: uuid.UUID, body: VariantsCreate, response: Response,
                    principal: Principal = Depends(get_principal), session=Depends(get_db), storage=Depends(get_storage_dep),
                    settings=Depends(get_settings_dep), limiter=Depends(get_rate_limiter_dep),
                    redis_client=Depends(get_redis_dep), enqueue=Depends(get_enqueue),
                    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    _idem(idempotency_key)
    limiter.hit("generations", principal.user_id, settings.rate_limit_generations_per_minute)
    _require_editing(redis_client)
    rows, created = es.create_variants(session, edit_id, body.count, body.strategy, user_id=principal.user_id,
                                       idempotency_key=idempotency_key, settings=settings)
    if not created:
        response.headers["Idempotent-Replay"] = "true"
    else:
        for gen in rows:
            _enqueue(session, enqueue, gen)
    return EditList(items=[es.edit_out(session, g, storage, with_versions=False) for g in rows])


@router.get("/{edit_id}/variants", response_model=EditList)
def list_variants(edit_id: uuid.UUID, principal: Principal = Depends(get_principal), session=Depends(get_db),
                  storage=Depends(get_storage_dep)):
    rows = es.list_variants(session, edit_id, principal.user_id)
    return EditList(items=[es.edit_out(session, g, storage, with_versions=False) for g in rows])
