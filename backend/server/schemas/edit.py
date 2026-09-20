"""Product-facing schemas for projects, assets and edits. No engine terminology."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.schemas.generation import AspectRatio, GenerationError, StatusLiteral

Platform = Literal["tiktok", "meta", "reels", "shorts"]
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(v: str) -> str:
    return _CTRL.sub("", v).strip()


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        v = _clean(v)
        if not v:
            raise ValueError("name is required")
        return v


class AssetOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    filename: str
    content_type: str
    purpose: str
    size_bytes: int | None
    status: Literal["pending", "uploaded"]
    created_at: datetime


class VersionOut(BaseModel):
    """One version of an edit: the original (version 1) or a prompt-to-edit revision."""

    id: uuid.UUID
    version: int
    instruction: str
    status: StatusLiteral
    progress: int
    output_url: str | None = None
    thumbnail_url: str | None = None
    created_at: datetime


class VariantInfo(BaseModel):
    strategy: str
    label: str


class EditCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID | None = None
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    instruction: str = Field(min_length=8, max_length=2000)
    platform: Platform = "tiktok"
    aspect_ratio: AspectRatio = "9:16"
    duration_target_seconds: int | None = Field(default=None, ge=5, le=90)
    cta_text: str | None = Field(default=None, max_length=60)
    brand_kit_id: uuid.UUID | None = None

    @field_validator("instruction")
    @classmethod
    def _i(cls, v: str) -> str:
        v = _clean(v)
        if len(v) < 8:
            raise ValueError("instruction is too short")
        return v


class InstructionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=4, max_length=2000)

    @field_validator("instruction")
    @classmethod
    def _i(cls, v: str) -> str:
        v = _clean(v)
        if len(v) < 4:
            raise ValueError("instruction is too short")
        return v


class VariantsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(default=3, ge=1, le=5)
    strategy: str = Field(default="hooks", max_length=32)


class EditAccepted(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    status: StatusLiteral
    progress: int
    poll_url: str


class EditOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    kind: Literal["edit", "revision", "variant"]
    parent_id: uuid.UUID | None
    version: int | None
    status: StatusLiteral
    progress: int
    stage: str | None
    display_stage: str | None
    instruction: str
    platform: str | None
    aspect_ratio: str
    duration_target_seconds: int
    duration_seconds: float | None = None
    variant: VariantInfo | None = None
    output_url: str | None = None
    thumbnail_url: str | None = None
    warnings: list[str] = Field(default_factory=list)
    insights: dict[str, float | int | bool] = Field(default_factory=dict)  # e.g. retakes_removed
    error: GenerationError | None = None
    versions: list[VersionOut] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class EditList(BaseModel):
    items: list[EditOut]


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
    edit_count: int = 0
    latest_edit: EditOut | None = None


class ProjectDetail(ProjectOut):
    assets: list[AssetOut] = Field(default_factory=list)
    edits: list[EditOut] = Field(default_factory=list)


class ProjectList(BaseModel):
    items: list[ProjectOut]
