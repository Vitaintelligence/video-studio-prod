from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import os

from server.core.config import normalize_database_url
from server.db.base import Base
from server.db import models  # noqa: F401  (register tables)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Migrations need ONLY the database URL. They must not construct the full app Settings, whose validation
    # (storage credentials, API token, ...) is irrelevant here and would block a deploy for unrelated reasons.
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL") or "sqlite+pysqlite:///./dev.db"
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
