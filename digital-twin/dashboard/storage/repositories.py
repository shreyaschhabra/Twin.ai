"""Repository access to the dashboard database.

All SQL lives here. Views and orchestration talk to repositories, never to sqlite3
directly, so the schema can grow without touching the UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlite3 import Row

from dashboard.domain.run import Run, RunStatus
from dashboard.storage.database import DashboardDatabase

_RUN_COLUMNS = (
    "run_id",
    "production_day",
    "status",
    "scenario_name",
    "scenario_reference",
    "scenario_description",
    "multiplier",
    "seed",
    "duration_ms",
    "factory_path",
    "factory_fingerprint",
    "artifact_path",
    "predictions_path",
    "started_at",
    "completed_at",
    "is_demo",
    "metadata_json",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRepository:
    """Persisted history of production runs."""

    def __init__(self, db: DashboardDatabase):
        self.db = db

    # -- writes ----------------------------------------------------------------------

    def _values(self, run: Run) -> tuple:
        return (
            run.run_id,
            run.production_day,
            RunStatus.coerce(run.status).value,
            run.scenario_name,
            run.scenario_reference,
            run.scenario_description,
            float(run.multiplier),
            run.seed,
            run.duration_ms,
            str(run.factory_path),
            run.factory_fingerprint,
            str(run.artifact_path) if run.artifact_path else None,
            str(run.predictions_path) if run.predictions_path else None,
            run.started_at,
            run.completed_at,
            1 if run.is_demo else 0,
            run.metadata_json,
        )

    def insert_run(self, run: Run) -> Run:
        """Insert a new run. Raises sqlite3.IntegrityError on a duplicate id or day."""
        now = _now()
        placeholders = ", ".join("?" for _ in _RUN_COLUMNS)
        with self.db.session() as conn:
            conn.execute(
                f"INSERT INTO runs ({', '.join(_RUN_COLUMNS)}, created_at, updated_at) "
                f"VALUES ({placeholders}, ?, ?)",
                (*self._values(run), now, now),
            )
        return run

    def upsert_run(self, run: Run) -> Run:
        """Insert, or replace the stored row for an existing ``run_id``."""
        now = _now()
        assignments = ", ".join(f"{column} = ?" for column in _RUN_COLUMNS[1:])
        with self.db.session() as conn:
            existing = conn.execute(
                "SELECT run_id FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone()
            if existing is None:
                placeholders = ", ".join("?" for _ in _RUN_COLUMNS)
                conn.execute(
                    f"INSERT INTO runs ({', '.join(_RUN_COLUMNS)}, created_at, updated_at) "
                    f"VALUES ({placeholders}, ?, ?)",
                    (*self._values(run), now, now),
                )
            else:
                conn.execute(
                    f"UPDATE runs SET {assignments}, updated_at = ? WHERE run_id = ?",
                    (*self._values(run)[1:], now, run.run_id),
                )
        return run

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        assignments = ["status = ?", "updated_at = ?"]
        values: list[object] = [RunStatus.coerce(status).value, _now()]
        if started_at is not None:
            assignments.insert(1, "started_at = ?")
            values.insert(1, started_at)
        if completed_at is not None:
            assignments.insert(-1, "completed_at = ?")
            values.insert(-1, completed_at)
        with self.db.session() as conn:
            conn.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
                (*values, run_id),
            )

    def delete_run(self, run_id: str) -> None:
        with self.db.session() as conn:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    def delete_all(self) -> None:
        """Clear history ahead of a rebuild from completed run artifacts."""
        with self.db.session() as conn:
            conn.execute("DELETE FROM runs")

    # -- reads -----------------------------------------------------------------------

    def get_run(self, run_id: str) -> Run | None:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, limit: int = 100, offset: int = 0) -> list[Run]:
        """Most recent production day first."""
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY production_day DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def latest_run(self) -> Run | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM runs ORDER BY production_day DESC LIMIT 1"
            ).fetchone()
        return _row_to_run(row) if row else None

    def latest_completed_run(self) -> Run | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE status = ? ORDER BY production_day DESC LIMIT 1",
                (RunStatus.COMPLETED.value,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def count_runs(self) -> int:
        with self.db.session() as conn:
            row = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
        return int(row[0]) if row else 0

    def next_production_day(self) -> int:
        with self.db.session() as conn:
            row = conn.execute("SELECT MAX(production_day) FROM runs").fetchone()
        return int(row[0]) + 1 if row and row[0] is not None else 1

    def find_by_artifact_path(self, artifact_path: str) -> Run | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE artifact_path = ? LIMIT 1", (str(artifact_path),)
            ).fetchone()
        return _row_to_run(row) if row else None


def _row_to_run(row: Row) -> Run:
    return Run(
        run_id=row["run_id"],
        production_day=row["production_day"],
        status=RunStatus.coerce(row["status"]),
        scenario_name=row["scenario_name"],
        scenario_reference=row["scenario_reference"],
        scenario_description=row["scenario_description"],
        multiplier=row["multiplier"],
        seed=row["seed"],
        duration_ms=row["duration_ms"],
        factory_path=row["factory_path"],
        factory_fingerprint=row["factory_fingerprint"],
        artifact_path=row["artifact_path"],
        predictions_path=row["predictions_path"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        is_demo=bool(row["is_demo"]),
        metadata=Run.from_metadata_json(row["metadata_json"]),
    )
