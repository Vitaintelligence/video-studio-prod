"""Product API layer over the generation engine.

An *edit* is a `generations` row with kind = edit | revision | variant. Nothing here executes
work: creation only validates + persists; the worker (`run_generation`) does the rest, using the
same state machine, queue, idempotency and progress plumbing as text-to-video generations.

Model:   Edit (version 1, kind=edit)
           |- Revision (kind=revision, version 2, 3, ...)  - non-destructive: previous outputs are kept
           `- Variant  (kind=variant, hook direction)      - an ordinary edit with its own output
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core.config import Settings
from server.core.errors import AppError, ErrorCode, client_message
from server.db.models import Asset, Generation, GenerationStatus, Project, utcnow
from server.schemas.edit import (
    AssetOut,
    EditCreate,
    EditOut,
    ProjectDetail,
    ProjectOut,
    VariantInfo,
    VersionOut,
)
from server.schemas.generation import GenerationError
from server.services.edit_planner import ALLOWED_VARIANT_STRATEGIES, DEFAULT_HOOK_STRATEGIES, HOOK_STRATEGIES
from server.services.generation_service import _aware, fingerprint_obj
from server.services.pipelines import display_stage, pipeline_manifest_exists
from server.services.storage import StorageService

S = GenerationStatus
EDIT_KINDS = ("edit", "revision", "variant")
DEFAULT_PIPELINE = "app-cinematic"
MAX_ACTIVE_JOBS_PER_USER = 8


# --------------------------------------------------------------------------- projects
def create_project(session: Session, user_id: str, name: str) -> Project:
    p = Project(id=uuid.uuid4(), user_id=user_id, name=name)
    session.add(p)
    session.commit()
    return p


def get_project(session: Session, project_id: uuid.UUID, user_id: str) -> Project:
    p = session.get(Project, project_id)
    if p is None or p.user_id != user_id:
        raise AppError(ErrorCode.NOT_FOUND, "Project not found.", 404)
    return p


def _latest_root_edit(session: Session, project_id: uuid.UUID) -> Generation | None:
    return session.scalar(
        select(Generation).where(Generation.project_id == project_id, Generation.kind == "edit")
        .order_by(Generation.created_at.desc()).limit(1)
    )


def project_out(session: Session, p: Project, storage: StorageService) -> ProjectOut:
    count = session.scalar(select(func.count()).select_from(Generation).where(
        Generation.project_id == p.id, Generation.kind == "edit")) or 0
    latest = _latest_root_edit(session, p.id)
    return ProjectOut(id=p.id, name=p.name, created_at=_aware(p.created_at), updated_at=_aware(p.updated_at),
                      edit_count=count, latest_edit=edit_out(session, latest, storage) if latest else None)


def project_detail(session: Session, p: Project, storage: StorageService) -> ProjectDetail:
    base = project_out(session, p, storage)
    assets = list(session.scalars(select(Asset).where(Asset.project_id == p.id).order_by(Asset.created_at)))
    edits = list(session.scalars(select(Generation).where(Generation.project_id == p.id, Generation.kind == "edit")
                                 .order_by(Generation.created_at.desc())))
    return ProjectDetail(**base.model_dump(), assets=[asset_out(a) for a in assets],
                         edits=[edit_out(session, e, storage) for e in edits])


def list_projects(session: Session, user_id: str, storage: StorageService, limit: int = 50) -> list[ProjectOut]:
    rows = session.scalars(select(Project).where(Project.user_id == user_id).order_by(Project.updated_at.desc()).limit(limit))
    return [project_out(session, p, storage) for p in rows]


def asset_out(a: Asset) -> AssetOut:
    return AssetOut(id=a.id, project_id=a.project_id, filename=a.filename, content_type=a.content_type, purpose=a.purpose,
                    size_bytes=a.size_bytes, status=a.status, created_at=_aware(a.created_at))


# --------------------------------------------------------------------------- creation
def _active_jobs(session: Session, user_id: str) -> int:
    return session.scalar(select(func.count()).select_from(Generation).where(
        Generation.user_id == user_id, Generation.status.in_([S.queued.value, S.starting.value, S.running.value]))) or 0


def _guard(session: Session, user_id: str, adding: int = 1) -> None:
    if _active_jobs(session, user_id) + adding > MAX_ACTIVE_JOBS_PER_USER:
        raise AppError(ErrorCode.RATE_LIMITED, "You have too many edits in progress. Please wait for one to finish.", 429)


def _existing_by_key(session: Session, scoped_key: str | None) -> Generation | None:
    return session.scalar(select(Generation).where(Generation.idempotency_key == scoped_key)) if scoped_key else None


def _replay(existing: Generation, fp: str) -> Generation:
    if (existing.meta or {}).get("request_fingerprint") != fp:
        raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT, "This Idempotency-Key was already used with a different request.", 409)
    return existing


def _persist(session: Session, gen: Generation, scoped_key: str | None, fp: str) -> tuple[Generation, bool]:
    session.add(gen)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _existing_by_key(session, scoped_key)
        if existing:
            return _replay(existing, fp), False
        raise
    return gen, True


def create_edit(session: Session, req: EditCreate, *, user_id: str, idempotency_key: str | None,
                settings: Settings) -> tuple[Generation, bool]:
    if req.brand_kit_id is not None:
        raise AppError(ErrorCode.INVALID_REQUEST, "Brand kits are not available yet.", 422)
    if not pipeline_manifest_exists(DEFAULT_PIPELINE):
        raise AppError(ErrorCode.PIPELINE_UNAVAILABLE, "Editing is temporarily unavailable.", 503)
    if len(req.asset_ids) > settings.max_assets_per_edit:
        raise AppError(ErrorCode.INVALID_REQUEST, "Too many source files.", 422)

    scoped_key = f"{user_id}:{idempotency_key}" if idempotency_key else None
    fp = fingerprint_obj(req.model_dump(mode="json"))
    existing = _existing_by_key(session, scoped_key)
    if existing:
        return _replay(existing, fp), False

    assets = list(session.scalars(select(Asset).where(Asset.id.in_(req.asset_ids), Asset.user_id == user_id)))
    if len(assets) != len(set(req.asset_ids)):
        raise AppError(ErrorCode.INVALID_REQUEST, "One or more source files were not found.", 422)
    if any(a.status != "uploaded" for a in assets):
        raise AppError(ErrorCode.INVALID_REQUEST, "One or more source files have not finished uploading.", 422)
    _guard(session, user_id)

    if req.project_id is not None:
        project = get_project(session, req.project_id, user_id)
    else:
        project = Project(id=uuid.uuid4(), user_id=user_id, name=req.instruction[:48].strip() or "Untitled edit")
        session.add(project)
    for a in assets:
        if a.project_id is None:
            a.project_id = project.id
    project.updated_at = utcnow()

    ordered_ids = [str(i) for i in dict.fromkeys(req.asset_ids)]
    gen = Generation(
        id=uuid.uuid4(), user_id=user_id, idempotency_key=scoped_key, prompt=req.instruction, pipeline=DEFAULT_PIPELINE,
        status=S.queued.value, progress=0, duration_seconds_requested=req.duration_target_seconds or 30,
        aspect_ratio=req.aspect_ratio, style=None, voice_enabled=True, captions_enabled=True, quality_profile="standard",
        runtime_provider=settings.orchestrator_provider, kind="edit", project_id=project.id, revision_number=1,
        platform=req.platform,
        meta={"request_fingerprint": fp, "asset_ids": ordered_ids, "cta_text": req.cta_text,
              "duration_explicit": req.duration_target_seconds is not None},
    )
    return _persist(session, gen, scoped_key, fp)


def _root_of(session: Session, gen: Generation) -> Generation:
    if gen.kind == "edit":
        return gen
    root = session.get(Generation, gen.parent_id) if gen.parent_id else None
    if root is None:
        raise AppError(ErrorCode.NOT_FOUND, "Edit not found.", 404)
    return root


def get_edit(session: Session, edit_id: uuid.UUID, user_id: str) -> Generation:
    gen = session.get(Generation, edit_id)
    if gen is None or gen.user_id != user_id or gen.kind not in EDIT_KINDS:
        raise AppError(ErrorCode.NOT_FOUND, "Edit not found.", 404)
    return gen


def create_revision(session: Session, edit_id: uuid.UUID, instruction: str, *, user_id: str,
                    idempotency_key: str | None, settings: Settings) -> tuple[Generation, bool]:
    """Prompt-to-edit: a NEW version; the previous output is never touched."""
    target = get_edit(session, edit_id, user_id)
    if target.kind == "variant":
        raise AppError(ErrorCode.INVALID_REQUEST, "Variants cannot be revised; revise the original edit.", 422)
    root = _root_of(session, target)
    scoped_key = f"{user_id}:{idempotency_key}" if idempotency_key else None
    fp = fingerprint_obj({"edit": str(root.id), "instruction": instruction})
    existing = _existing_by_key(session, scoped_key)
    if existing:
        return _replay(existing, fp), False
    if target.status not in (S.completed.value,):
        raise AppError(ErrorCode.INVALID_REQUEST, "Wait for this version to finish before revising it.", 409)
    _guard(session, user_id)

    last = session.scalar(select(func.max(Generation.revision_number)).where(
        (Generation.id == root.id) | ((Generation.parent_id == root.id) & (Generation.kind == "revision")))) or 1
    gen = Generation(
        id=uuid.uuid4(), user_id=user_id, idempotency_key=scoped_key, prompt=instruction, pipeline=root.pipeline,
        status=S.queued.value, progress=0, duration_seconds_requested=root.duration_seconds_requested,
        aspect_ratio=root.aspect_ratio, style=None, voice_enabled=True, captions_enabled=True, quality_profile="standard",
        runtime_provider=settings.orchestrator_provider, kind="revision", project_id=root.project_id, parent_id=root.id,
        revision_number=last + 1, platform=root.platform,
        meta={"request_fingerprint": fp, "asset_ids": (root.meta or {}).get("asset_ids", []),
              "cta_text": (root.meta or {}).get("cta_text"),
              "duration_explicit": (root.meta or {}).get("duration_explicit", False)},
    )
    return _persist(session, gen, scoped_key, fp)


def create_restore_revision(session: Session, edit_id: uuid.UUID, restored: dict, *, user_id: str,
                            idempotency_key: str | None, settings: Settings) -> tuple[Generation, bool]:
    """Create a new edit version with one previously removed source range restored."""
    target = get_edit(session, edit_id, user_id)
    if target.kind == "variant":
        raise AppError(ErrorCode.INVALID_REQUEST, "Variant footage cannot be restored here.", 422)
    root = _root_of(session, target)
    scoped_key = f"{user_id}:{idempotency_key}" if idempotency_key else None
    normalized = {
        "source": int(restored["source"]),
        "start": round(float(restored["start"]), 3),
        "end": round(float(restored["end"]), 3),
    }
    fp = fingerprint_obj({"edit": str(root.id), "restore": normalized})
    existing = _existing_by_key(session, scoped_key)
    if existing:
        return _replay(existing, fp), False
    if target.status != S.completed.value:
        raise AppError(ErrorCode.INVALID_REQUEST, "Wait for this version to finish before restoring footage.", 409)
    _guard(session, user_id)

    prior = list(session.scalars(select(Generation).where(
        Generation.parent_id == root.id, Generation.kind == "revision").order_by(Generation.revision_number)))
    restore_ranges: list[dict] = []
    for row in [root, *prior]:
        for item in (row.meta or {}).get("restore_ranges", []):
            if isinstance(item, dict) and {"source", "start", "end"}.issubset(item):
                restore_ranges.append({
                    "source": int(item["source"]),
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                })
    if normalized not in restore_ranges:
        restore_ranges.append(normalized)

    last = max([row.revision_number or 1 for row in [root, *prior]], default=1)
    gen = Generation(
        id=uuid.uuid4(), user_id=user_id, idempotency_key=scoped_key, prompt="Restore removed footage",
        pipeline=root.pipeline, status=S.queued.value, progress=0,
        duration_seconds_requested=root.duration_seconds_requested, aspect_ratio=root.aspect_ratio, style=None,
        voice_enabled=True, captions_enabled=True, quality_profile="standard",
        runtime_provider=settings.orchestrator_provider, kind="revision", project_id=root.project_id,
        parent_id=root.id, revision_number=last + 1, platform=root.platform,
        meta={
            "request_fingerprint": fp,
            "asset_ids": (root.meta or {}).get("asset_ids", []),
            "cta_text": (root.meta or {}).get("cta_text"),
            "duration_explicit": (root.meta or {}).get("duration_explicit", False),
            "restore_ranges": restore_ranges,
        },
    )
    return _persist(session, gen, scoped_key, fp)


def create_variants(session: Session, edit_id: uuid.UUID, count: int, strategy: str, *, user_id: str,
                    idempotency_key: str | None, settings: Settings) -> tuple[list[Generation], bool]:
    target = get_edit(session, edit_id, user_id)
    root = _root_of(session, target)
    if strategy not in ALLOWED_VARIANT_STRATEGIES:
        raise AppError(ErrorCode.INVALID_REQUEST, "Unknown variant strategy.", 422)
    if count > settings.max_variants_per_request:
        raise AppError(ErrorCode.INVALID_REQUEST, f"At most {settings.max_variants_per_request} variants per request.", 422)
    if strategy != "hooks" and count != 1:
        raise AppError(ErrorCode.INVALID_REQUEST, "A specific hook strategy produces one variant.", 422)

    fp = fingerprint_obj({"edit": str(root.id), "count": count, "strategy": strategy})
    scoped = f"{user_id}:{idempotency_key}" if idempotency_key else None
    first_key = f"{scoped}#0" if scoped else None
    existing = _existing_by_key(session, first_key)
    if existing:
        _replay(existing, fp)
        rows = list(session.scalars(select(Generation).where(Generation.parent_id == root.id, Generation.kind == "variant",
                                                             Generation.idempotency_key.like(f"{scoped}#%"))
                                    .order_by(Generation.created_at)))
        return rows, False

    already = session.scalar(select(func.count()).select_from(Generation).where(
        Generation.parent_id == root.id, Generation.kind == "variant")) or 0
    if already + count > settings.max_variants_per_edit:
        raise AppError(ErrorCode.INVALID_REQUEST, "This edit already has the maximum number of variants.", 422)
    _guard(session, user_id, adding=count)

    picks = DEFAULT_HOOK_STRATEGIES[:count] if strategy == "hooks" else [strategy]
    # rotate through strategies not yet used, so a second batch adds new directions
    used = set(session.scalars(select(Generation.variant_strategy).where(
        Generation.parent_id == root.id, Generation.kind == "variant")))
    if strategy == "hooks":
        pool = [s for s in DEFAULT_HOOK_STRATEGIES if s not in used] or list(DEFAULT_HOOK_STRATEGIES)
        picks = pool[:count]

    rows: list[Generation] = []
    for i, key in enumerate(picks):
        label, hook_text = HOOK_STRATEGIES[key]
        rows.append(Generation(
            id=uuid.uuid4(), user_id=user_id, idempotency_key=f"{scoped}#{i}" if scoped else None, prompt=root.prompt,
            pipeline=root.pipeline, status=S.queued.value, progress=0,
            duration_seconds_requested=root.duration_seconds_requested, aspect_ratio=root.aspect_ratio, style=None,
            voice_enabled=True, captions_enabled=True, quality_profile="standard",
            runtime_provider=settings.orchestrator_provider, kind="variant", project_id=root.project_id, parent_id=root.id,
            platform=root.platform, variant_strategy=key, variant_label=label,
            meta={"request_fingerprint": fp, "asset_ids": (root.meta or {}).get("asset_ids", []),
                  "cta_text": (root.meta or {}).get("cta_text"), "hook_text": hook_text,
                  "duration_explicit": (root.meta or {}).get("duration_explicit", False)},
        ))
    session.add_all(rows)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT, "Duplicate request.", 409)
    return rows, True


def list_variants(session: Session, edit_id: uuid.UUID, user_id: str) -> list[Generation]:
    root = _root_of(session, get_edit(session, edit_id, user_id))
    return list(session.scalars(select(Generation).where(Generation.parent_id == root.id, Generation.kind == "variant")
                                .order_by(Generation.created_at)))


def list_root_edits(session: Session, user_id: str, project_id: uuid.UUID | None, limit: int = 50) -> list[Generation]:
    stmt = select(Generation).where(Generation.user_id == user_id, Generation.kind == "edit")
    if project_id:
        stmt = stmt.where(Generation.project_id == project_id)
    return list(session.scalars(stmt.order_by(Generation.created_at.desc()).limit(limit)))


# --------------------------------------------------------------------------- worker helpers
def effective_instruction(session: Session, gen: Generation) -> str:
    """What the worker actually applies: original instruction + earlier revisions + this one."""
    if gen.kind == "revision" and gen.parent_id:
        root = session.get(Generation, gen.parent_id)
        prior = list(session.scalars(select(Generation).where(
            Generation.parent_id == gen.parent_id, Generation.kind == "revision",
            Generation.revision_number < (gen.revision_number or 0)).order_by(Generation.revision_number)))
        parts = [root.prompt if root else ""] + [p.prompt for p in prior] + [gen.prompt]
        return " ".join(x.strip() for x in parts if x).strip()
    if gen.kind == "variant" and gen.parent_id:
        root = session.get(Generation, gen.parent_id)
        return root.prompt if root else gen.prompt
    return gen.prompt


def source_assets(session: Session, gen: Generation) -> list[Asset]:
    ids = [uuid.UUID(i) for i in (gen.meta or {}).get("asset_ids", [])]
    rows = {a.id: a for a in session.scalars(select(Asset).where(Asset.id.in_(ids)))} if ids else {}
    return [rows[i] for i in ids if i in rows]


# --------------------------------------------------------------------------- output
def _version_out(g: Generation, storage: StorageService) -> VersionOut:
    done = g.status == S.completed.value
    return VersionOut(
        id=g.id, version=g.revision_number or 1, instruction=g.prompt, status=g.status,
        progress=100 if done else g.progress,
        output_url=storage.url_for(g.output_storage_key) if done and g.output_storage_key else None,
        thumbnail_url=storage.url_for(g.thumbnail_storage_key) if done and g.thumbnail_storage_key else None,
        kept_ranges=(g.meta or {}).get("kept_ranges", []),
        created_at=_aware(g.created_at))


def edit_out(session: Session, gen: Generation, storage: StorageService, *, with_versions: bool = True) -> EditOut:
    done = gen.status == S.completed.value
    error = None
    if gen.status == S.failed.value:
        code = gen.error_code or ErrorCode.GENERATION_FAILED.value
        error = GenerationError(code=code, message=client_message(code))
    stage = "complete" if done else gen.current_stage
    versions: list[VersionOut] = []
    if with_versions and gen.kind in ("edit", "revision"):
        root = gen if gen.kind == "edit" else session.get(Generation, gen.parent_id)
        if root is not None:
            revs = list(session.scalars(select(Generation).where(Generation.parent_id == root.id, Generation.kind == "revision")
                                        .order_by(Generation.revision_number)))
            versions = [_version_out(g, storage) for g in [root, *revs]]
    meta = gen.meta or {}
    duration = ((meta.get("output") or {}).get("duration_seconds"))
    return EditOut(
        id=gen.id, project_id=gen.project_id, kind=gen.kind, parent_id=gen.parent_id,
        version=gen.revision_number, status=gen.status, progress=100 if done else gen.progress, stage=stage,
        display_stage=display_stage(stage, gen.kind), instruction=gen.prompt, platform=gen.platform,
        aspect_ratio=gen.aspect_ratio, duration_target_seconds=gen.duration_seconds_requested, duration_seconds=duration,
        variant=VariantInfo(strategy=gen.variant_strategy, label=gen.variant_label) if gen.variant_strategy else None,
        output_url=storage.url_for(gen.output_storage_key) if done and gen.output_storage_key else None,
        thumbnail_url=storage.url_for(gen.thumbnail_storage_key) if done and gen.thumbnail_storage_key else None,
        warnings=[w for w in meta.get("warnings", []) if isinstance(w, str)][:10],
        insights={k: v for k, v in (meta.get("insights") or {}).items() if isinstance(v, (int, float, bool))},
        kept_ranges=meta.get("kept_ranges", []),
        error=error, versions=versions,
        created_at=_aware(gen.created_at), started_at=_aware(gen.started_at), completed_at=_aware(gen.completed_at),
        updated_at=_aware(gen.updated_at),
    )


_ = Any
