"""Generation persistence + state machine.

All worker-side transitions are conditional UPDATEs so a late writer can never
resurrect a terminal job (e.g. mark a cancelled job completed).
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core.config import Settings
from server.core.errors import AppError, ErrorCode, client_message
from server.db.models import ACTIVE_STATUSES, TERMINAL_STATUSES, Generation, GenerationStatus, utcnow
from server.schemas.generation import GenerationCreate, GenerationError, GenerationOut
from server.services.pipelines import display_stage, get_pipeline, pipeline_manifest_exists
from server.services.storage import StorageService

S = GenerationStatus
TERMINAL_VALUES = {s.value for s in TERMINAL_STATUSES}
ACTIVE_VALUES = {s.value for s in ACTIVE_STATUSES}
RUNNABLE_VALUES = {S.queued.value, S.starting.value, S.running.value}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def fingerprint(req: GenerationCreate) -> str:
    return hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()


def fingerprint_obj(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def create_generation(
    session: Session,
    req: GenerationCreate,
    *,
    user_id: str,
    idempotency_key: str | None,
    settings: Settings,
) -> tuple[Generation, bool]:
    """Returns (generation, created). ``created`` False => idempotent replay."""
    if not get_pipeline(req.pipeline) or not pipeline_manifest_exists(req.pipeline):
        raise AppError(ErrorCode.PIPELINE_UNAVAILABLE, "Unknown or unavailable pipeline.", 422)

    scoped_key = f"{user_id}:{idempotency_key}" if idempotency_key else None
    fp = fingerprint(req)

    if scoped_key:
        existing = session.scalar(select(Generation).where(Generation.idempotency_key == scoped_key))
        if existing:
            return _replay(existing, fp), False

    gen = Generation(
        id=uuid.uuid4(),
        user_id=user_id,
        idempotency_key=scoped_key,
        prompt=req.prompt,
        pipeline=req.pipeline,
        status=S.queued.value,
        progress=0,
        duration_seconds_requested=req.duration_seconds,
        aspect_ratio=req.aspect_ratio,
        style=req.style,
        voice_enabled=req.voice_enabled,
        captions_enabled=req.captions_enabled,
        quality_profile=req.quality,
        runtime_provider=settings.orchestrator_provider,
        meta={"request_fingerprint": fp},
    )
    session.add(gen)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if scoped_key:  # lost a race with a concurrent identical request
            existing = session.scalar(select(Generation).where(Generation.idempotency_key == scoped_key))
            if existing:
                return _replay(existing, fp), False
        raise
    return gen, True


def _replay(existing: Generation, fp: str) -> Generation:
    if (existing.meta or {}).get("request_fingerprint") != fp:
        raise AppError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "This Idempotency-Key was already used with a different request.",
            409,
        )
    return existing


def get_generation(session: Session, generation_id: uuid.UUID, user_id: str) -> Generation:
    gen = session.get(Generation, generation_id)
    if gen is None or gen.user_id != user_id:
        raise AppError(ErrorCode.GENERATION_NOT_FOUND, "Generation not found.", 404)
    return gen


def _encode_cursor(gen: Generation) -> str:
    raw = f"{_aware(gen.created_at).isoformat()}|{gen.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, _, gid = raw.partition("|")
        return datetime.fromisoformat(ts), uuid.UUID(gid)
    except Exception as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid cursor.", 422) from exc


def list_generations(
    session: Session, user_id: str, *, limit: int, cursor: str | None, status: str | None
) -> tuple[list[Generation], str | None]:
    stmt = select(Generation).where(Generation.user_id == user_id, Generation.kind == "generation")
    if status:
        stmt = stmt.where(Generation.status == status)
    if cursor:
        c_ts, c_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(Generation.created_at < c_ts, and_(Generation.created_at == c_ts, Generation.id < c_id))
        )
    stmt = stmt.order_by(Generation.created_at.desc(), Generation.id.desc()).limit(limit + 1)
    rows = list(session.scalars(stmt))
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


def to_out(gen: Generation, storage: StorageService) -> GenerationOut:
    """Client-safe projection. Never includes paths, metadata, costs or raw errors."""
    error = None
    if gen.status == S.failed.value:
        code = gen.error_code or ErrorCode.GENERATION_FAILED.value
        error = GenerationError(code=code, message=client_message(code))
    output_url = thumb_url = None
    if gen.status == S.completed.value:
        if gen.output_storage_key:
            output_url = storage.url_for(gen.output_storage_key)
        if gen.thumbnail_storage_key:
            thumb_url = storage.url_for(gen.thumbnail_storage_key)
    stage = gen.current_stage
    if gen.status == S.completed.value:
        stage = "complete"
    return GenerationOut(
        id=gen.id,
        status=gen.status,
        progress=100 if gen.status == S.completed.value else gen.progress,
        current_stage=stage,
        display_stage=display_stage(stage),
        duration_seconds=gen.duration_seconds_requested,
        aspect_ratio=gen.aspect_ratio,
        style=gen.style,
        prompt=gen.prompt,
        voice_enabled=gen.voice_enabled,
        captions_enabled=gen.captions_enabled,
        quality=gen.quality_profile,
        output_url=output_url,
        thumbnail_url=thumb_url,
        error=error,
        created_at=_aware(gen.created_at),
        started_at=_aware(gen.started_at),
        completed_at=_aware(gen.completed_at),
        updated_at=_aware(gen.updated_at),
    )


def request_cancel(session: Session, generation_id: uuid.UUID, user_id: str) -> Generation:
    gen = get_generation(session, generation_id, user_id)
    now = utcnow()
    # Not picked up by a worker yet: nothing to stop, cancel immediately.
    n = session.execute(
        update(Generation)
        .where(Generation.id == generation_id, Generation.status == S.queued.value)
        .values(status=S.cancelled.value, completed_at=now, updated_at=now, error_code=ErrorCode.CANCELLED.value)
    ).rowcount
    if not n:
        session.execute(
            update(Generation)
            .where(Generation.id == generation_id, Generation.status.in_([S.starting.value, S.running.value]))
            .values(status=S.cancel_requested.value, updated_at=now)
        )
    session.commit()
    session.refresh(gen)
    return gen


# --------------------------------------------------------------------------
# Worker-side transitions
# --------------------------------------------------------------------------

def _apply(session: Session, generation_id: uuid.UUID, allowed_from: set[str], **values: Any) -> bool:
    values.setdefault("updated_at", utcnow())
    n = session.execute(
        update(Generation).where(Generation.id == generation_id, Generation.status.in_(allowed_from)).values(**values)
    ).rowcount
    session.commit()
    return bool(n)


def mark_starting(session: Session, generation_id: uuid.UUID, project_path: str, runtime: str) -> bool:
    return _apply(
        session,
        generation_id,
        RUNNABLE_VALUES,
        status=S.starting.value,
        current_stage="starting",
        started_at=utcnow(),
        project_path=project_path,
        runtime_provider=runtime,
        error_code=None,
        error_message=None,
    )


def mark_running(session: Session, generation_id: uuid.UUID) -> bool:
    return _apply(session, generation_id, {S.starting.value, S.running.value}, status=S.running.value)


def update_progress(
    session: Session,
    generation_id: uuid.UUID,
    progress: int,
    stage: str | None,
    *,
    spent_usd: float | None = None,
) -> bool:
    """Monotonic progress; only while the job is still live."""
    gen = session.get(Generation, generation_id)
    if gen is None or gen.status not in {S.starting.value, S.running.value, S.cancel_requested.value}:
        return False
    values: dict[str, Any] = {"progress": max(gen.progress, min(99, progress))}
    if stage:
        values["current_stage"] = stage
    if spent_usd is not None:
        values["actual_cost_usd"] = spent_usd
    return _apply(session, generation_id, {S.starting.value, S.running.value, S.cancel_requested.value}, **values)


def mark_completed(
    session: Session,
    generation_id: uuid.UUID,
    *,
    output_key: str,
    thumbnail_key: str | None,
    output_url: str | None,
    thumbnail_url: str | None,
    actual_cost_usd: float | None,
    metadata_update: dict | None = None,
) -> bool:
    gen = session.get(Generation, generation_id)
    meta = dict(gen.meta or {}) if gen else {}
    meta.update(metadata_update or {})
    return _apply(
        session,
        generation_id,
        {S.starting.value, S.running.value, S.cancel_requested.value},  # finished before cancel took effect
        status=S.completed.value,
        progress=100,
        current_stage="complete",
        output_storage_key=output_key,
        thumbnail_storage_key=thumbnail_key,
        output_url=output_url,
        thumbnail_url=thumbnail_url,
        actual_cost_usd=actual_cost_usd,
        completed_at=utcnow(),
        error_code=None,
        error_message=None,
        meta=meta,
    )


def mark_failed(session: Session, generation_id: uuid.UUID, code: str, safe_message: str) -> bool:
    return _apply(
        session,
        generation_id,
        RUNNABLE_VALUES | {S.cancel_requested.value},
        status=S.failed.value,
        error_code=code,
        error_message=safe_message[:500],
        completed_at=utcnow(),
    )


def mark_cancelled(session: Session, generation_id: uuid.UUID) -> bool:
    return _apply(
        session,
        generation_id,
        RUNNABLE_VALUES | {S.cancel_requested.value},
        status=S.cancelled.value,
        error_code=ErrorCode.CANCELLED.value,
        completed_at=utcnow(),
    )


def is_cancel_requested(session: Session, generation_id: uuid.UUID) -> bool:
    session.expire_all()
    status = session.scalar(select(Generation.status).where(Generation.id == generation_id))
    return status in (S.cancel_requested.value, S.cancelled.value)


def mark_requeued(session: Session, generation_id: uuid.UUID, restarts: int) -> bool:
    """Return an interrupted job (worker shutting down) to the queue."""
    gen = session.get(Generation, generation_id)
    meta = dict(gen.meta or {}) if gen else {}
    meta["restarts"] = restarts
    return _apply(
        session,
        generation_id,
        {S.starting.value, S.running.value},
        status=S.queued.value,
        current_stage=None,
        meta=meta,
    )
