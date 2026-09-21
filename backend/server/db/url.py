"""Database URL helpers shared by the application and Alembic."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url


def ensure_sqlite_parent_directory(url: str) -> None:
    """Create the parent directory for a file-backed SQLite database.

    SQLite creates the database file, but it does not create missing parent
    directories.  This is intentionally a no-op for non-SQLite URLs, in-memory
    databases, and SQLite URI filenames (whose semantics are handled by the
    driver).
    """
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return

    database = parsed.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return

    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
