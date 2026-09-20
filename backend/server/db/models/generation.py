from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from server.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationStatus(str, enum.Enum):
    queued = "queued"
    starting = "starting"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"


TERMINAL_STATUSES = {GenerationStatus.completed, GenerationStatus.failed, GenerationStatus.cancelled}
ACTIVE_STATUSES = {GenerationStatus.starting, GenerationStatus.running}


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=GenerationStatus.queued.value)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    duration_seconds_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False)
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    captions_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")

    project_path: Mapped[str | None] = mapped_column(String(512), nullable=True)  # internal only
    output_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized

    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    runtime_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # --- edit product fields (an "edit" is a generation row; see services/edit_service.py) ---
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="generation", server_default="generation")  # generation|edit|revision|variant
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # revision/variant -> root edit
    revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    variant_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    variant_label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Column is called "metadata" but that name is reserved on declarative classes.
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_generations_user_created", "user_id", "created_at"),
        Index("ix_generations_status_created", "status", "created_at"),
        Index("ix_generations_created_at", "created_at"),
        Index("ix_generations_project", "project_id", "created_at"),
        Index("ix_generations_parent", "parent_id", "created_at"),
    )
