"""SQLite connection and lifecycle management for the dashboard database.

The dashboard is the only reader and writer of this file. Nothing upstream depends on
it, so it can be deleted at any time; :meth:`DashboardDatabase.reset` and
:meth:`DashboardDatabase.prepare_rebuild` make that an ordinary operation rather than a
recovery procedure.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from dashboard.storage.migrations import LATEST_VERSION, apply_migrations, get_current_version

#: Side files SQLite creates in WAL mode; they must go with the database on reset.
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class DashboardDatabase:
    """A thin owner of one SQLite file.

    Connections are short-lived and always closed: the dashboard is a read-mostly UI and
    holding a connection open across Streamlit reruns would leak handles and keep the
    file locked on Windows.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    # -- connections ----------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """Open a configured connection. The caller owns closing it."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Connection context manager that commits on success and always closes."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- lifecycle ------------------------------------------------------------------

    def initialize(self) -> int:
        """Create or upgrade the schema. Safe to call repeatedly."""
        with self.session() as conn:
            return apply_migrations(conn)

    def reset(self) -> int:
        """Delete the database file (and WAL sidecars) and recreate an empty schema."""
        self.delete()
        return self.initialize()

    def delete(self) -> None:
        """Remove the database entirely. The upstream system is unaffected."""
        for suffix in ("", *_SIDECAR_SUFFIXES):
            path = Path(str(self.db_path) + suffix)
            path.unlink(missing_ok=True)

    def prepare_rebuild(self) -> int:
        """Clear dashboard-owned rows, keeping the schema, ready for re-ingestion.

        Used when historical runs are rebuilt from completed run artifacts on disk.
        """
        with self.session() as conn:
            if _table_exists(conn, "runs"):
                conn.execute("DELETE FROM runs")
        return self.schema_version() or self.initialize()

    # -- introspection ---------------------------------------------------------------

    def exists(self) -> bool:
        return self.db_path.is_file()

    def is_initialized(self) -> bool:
        """True when the file exists and carries the dashboard's run-history schema."""
        if not self.exists():
            return False
        try:
            with self.session() as conn:
                return _table_exists(conn, "runs")
        except sqlite3.Error:
            return False

    def schema_version(self) -> int | None:
        if not self.exists():
            return None
        try:
            with self.session() as conn:
                return get_current_version(conn)
        except sqlite3.Error:
            return None

    def needs_migration(self) -> bool:
        version = self.schema_version()
        return version is None or version < LATEST_VERSION


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None
