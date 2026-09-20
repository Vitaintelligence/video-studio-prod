"""Migrations, OpenMontage registry preflight, upstream-integrity checks."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_and_downgrade(tmp_path):
    from alembic import command
    from alembic.config import Config

    url = f"sqlite+pysqlite:///{tmp_path / 'mig.db'}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(url))
    cols = {c["name"] for c in insp.get_columns("generations")}
    required = {
        "id", "user_id", "idempotency_key", "prompt", "pipeline", "status", "current_stage", "progress",
        "duration_seconds_requested", "aspect_ratio", "style", "voice_enabled", "captions_enabled", "quality_profile",
        "project_path", "output_storage_key", "output_url", "thumbnail_storage_key", "thumbnail_url", "error_code",
        "error_message", "estimated_cost_usd", "actual_cost_usd", "runtime_provider", "created_at", "started_at",
        "completed_at", "updated_at", "metadata",
    }
    assert required <= cols
    idx = {i["name"] for i in insp.get_indexes("generations")}
    assert {"ix_generations_user_created", "ix_generations_status_created", "ix_generations_created_at"} <= idx
    assert any(u["column_names"] == ["idempotency_key"] for u in insp.get_unique_constraints("generations"))
    command.downgrade(cfg, "base")
    assert "generations" not in inspect(create_engine(url)).get_table_names()


def test_models_and_migration_agree(tmp_path):
    """Autogenerate should find nothing to change once the migration is applied."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic import command
    from alembic.config import Config

    from server.db import models  # noqa: F401
    from server.db.base import Base

    url = f"sqlite+pysqlite:///{tmp_path / 'drift.db'}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_openmontage_registry_preflight_real_engine():
    """Runs the real registry (discover + provider_menu_summary) in the real engine dir."""
    from server.core.config import Settings
    from server.services.capabilities import normalize, run_probe

    settings = Settings(_env_file=None, openmontage_dir=BACKEND / "openmontage", orchestrator_provider="mock")
    raw = run_probe(settings, timeout=240)
    assert raw["registry_ok"] is True and raw["tool_count"] > 50
    assert "video_generation" in raw["capabilities"] and "tts" in raw["capabilities"]
    assert raw["composition_runtimes"]["ffmpeg"] in (True, False)

    text = json.dumps(raw)
    assert "install" not in text.lower()  # no install instructions / env-var names leak through the probe

    doc = normalize(raw, settings)
    assert set(doc) >= {"status", "generation_available", "pipelines", "features"}
    assert doc["pipelines"][0]["id"] == "app-cinematic"


def test_app_pipeline_manifest_is_headless_and_valid():
    import yaml

    m = yaml.safe_load((BACKEND / "openmontage" / "pipeline_defs" / "app-cinematic.yaml").read_text(encoding="utf-8"))
    assert [s["name"] for s in m["stages"]] == ["research", "proposal", "script", "scene_plan", "assets", "edit", "compose"]
    assert all(s["human_approval_default"] is False for s in m["stages"])
    assert all(s["checkpoint_required"] for s in m["stages"])  # QA/checkpoints are NOT removed
    skills = [s["skill"] for s in m["stages"]]
    for rel in skills:
        assert (BACKEND / "openmontage" / "skills" / f"{rel}.md").is_file(), rel


def test_upstream_provenance_and_license_preserved():
    assert (BACKEND / "openmontage" / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    doc = (BACKEND / "OPENMONTAGE_UPSTREAM.md").read_text(encoding="utf-8")
    assert "github.com/calesthio/OpenMontage" in doc and "08e2151fa02de28a5d6a312b3d575692bf147ad7" in doc
    assert (BACKEND.parent / "THIRD_PARTY_NOTICES.md").is_file()


def test_env_example_has_required_keys_no_secrets_and_only_real_provider_vars():
    import re

    def names(p: Path) -> set[str]:
        return {m.group(1) for line in p.read_text(encoding="utf-8").splitlines()
                if (m := re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=", line.strip()))}

    mine = BACKEND / ".env.example"
    text = mine.read_text(encoding="utf-8")
    required = {"APP_ENV", "LOG_LEVEL", "AUTH_MODE", "DEV_API_TOKEN", "DATABASE_URL", "REDIS_URL", "ORCHESTRATOR_PROVIDER",
                "ANTHROPIC_API_KEY", "OPENMONTAGE_PIPELINE", "MAX_JOB_BUDGET_USD", "WORKER_CONCURRENCY",
                "GENERATION_SOFT_TIMEOUT_SECONDS", "GENERATION_HARD_TIMEOUT_SECONDS", "STORAGE_BACKEND", "LOCAL_STORAGE_PATH",
                "LOCAL_JOB_RETENTION_HOURS", "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET",
                "S3_ADDRESSING_STYLE", "S3_PUBLIC_BASE_URL"}
    assert required <= names(mine)
    upstream = names(BACKEND / "openmontage" / ".env.example")
    assert {"FAL_KEY", "ELEVENLABS_API_KEY", "KLING_API_KEY", "PEXELS_API_KEY"} <= upstream & names(mine)
    # every non-empty assignment in the template must be a harmless default, never a credential
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]+)=(.+)$", line)
        if m and re.search(r"KEY|SECRET|TOKEN", m.group(1)):
            assert m.group(2).strip() == "", line
    assert "MAX_JOB_BUDGET_USD=3.00" in text


def test_probe_timeout_degrades_instead_of_raising(env):
    from server.services.capabilities import normalize, run_probe

    raw = run_probe(env["settings"], timeout=0.001)  # engine dir in `env` is a stub; either way it must not raise
    assert raw["registry_ok"] is False
    doc = normalize(raw, env["settings"])
    assert doc["status"] == "degraded" and doc["generation_available"] is False


def test_migrations_run_without_any_other_app_configuration(tmp_path):
    """Regression (Railway): `alembic upgrade head` failed because Settings validation demanded R2 credentials.
    Migrations must work with DATABASE_URL alone, even when storage/auth settings are incomplete or invalid,
    and must create a missing parent directory for a file-backed SQLite database."""
    import os
    import subprocess
    import sys

    database = tmp_path / "missing" / "parent" / "m.db"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("R2_", "DEV_API", "STORAGE", "APP_ENV", "DATABASE"))}
    env.update({"APP_ENV": "production", "STORAGE_BACKEND": "r2", "DATABASE_URL": f"sqlite:///{database.as_posix()}"})
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "generations" in inspect(create_engine(f"sqlite:///{database.as_posix()}")).get_table_names()


def test_application_engine_creates_sqlite_parent_directory(tmp_path, monkeypatch):
    from server.core.config import reset_settings_cache
    from server.db.session import get_engine, reset_engine_cache

    database = tmp_path / "missing" / "application" / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database.as_posix()}")
    reset_settings_cache()
    reset_engine_cache()
    try:
        with get_engine().connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        assert database.is_file()
    finally:
        reset_engine_cache()
        reset_settings_cache()


def test_postgres_url_variants_are_normalized():
    from server.core.config import normalize_database_url

    assert normalize_database_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"
