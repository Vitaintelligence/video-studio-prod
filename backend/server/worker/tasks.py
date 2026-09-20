"""The generation task: load -> run runtime -> validate -> upload -> persist.

``execute_generation`` holds the logic (dependency-injected for tests);
``run_generation`` is the thin Celery wrapper.
"""

from __future__ import annotations

import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session, sessionmaker

from server.core.config import Settings, get_settings
from server.core.errors import ErrorCode, client_message, sanitize_text
from server.core.logging import bind_generation, clear_context, prompt_fingerprint
from server.db.models import TERMINAL_STATUSES, Generation
from server.db.session import get_sessionmaker
from server.runtime.base import Abort, JobContext, RuntimeOrchestrator
from server.runtime.factory import build_runtime
from server.runtime.openmontage_runtime import (
    compose_completed,
    find_final_output,
    prepare_workspace,
    purge_old_workspaces,
    safe_project_id,
)
from server.services import edit_service as edits
from server.services import generation_service as svc
from server.services.checkpoint_monitor import CheckpointMonitor
from server.services.output_validation import OutputInvalid, extract_thumbnail, validate_output
from server.services.pipelines import stage_order
from server.services.queue import TASK_NAME, enqueue_generation
from server.services.storage import StorageError, StorageService, get_storage, output_key, sanitize_filename
from server.worker import lifecycle
from server.worker.celery_app import celery_app

log = structlog.get_logger(__name__)

MAX_SHUTDOWN_RESTARTS = 5


class RetryableError(Exception):
    """Infrastructure hiccup (e.g. object storage): Celery retries with backoff."""


def _estimated_cost(project_dir: Path) -> float | None:
    try:
        cp = json.loads((project_dir / "checkpoint_proposal.json").read_text(encoding="utf-8"))
        est = cp["artifacts"]["proposal_packet"]["cost_estimate"]
        total = est.get("total_usd", est.get("total_estimated_usd"))
        return float(total) if total is not None else None
    except Exception:
        return None


def execute_generation(
    generation_id: str,
    *,
    task_id: str | None = None,
    attempt: int = 0,
    max_retries: int = 0,
    settings: Settings | None = None,
    sessionmaker_: sessionmaker[Session] | None = None,
    runtime: RuntimeOrchestrator | None = None,
    storage: StorageService | None = None,
    requeue: Callable[[uuid.UUID], object] = enqueue_generation,
    shutdown_requested: Callable[[], bool] = lifecycle.shutdown_requested,
) -> str:
    settings = settings or get_settings()
    sm = sessionmaker_ or get_sessionmaker()
    gid = uuid.UUID(generation_id)
    bind_generation(generation_id, task_id, runtime=settings.orchestrator_provider)
    started = time.monotonic()
    try:
        with sm() as session:
            return _execute(
                session, gid, settings, runtime or build_runtime(settings), storage or get_storage(),
                attempt, max_retries, requeue, shutdown_requested, started,
            )
    finally:
        clear_context()


def _fail(session: Session, gid: uuid.UUID, code: ErrorCode | str, internal: str) -> str:
    code_v = code.value if isinstance(code, ErrorCode) else code
    svc.mark_failed(session, gid, code_v, client_message(code_v))
    log.error("generation_failed", error_code=code_v, detail=sanitize_text(internal, 500))
    return "failed"


