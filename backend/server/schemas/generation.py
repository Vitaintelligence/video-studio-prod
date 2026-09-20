"""Public API schemas. No OpenMontage terminology, paths or provider details."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_DURATIONS = (15, 30, 45, 60)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_STYLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,39}$")

AspectRatio = Literal["9:16", "1:1", "16:9"]
Quality = Literal["standard", "cinematic"]
StatusLiteral = Literal["queued", "starting", "running", "completed", "failed", "cancel_requested", "cancelled"]


class GenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=10, max_length=2000)
    duration_seconds: Literal[15, 30, 45, 60] = 30
    aspect_ratio: AspectRatio = "9:16"
    style: str | None = Field(default=None, max_length=40)
    pipeline: str = Field(default="app-cinematic", min_length=1, max_length=64)
    voice_enabled: bool = True
    captions_enabled: bool = True
    quality: Quality = "standard"

    @field_validator("prompt")
    @classmethod
    def _clean_prompt(cls, v: str) -> str:
        v = _CONTROL_CHARS.sub("", v).strip()
        if len(v) < 10:
            raise ValueError("prompt is too short")
        return v

    @field_validator("style")
    @classmethod
    def _clean_style(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not _STYLE_RE.match(v):
            raise ValueError("style may only contain letters, numbers, spaces, '-' and '_'")
        return v


class GenerationError(BaseModel):
    code: str
    message: str


class GenerationAccepted(BaseModel):
    id: uuid.UUID
    status: StatusLiteral
    progress: int
    current_stage: str | None
    created_at: datetime
    poll_url: str


class GenerationOut(BaseModel):
    id: uuid.UUID
    status: StatusLiteral
    progress: int
    current_stage: str | None
    display_stage: str | None
    duration_seconds: int
    aspect_ratio: str
    style: str | None
    prompt: str
    voice_enabled: bool
    captions_enabled: bool
    quality: str
    output_url: str | None = None
    thumbnail_url: str | None = None
    error: GenerationError | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class GenerationList(BaseModel):
    items: list[GenerationOut]
    next_cursor: str | None = None
