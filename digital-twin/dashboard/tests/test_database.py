"""SQLite foundation tests: lifecycle, migrations, and the run repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dashboard.domain.run import Run, RunStatus
from dashboard.storage.database import DashboardDatabase
from dashboard.storage.migrations import LATEST_VERSION, apply_migrations, get_current_version
from dashboard.storage.repositories import RunRepository


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "dashboard.db"


@pytest.fixture
def db(db_path: Path) -> DashboardDatabase:
    database = DashboardDatabase(db_path)
    database.initialize()
    return database


@pytest.fixture
def repo(db: DashboardDatabase) -> RunRepository:
    return RunRepository(db)


def _run(run_id: str = "run_0001", production_day: int = 1, **overrides) -> Run:
    values = {
        "run_id": run_id,
        "production_day": production_day,
        "status": RunStatus.COMPLETED,
        "scenario_name": "scenario_0001",
        "scenario_reference": "/runs/run_0001",
        "scenario_description": "seed 42, 8.0h simulated",
        "multiplier": 60.0,
        "seed": 42,
        "duration_ms": 28_800_000,
        "factory_path": "/config/factory.json",
        "factory_fingerprint": "abc123",
        "artifact_path": f"/runs/{run_id}",
        "predictions_path": f"/runtime_output/{run_id}",
        "started_at": "2026-08-30T10:00:00+00:00",
        "completed_at": "2026-08-30T10:05:00+00:00",
        "is_demo": False,
        "metadata": {"units_created": 420},
    }
    values.update(overrides)
    return Run(**values)


class TestLifecycle:
    def test_initialize_creates_file_and_schema(self, db_path: Path):
        database = DashboardDatabase(db_path)
        assert not database.exists()
        assert database.initialize() == LATEST_VERSION
        assert database.exists()
        assert database.is_initialized()

    def test_initialize_creates_parent_directories(self, tmp_path: Path):
        database = DashboardDatabase(tmp_path / "a" / "b" / "dashboard.db")
        database.initialize()
        assert database.exists()

    def test_not_initialized_before_init(self, db_path: Path):
        assert DashboardDatabase(db_path).is_initialized() is False

    def test_schema_version_is_none_before_init(self, db_path: Path):
        assert DashboardDatabase(db_path).schema_version() is None

    def test_initialize_is_idempotent(self, db: DashboardDatabase):
        assert db.initialize() == LATEST_VERSION
        assert db.initialize() == LATEST_VERSION
        assert db.schema_version() == LATEST_VERSION

    def test_needs_migration(self, db_path: Path):
        database = DashboardDatabase(db_path)
        assert database.needs_migration() is True
        database.initialize()
        assert database.needs_migration() is False

    def test_reset_empties_history(self, repo: RunRepository, db: DashboardDatabase):
        repo.insert_run(_run())
        assert repo.count_runs() == 1
        db.reset()
        assert db.is_initialized()
        assert repo.count_runs() == 0

    def test_delete_removes_the_file_and_sidecars(self, db: DashboardDatabase):
        db.delete()
        assert not db.exists()
        assert not Path(str(db.db_path) + "-wal").exists()

    def test_delete_then_initialize_recovers(self, db: DashboardDatabase):
        db.delete()
        db.initialize()
        assert db.is_initialized()

    def test_prepare_rebuild_keeps_schema_and_clears_rows(
        self, repo: RunRepository, db: DashboardDatabase
    ):
        repo.insert_run(_run())
        db.prepare_rebuild()
        assert db.is_initialized()
        assert repo.count_runs() == 0

    def test_sessions_do_not_leak_connections(self, db: DashboardDatabase):
        for _ in range(60):
            with db.session() as conn:
                conn.execute("SELECT 1")
        assert db.is_initialized()

    def test_session_rolls_back_on_error(self, repo: RunRepository, db: DashboardDatabase):
        with pytest.raises(RuntimeError):
            with db.session() as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, production_day, factory_path, created_at, "
                    "updated_at) VALUES ('x', 1, 'f', 'now', 'now')"
                )
                raise RuntimeError("boom")
        assert repo.count_runs() == 0


class TestMigrations:
    def test_get_current_version_on_empty_database(self, tmp_path: Path):
        conn = sqlite3.connect(tmp_path / "empty.db")
        try:
            assert get_current_version(conn) is None
        finally:
            conn.close()

    def test_apply_migrations_is_idempotent(self, tmp_path: Path):
        conn = sqlite3.connect(tmp_path / "m.db")
        try:
            assert apply_migrations(conn) == LATEST_VERSION
            assert apply_migrations(conn) == LATEST_VERSION
        finally:
            conn.close()


class TestRunRepository:
    def test_insert_and_read_back(self, repo: RunRepository):
        repo.insert_run(_run())
        fetched = repo.get_run("run_0001")
        assert fetched is not None
        assert fetched.production_day == 1
        assert fetched.scenario_name == "scenario_0001"
        assert fetched.seed == 42
        assert fetched.factory_fingerprint == "abc123"
        assert fetched.metadata == {"units_created": 420}

    def test_get_missing_returns_none(self, repo: RunRepository):
        assert repo.get_run("nope") is None

    def test_duplicate_production_day_is_rejected(self, repo: RunRepository):
        repo.insert_run(_run("run_a", 1))
        with pytest.raises(sqlite3.IntegrityError):
            repo.insert_run(_run("run_b", 1))

    def test_upsert_updates_in_place(self, repo: RunRepository):
        repo.upsert_run(_run(status=RunStatus.PENDING))
        repo.upsert_run(_run(status=RunStatus.COMPLETED, scenario_name="scenario_0002"))
        assert repo.count_runs() == 1
        run = repo.get_run("run_0001")
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.scenario_name == "scenario_0002"

    def test_list_runs_newest_day_first(self, repo: RunRepository):
        for day in (1, 2, 3):
            repo.insert_run(_run(f"run_{day:04d}", day))
        assert [run.production_day for run in repo.list_runs()] == [3, 2, 1]

    def test_list_runs_honours_limit_and_offset(self, repo: RunRepository):
        for day in range(1, 6):
            repo.insert_run(_run(f"run_{day:04d}", day))
        assert len(repo.list_runs(limit=2)) == 2
        assert repo.list_runs(limit=1, offset=1)[0].production_day == 4

    def test_latest_run(self, repo: RunRepository):
        assert repo.latest_run() is None
        repo.insert_run(_run("run_0001", 1))
        repo.insert_run(_run("run_0002", 2))
        latest = repo.latest_run()
        assert latest is not None and latest.run_id == "run_0002"

    def test_latest_completed_run_skips_pending(self, repo: RunRepository):
        repo.insert_run(_run("run_0001", 1, status=RunStatus.COMPLETED))
        repo.insert_run(_run("run_0002", 2, status=RunStatus.PENDING))
        latest = repo.latest_completed_run()
        assert latest is not None and latest.run_id == "run_0001"

    def test_next_production_day(self, repo: RunRepository):
        assert repo.next_production_day() == 1
        repo.insert_run(_run("run_0001", 1))
        assert repo.next_production_day() == 2
        repo.insert_run(_run("run_0005", 5))
        assert repo.next_production_day() == 6

    def test_update_status(self, repo: RunRepository):
        repo.insert_run(_run(status=RunStatus.RUNNING, completed_at=None))
        repo.update_status(
            "run_0001", RunStatus.COMPLETED, completed_at="2026-08-30T11:00:00+00:00"
        )
        run = repo.get_run("run_0001")
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.completed_at == "2026-08-30T11:00:00+00:00"

    def test_every_status_round_trips(self, repo: RunRepository):
        for day, status in enumerate(RunStatus, start=1):
            repo.insert_run(_run(f"run_{status.value}", day, status=status))
            fetched = repo.get_run(f"run_{status.value}")
            assert fetched is not None and fetched.status is status

    def test_unknown_stored_status_degrades_to_pending(
        self, repo: RunRepository, db: DashboardDatabase
    ):
        repo.insert_run(_run())
        with db.session() as conn:
            conn.execute("UPDATE runs SET status = 'WEIRD' WHERE run_id = 'run_0001'")
        run = repo.get_run("run_0001")
        assert run is not None and run.status is RunStatus.PENDING

    def test_demo_flag_round_trips(self, repo: RunRepository):
        repo.insert_run(_run("demo_run", 1, is_demo=True))
        run = repo.get_run("demo_run")
        assert run is not None and run.is_demo is True

    def test_find_by_artifact_path(self, repo: RunRepository):
        repo.insert_run(_run())
        assert repo.find_by_artifact_path("/runs/run_0001") is not None
        assert repo.find_by_artifact_path("/runs/other") is None

    def test_delete_run(self, repo: RunRepository):
        repo.insert_run(_run())
        repo.delete_run("run_0001")
        assert repo.count_runs() == 0

    def test_delete_all(self, repo: RunRepository):
        for day in (1, 2):
            repo.insert_run(_run(f"run_{day}", day))
        repo.delete_all()
        assert repo.count_runs() == 0

    def test_empty_metadata_stores_as_null(self, repo: RunRepository):
        repo.insert_run(_run(metadata={}))
        run = repo.get_run("run_0001")
        assert run is not None and run.metadata == {}
