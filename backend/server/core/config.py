"""Typed application settings, loaded from the environment.

Secrets are ``SecretStr`` so they never appear in ``repr`` / logs by accident.
The API and worker share this module; each service simply receives a different
subset of environment variables (provider keys live on the worker only).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


def normalize_database_url(url: str) -> str:
    """Railway / Heroku style URLs use the bare `postgres(ql)://` scheme; SQLAlchemy needs the psycopg (v3) driver spelled out."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # `KEY=` lines in .env.example mean "unset"
        populate_by_name=True,
    )

    # --- general -----------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    enable_api_docs: bool | None = None  # default: on outside production
    cors_allowed_origins: list[str] = Field(default_factory=list)
    max_body_bytes: int = 64 * 1024

    # --- auth --------------------------------------------------------------
    auth_mode: Literal["dev_token", "device_session"] = "dev_token"
    dev_api_token: SecretStr | None = None
    device_auth_secret: SecretStr | None = None
    device_session_ttl_seconds: int = 365 * 24 * 60 * 60

    # --- data stores -------------------------------------------------------
    database_url: str = "sqlite+pysqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"

    # --- orchestration -----------------------------------------------------
    orchestrator_provider: Literal["claude_agent_sdk", "local_edit", "mock"] = "claude_agent_sdk"
    anthropic_api_key: SecretStr | None = None
    openmontage_dir: Path = BACKEND_DIR / "openmontage"
    openmontage_pipeline: str = "app-cinematic"
    max_job_budget_usd: float = 3.00  # provider spend cap (OpenMontage cost tracker)
    agent_model: str = "claude-sonnet-5"
    agent_max_turns: int = 200
    agent_max_llm_budget_usd: float = 2.00  # Claude token spend cap (SDK max_budget_usd)
    agent_max_continuations: int = 2
    agent_allow_web_search: bool = True
    agent_transcript_dir: Path = Path("/workspace/agent-logs")

    # --- worker ------------------------------------------------------------
    worker_concurrency: int = 1
    generation_soft_timeout_seconds: int = 2400
    generation_hard_timeout_seconds: int = 2700
    celery_visibility_timeout_seconds: int = 4200
    task_max_retries: int = 2
    cancel_poll_seconds: float = 3.0
    local_job_retention_hours: int = 24

    # --- storage -----------------------------------------------------------
    storage_backend: Literal["local", "r2", "s3"] = "local"  # r2 and s3 are the same S3-compatible client
    local_storage_path: Path = Path("/workspace/storage")
    # S3-compatible object storage: Cloudflare R2, Supabase Storage, AWS S3, Backblaze B2, ...
    # Generic S3_* names are preferred; the original R2_* names keep working.
    r2_endpoint_url: str | None = Field(default=None, validation_alias=AliasChoices("S3_ENDPOINT_URL", "R2_ENDPOINT_URL"))
    r2_access_key_id: SecretStr | None = Field(default=None, validation_alias=AliasChoices("S3_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"))
    r2_secret_access_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("S3_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"))
    r2_bucket: str | None = Field(default=None, validation_alias=AliasChoices("S3_BUCKET", "R2_BUCKET"))
    # set => public URLs (no expiry), unset => signed URLs
    r2_public_base_url: str | None = Field(default=None, validation_alias=AliasChoices("S3_PUBLIC_BASE_URL", "R2_PUBLIC_BASE_URL"))
    # R2 uses "auto". Supabase / AWS need the real region of the project/bucket (e.g. "us-east-1", "ap-south-1").
    r2_region: str = Field(default="auto", validation_alias=AliasChoices("S3_REGION", "R2_REGION"))
    # Supabase requires path-style URLs; Railway Buckets and AWS use virtual-hosted URLs.
    s3_addressing_style: Literal["path", "virtual", "auto"] = Field(
        default="path", validation_alias=AliasChoices("S3_ADDRESSING_STYLE", "R2_ADDRESSING_STYLE")
    )
    signed_url_ttl_seconds: int = 3600

    # --- limits ------------------------------------------------------------
    rate_limit_generations_per_minute: int = 10
    rate_limit_uploads_per_minute: int = 30
    max_upload_bytes_video: int = 500 * 1024 * 1024
    max_upload_bytes_image: int = 20 * 1024 * 1024
    presign_ttl_seconds: int = 900

    # --- OpenRouter (backend/worker only; NEVER shipped to a client) ------------
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_reasoning_model: str | None = None
    openrouter_vision_model: str | None = None
    openrouter_image_model: str | None = None
    openrouter_video_model: str | None = None
    # Editorial decisions (best-take selection). Any OpenRouter text model, e.g. a Qwen 3.x model id.
    openrouter_editing_model: str | None = None
    # Internal quality profiles -> model ids, e.g. {"ugc_broll": "vendor/model", "fast": "..."}.
    openrouter_video_profiles: dict[str, str] = Field(default_factory=dict)
    openrouter_timeout_seconds: float = 60.0
    video_poll_interval_seconds: float = 5.0
    video_poll_timeout_seconds: float = 900.0

    # --- editing product ---------------------------------------------------------
    local_edit_first: bool = True  # deterministic FFmpeg/OpenMontage edits before any LLM or generation
    enable_generative_broll: bool = False  # paid; off unless explicitly enabled
    max_broll_clips_per_edit: int = 2
    max_variants_per_request: int = 5
    max_variants_per_edit: int = 10
    max_assets_per_edit: int = 10
    transcribe_model: str = "base"  # faster-whisper size; pre-downloaded in the Docker image
    transcribe_language: str | None = None  # None = auto-detect
    takes_llm_enabled: bool = True  # let the editing model choose among the engine's candidate takes

    # --- smoke tests -------------------------------------------------------
    allow_paid_smoke_test: bool = False
    allow_paid_e2e: bool = False

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if self.generation_hard_timeout_seconds <= self.generation_soft_timeout_seconds:
            raise ValueError("GENERATION_HARD_TIMEOUT_SECONDS must exceed the soft timeout")
        if self.celery_visibility_timeout_seconds <= self.generation_hard_timeout_seconds:
            raise ValueError("CELERY_VISIBILITY_TIMEOUT_SECONDS must exceed the hard timeout")
        if self.uses_object_storage:
            missing = [
                name
                for name, val in (
                    ("S3_ENDPOINT_URL", self.r2_endpoint_url),
                    ("S3_ACCESS_KEY_ID", self.r2_access_key_id),
                    ("S3_SECRET_ACCESS_KEY", self.r2_secret_access_key),
                    ("S3_BUCKET", self.r2_bucket),
                )
                if not val
            ]
            if missing:
                raise ValueError(f"STORAGE_BACKEND={self.storage_backend} requires {', '.join(missing)} (R2_* names also accepted)")
        if self.is_production:
            if self.auth_mode == "dev_token":
                token = self.dev_api_token.get_secret_value() if self.dev_api_token else ""
                if len(token) < 24:
                    raise ValueError(
                        "production requires DEV_API_TOKEN (>= 24 chars) while AUTH_MODE=dev_token"
                    )
            else:
                secret = self.device_auth_secret.get_secret_value() if self.device_auth_secret else ""
                if len(secret) < 32:
                    raise ValueError(
                        "production requires DEVICE_AUTH_SECRET (>= 32 chars) while AUTH_MODE=device_session"
                    )
            if self.storage_backend == "local":
                # Allowed (e.g. a volume) but loudly discouraged; see README.
                pass
        return self

    @property
    def uses_object_storage(self) -> bool:
        return self.storage_backend in ("r2", "s3")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return not self.is_production

    @property
    def dev_token_value(self) -> str | None:
        return self.dev_api_token.get_secret_value() if self.dev_api_token else None

    @property
    def device_auth_secret_value(self) -> str | None:
        return self.device_auth_secret.get_secret_value() if self.device_auth_secret else None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