def _execute(
    session, gid, settings, runtime, storage, attempt, max_retries, requeue, shutdown_requested, started
) -> str:
    gen = session.get(Generation, gid)
    if gen is None:
        log.warning("generation_not_found")
        return "not_found"
    if gen.status in {s.value for s in TERMINAL_STATUSES}:
        log.info("generation_already_terminal", status=gen.status)
        return "already_terminal"
    if gen.status == "cancel_requested":
        svc.mark_cancelled(session, gid)
        return "cancelled"

    try:
        project_id = safe_project_id(gid)
        engine_dir = settings.openmontage_dir
        stages = stage_order(gen.pipeline)
        project_dir = prepare_workspace(engine_dir, project_id)
        purge_old_workspaces(engine_dir, settings.local_job_retention_hours, keep={project_id})
    except Exception as exc:
        return _fail(session, gid, ErrorCode.PIPELINE_UNAVAILABLE, f"workspace/pipeline setup failed: {exc!r}")

    if not svc.mark_starting(session, gid, f"projects/{project_id}", runtime.name):
        log.info("generation_not_startable")  # cancelled between load and start
        return "skipped"
    log.info("generation_starting", pipeline=gen.pipeline, **prompt_fingerprint(gen.prompt))

    is_edit = gen.kind in edits.EDIT_KINDS
    meta0 = gen.meta or {}
    instruction = edits.effective_instruction(session, gen) if is_edit else gen.prompt
    source_files: list[Path] = []
    if is_edit:
        try:
            for i, asset in enumerate(edits.source_assets(session, gen)):
                dest = project_dir / "assets" / "source" / f"{i:02d}_{sanitize_filename(asset.filename)}"
                if not dest.is_file():
                    storage.get_file(asset.storage_key, dest)
                source_files.append(dest)
            if not source_files:
                return _fail(session, gid, ErrorCode.GENERATION_FAILED, "edit has no source footage")
        except StorageError as exc:
            if attempt < max_retries:
                raise RetryableError("source download failed") from exc
            return _fail(session, gid, ErrorCode.STORAGE_FAILED, f"source download failed: {exc!r}")

    ctx = JobContext(
        generation_id=str(gid), project_id=project_id, project_dir=project_dir, engine_dir=engine_dir,
        pipeline=gen.pipeline, stages=stages, prompt=instruction, duration_seconds=gen.duration_seconds_requested,
        aspect_ratio=gen.aspect_ratio, style=gen.style, voice_enabled=gen.voice_enabled,
        captions_enabled=gen.captions_enabled, quality=gen.quality_profile,
        budget_usd=settings.max_job_budget_usd, poll_interval_seconds=settings.cancel_poll_seconds,
        kind=gen.kind, source_files=source_files, platform=gen.platform, cta_text=meta0.get("cta_text"),
        variant_label=gen.variant_label, hook_text=meta0.get("hook_text"),
        duration_explicit=bool(meta0.get("duration_explicit", True)),
    )
    # The chosen runtime may report a different stage vocabulary (e.g. the deterministic editor).
    stages = runtime.plan_stages(ctx) or stages
    ctx.stages = stages
    monitor = CheckpointMonitor(project_dir, stages)
    llm_cost = 0.0
    warnings: list[str] = []
    insights: dict = {}

    def poll() -> Abort | None:
        try:
            if shutdown_requested():
                return Abort("WORKER_SHUTDOWN", "worker is shutting down")
            if svc.is_cancel_requested(session, gid):
                return Abort(ErrorCode.CANCELLED.value, "cancel requested")
            snap = monitor.snapshot()
            svc.update_progress(session, gid, snap.progress, snap.current_stage, spent_usd=snap.total_spent_usd)
            if snap.awaiting_human:
                return Abort(ErrorCode.GENERATION_FAILED.value, "pipeline stopped at a human gate")
            if snap.total_spent_usd is not None and snap.total_spent_usd > settings.max_job_budget_usd:
                return Abort(ErrorCode.BUDGET_EXCEEDED.value, f"spent {snap.total_spent_usd:.2f} > cap")
        except Exception:
            log.exception("progress_poll_failed")
        return None

    try:
        # Idempotent retry: never pay to re-render a finished video.
        reuse = compose_completed(project_dir, stages[-1]) and find_final_output(project_dir, stages[-1]) is not None
        if reuse:
            log.info("reusing_rendered_output")
        else:
            svc.mark_running(session, gid)
            ctx.poll = poll
            result = runtime.run_generation(ctx)
            llm_cost = result.llm_cost_usd or 0.0
            warnings = list(result.warnings)
            insights = dict(result.insights)
            log.info("runtime_finished", status=result.status, turns=result.turns,
                     elapsed_ms=int((time.monotonic() - started) * 1000), detail=sanitize_text(result.detail, 400))

            if result.status == "aborted" and result.abort:
                code = result.abort.code
                if code == ErrorCode.CANCELLED.value:
                    svc.mark_cancelled(session, gid)
                    return "cancelled"
                if code == "WORKER_SHUTDOWN":
                    return _requeue(session, gid, gen, requeue)
                return _fail(session, gid, code, result.abort.reason)
            produced = compose_completed(project_dir, stages[-1]) and find_final_output(project_dir, stages[-1])
            if result.status != "completed" and not produced:
                return _fail(session, gid, result.error_code or ErrorCode.GENERATION_FAILED, result.detail)

        # ---- finalize: validate -> thumbnail -> upload -> persist ----
        svc.update_progress(session, gid, 92, "finalizing")
        final = find_final_output(project_dir, stages[-1])
        if final is None:
            return _fail(session, gid, ErrorCode.OUTPUT_INVALID, "no final output found")
        try:
            probe = validate_output(final, expect_audio=gen.voice_enabled)
        except OutputInvalid as exc:
            return _fail(session, gid, ErrorCode.OUTPUT_INVALID, str(exc))

        svc.update_progress(session, gid, 95, "uploading")
        with tempfile.TemporaryDirectory(prefix="thumb-") as tmp:
            thumb_path = Path(tmp) / "thumbnail.jpg"
            have_thumb = extract_thumbnail(final, thumb_path, min(1.0, probe.duration_seconds / 2))
            vkey = output_key(gid, "final.mp4")
            tkey = output_key(gid, "thumbnail.jpg") if have_thumb else None
            try:
                storage.put_file(vkey, final, "video/mp4")
                if tkey:
                    storage.put_file(tkey, thumb_path, "image/jpeg")
            except StorageError as exc:
                if attempt < max_retries:
                    raise RetryableError("storage upload failed") from exc
                return _fail(session, gid, ErrorCode.STORAGE_FAILED, f"upload failed after retries: {exc!r}")

        snap = monitor.snapshot()
        provider_spend = snap.total_spent_usd or 0.0
        ok = svc.mark_completed(
            session, gid,
            output_key=vkey, thumbnail_key=tkey,
            output_url=storage.url_for(vkey) if settings.r2_public_base_url or storage.backend == "local" else None,
            thumbnail_url=storage.url_for(tkey) if tkey and (settings.r2_public_base_url or storage.backend == "local") else None,
            actual_cost_usd=round(provider_spend + llm_cost, 4),
            metadata_update={
                "output": {
                    "duration_seconds": round(probe.duration_seconds, 2), "size_bytes": probe.size_bytes,
                    "video_codec": probe.video_codec, "has_audio": probe.has_audio,
                    "width": probe.width, "height": probe.height,
                },
                "provider_cost_usd": provider_spend, "llm_cost_usd": round(llm_cost, 4),
                "warnings": warnings, "insights": insights,
            },
        )
        est = _estimated_cost(project_dir)
        if est is not None:
            gen.estimated_cost_usd = est
            session.commit()
        log.info("generation_completed", persisted=ok, elapsed_ms=int((time.monotonic() - started) * 1000))
        _cleanup_media(project_dir)
        return "completed" if ok else "skipped"

    except RetryableError:
        raise
    except SoftTimeLimitExceeded:
        return _fail(session, gid, ErrorCode.TIMEOUT, "celery soft time limit exceeded")
    except Exception as exc:
        log.exception("generation_unexpected_error")
        return _fail(session, gid, ErrorCode.GENERATION_FAILED, f"unexpected {type(exc).__name__}")


def _requeue(session, gid, gen, requeue) -> str:
    restarts = int((gen.meta or {}).get("restarts", 0)) + 1
    if restarts > MAX_SHUTDOWN_RESTARTS:
        return _fail(session, gid, ErrorCode.GENERATION_FAILED, "too many worker restarts")
    if svc.mark_requeued(session, gid, restarts):
        try:
            requeue(gid)
        except Exception:
            log.exception("requeue_failed")  # DB says queued; visibility-timeout redelivery is the backstop
    log.warning("generation_requeued_on_shutdown", restarts=restarts)
    return "requeued"


def _cleanup_media(project_dir: Path) -> None:
    """Drop large media once it is safely uploaded and persisted; keep JSON for debugging."""
    import shutil

    for sub in ("renders", "assets", "snapshots"):
        shutil.rmtree(project_dir / sub, ignore_errors=True)


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(RetryableError,),
    retry_backoff=15,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=get_settings().task_max_retries,
)
def run_generation(self, generation_id: str) -> str:
    return execute_generation(
        generation_id,
        task_id=self.request.id,
        attempt=self.request.retries,
        max_retries=self.max_retries,
    )
