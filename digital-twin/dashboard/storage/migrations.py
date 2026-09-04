"""Forward-only schema migrations for the dashboard database.

Adding a schema change means appending a new integer key to :data:`MIGRATIONS` with the
statements that move the database from ``version - 1`` to ``version``. Existing entries
are never edited, so an older dashboard database upgrades cleanly.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from dashboard.storage.schema import INITIAL_SCHEMA

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: INITIAL_SCHEMA,
}

LATEST_VERSION = max(MIGRATIONS)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def get_current_version(conn: sqlite3.Connection) -> int | None:
    """Return the applied schema version, or None for an empty/unmanaged database."""
    try:
        if not _has_table(conn, "schema_versions"):
            return None
        row = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row and row[0] is not None else None


def apply_migrations(conn: sqlite3.Connection, current_version: int | None = None) -> int:
    """Bring the connection's database up to :data:`LATEST_VERSION`.

    Idempotent: re-running against an up-to-date database is a no-op.
    """
    if current_version is None:
        current_version = get_current_version(conn)
    start = 0 if current_version is None else current_version
    if start >= LATEST_VERSION:
        return start

    applied_at = datetime.now(timezone.utc).isoformat()
    for version in range(start + 1, LATEST_VERSION + 1):
        for statement in MIGRATIONS.get(version, ()):
            conn.execute(statement)
        conn.execute(
            "INSERT OR REPLACE INTO schema_versions (version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
    conn.commit()
    return LATEST_VERSION
