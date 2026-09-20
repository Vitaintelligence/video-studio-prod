from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UploadPurpose = Literal["reference", "source_video"]

ALLOWED_UPLOAD_TYPES: dict[str, str] = {
    "video/mp4": "video",
    "video/x-m4v": "video",
    "video/quicktime": "video",
    "image/jpeg": "image",
    "image/png": "image",
    "image/heic": "image",
}
PURPOSE_KINDS: dict[str, set[str]] = {
    "reference": {"video", "image"},
    "source_video": {"video"},
}


class PresignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=3, max_length=100)
    purpose: UploadPurpose
    size_bytes: int | None = Field(default=None, gt=0)
    project_id: uuid.UUID | None = None


class PresignResponse(BaseModel):
    upload_id: str
    asset_id: str
    method: str
    url: str
    headers: dict[str, str]
    key: str
    expires_in: int
    max_bytes: int


class HealthOut(BaseModel):
    status: str


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, str]


class CapabilitiesOut(BaseModel):
    status: str
    generation_available: bool
    editing: bool = False
    ai_broll: bool = False
    video_generation: bool = False
    variants: bool = False
    revisions: bool = False
    best_takes: bool = False
    takes_llm: bool = False
    pipelines: list[dict]
    features: dict[str, bool]
    limits: dict
