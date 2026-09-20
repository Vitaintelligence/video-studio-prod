"""Typed application settings, loaded from the environment.

Secrets are ``SecretStr`` so they never appear in ``repr`` / logs by accident.
The API and worker share this module; each service simply receives a different
subset of environment variables (provider keys live on the worker only).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # `KEY=` lines in .env.example mean "unset"
    )

    # --- general -----------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    enable_api_docs: bool | None = None  # default: on outside production
    cors_allowed_origins: list[str] = Field(default_factory=list)
    max_body_bytes: int = 64 * 1024

    # --- auth --------------------------------------------------------------
    auth_mode: Literal["dev_token"] = "dev_token"
    dev_api_token: SecretStr | None = None

    # --- data stores -------------------------------------------------------
    database_url: str = "sqlite+pysqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"

    # --- orchestration -----------------------------------------------------
    orchestrator_provider: Literal["claude_agent_sdk", "mock"] = "claude_agent_sdk"
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
    storage_backend: Literal["local", "r2"] = "local"
    local_storage_path: Path = Path("/workspace/storage")
    r2_endpoint_url: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_public_base_url: str | None = None  # set => public URLs, unset => signed URLs
    r2_region: str = "auto"
    signed_url_ttl_seconds: int = 3600

    # --- limits ------------------------------------------------------------
    rate_limit_generations_per_minute: int = 10
    rate_limit_uploads_per_minute: int = 30
    max_upload_bytes_video: int = 500 * 1024 * 1024
    max_upload_bytes_image: int = 20 * 1024 * 1024
    presign_ttl_seconds: int = 900

    # --- smoke tests -------------------------------------------------------
    allow_paid_smoke_test: bool = False

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Railway / Heroku style URLs use the bare `postgres(ql)://` scheme;
        # SQLAlchemy needs the psycopg (v3) driver spelled out.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if self.generation_hard_timeout_seconds <= self.generation_soft_timeout_seconds:
            raise ValueError("GENERATION_HARD_TIMEOUT_SECONDS must exceed the soft timeout")
        if self.celery_visibility_timeout_seconds <= self.generation_hard_timeout_seconds:
            raise ValueError("CELERY_VISIBILITY_TIMEOUT_SECONDS must exceed the hard timeout")
        if self.storage_backend == "r2":
            missing = [
                name
                for name, val in (
                    ("R2_ENDPOINT_URL", self.r2_endpoint_url),
                    ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
                    ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
                    ("R2_BUCKET", self.r2_bucket),
                )
                if not val
            ]
            if missing:
                raise ValueError(f"STORAGE_BACKEND=r2 requires {', '.join(missing)}")
        if self.is_production:
            token = self.dev_api_token.get_secret_value() if self.dev_api_token else ""
            if len(token) < 24:
                raise ValueError(
                    "production requires DEV_API_TOKEN (>= 24 chars) while AUTH_MODE=dev_token"
                )
            if self.storage_backend == "local":
                # Allowed (e.g. a volume) but loudly discouraged; see README.
                pass
        return self

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
