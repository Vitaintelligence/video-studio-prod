"""Server-side pipeline whitelist and stage vocabulary.

Only pipelines listed in ``APP_PIPELINES`` may be requested by clients. Each one
maps to an OpenMontage manifest that has been verified to run headless (no
human approval gates). The manifest is read straight from disk so the API
process does not need to import the OpenMontage engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from server.core.config import get_settings


@dataclass(frozen=True)
class PipelineInfo:
    id: str
    manifest: str  # file stem under openmontage/pipeline_defs/
    label: str


APP_PIPELINES: dict[str, PipelineInfo] = {
    "app-cinematic": PipelineInfo("app-cinematic", "app-cinematic", "Cinematic text-to-video"),
}

# Friendly, client-safe stage labels. Anything unknown collapses to a neutral label.
DISPLAY_STAGES: dict[str, str] = {
    "queued": "Waiting in line",
    "starting": "Getting ready",
    "research": "Preparing your video",
    "proposal": "Planning your video",
    "script": "Writing your story",
    "scene_plan": "Planning scenes",
    "assets": "Creating visuals",
    "edit": "Editing your video",
    "compose": "Finalizing",
    "finalizing": "Finalizing",
    "uploading": "Finalizing",
    "complete": "Ready",
}
DEFAULT_DISPLAY_STAGE = "Working on your video"


# Edit jobs (footage in, video out) use their own consumer wording. Covers both the deterministic
# editor's stages and the agent pipeline's stage names.
EDIT_DISPLAY_STAGES: dict[str, str] = {
    "queued": "Waiting in line",
    "starting": "Getting ready",
    "ingest": "Understanding footage",
    "research": "Understanding footage",
    "analyze": "Finding strongest moments",
    "proposal": "Finding strongest moments",
    "script": "Finding strongest moments",
    "plan": "Building your edit",
    "scene_plan": "Building your edit",
    "broll": "Adding B-roll",
    "assets": "Adding B-roll",
    "edit": "Building your edit",
    "captions": "Adding captions",
    "render": "Finalizing",
    "compose": "Finalizing",
    "finalizing": "Finalizing",
    "uploading": "Finalizing",
    "complete": "Ready",
}
EDIT_KINDS = ("edit", "revision", "variant")


def display_stage(stage: str | None, kind: str = "generation") -> str | None:
    if stage is None:
        return None
    table = EDIT_DISPLAY_STAGES if kind in EDIT_KINDS else DISPLAY_STAGES
    return table.get(stage, DEFAULT_DISPLAY_STAGE)


def get_pipeline(pipeline_id: str) -> PipelineInfo | None:
    return APP_PIPELINES.get(pipeline_id)


def manifest_path(pipeline_id: str) -> Path:
    info = APP_PIPELINES[pipeline_id]
    return get_settings().openmontage_dir / "pipeline_defs" / f"{info.manifest}.yaml"


@lru_cache(maxsize=16)
def _stage_order_cached(path: str, mtime: float) -> tuple[str, ...]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return tuple(stage["name"] for stage in data["stages"])


def stage_order(pipeline_id: str) -> list[str]:
    path = manifest_path(pipeline_id)
    return list(_stage_order_cached(str(path), path.stat().st_mtime))


def pipeline_manifest_exists(pipeline_id: str) -> bool:
    return pipeline_id in APP_PIPELINES and manifest_path(pipeline_id).is_file()


def enabled_pipelines() -> list[str]:
    return [pid for pid in APP_PIPELINES if pipeline_manifest_exists(pid)]
