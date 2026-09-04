"""Run History storage management: deleting a run's row AND its artifacts.

Deletion follows the same ownership model as everywhere else in the dashboard: a run's
directories are only ever derived from the dashboard's own configured roots
(``runs_root``/``generated_root``/``predictions_root``), and a directory is removed only
when it is a genuine descendant of the matching root -- never the root itself, and never
a path a row happens to reference that lives somewhere else entirely. Missing files are
not an error; a currently-executing run is never offered for deletion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.config import DashboardConfig
from dashboard.domain.run import Run, RunStatus
from dashboard.orchestration.existing_runtime_adapter import ExistingRuntimeAdapter
from dashboard.orchestration.run_manager import RunManager
from dashboard.storage.database import DashboardDatabase
from dashboard.storage.repositories import RunRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        project_root=PROJECT_ROOT,
        factory_path=tmp_path / "config" / "factory.json",
        database_path=tmp_path / "db" / "dashboard.db",
        runs_root=tmp_path / "runs",
        generated_root=tmp_path / "generated",
        predictions_root=tmp_path / "runtime_output",
    )


def _manager(config: DashboardConfig) -> tuple[RunManager, RunRepository]:
    database = DashboardDatabase(config.database_path)
    database.initialize()
    repository = RunRepository(database)
    adapter = ExistingRuntimeAdapter(config.project_root)
    return RunManager(config, adapter, repository), repository


def _seed_run(config: DashboardConfig, repository: RunRepository, run_id: str, *, day: int = 1) -> Run:
    """Fake artifacts the size and shape of what the dashboard actually creates."""
    run_dir = config.runs_root / run_id / "run_0001"
    run_dir.mkdir(parents=True)
    (run_dir / "stations.csv").write_text("station_id\nS01\n", encoding="utf-8")

    predictions_dir = config.predictions_root / run_id
    predictions_dir.mkdir(parents=True)
    (predictions_dir / "bottleneck_predictions.jsonl").write_text("{}\n", encoding="utf-8")
    (predictions_dir / "defect_predictions.jsonl").write_text("{}\n", encoding="utf-8")

    generated_dir = config.generated_root / run_id
    generated_dir.mkdir(parents=True)
    (generated_dir / "manifest.json").write_text("{}", encoding="utf-8")

    run = Run(
        run_id=run_id,
        production_day=day,
        status=RunStatus.COMPLETED,
        artifact_path=str(run_dir),
        predictions_path=str(predictions_dir),
        factory_path=str(config.factory_path),
    )
    repository.upsert_run(run)
    return run


class TestDeleteSingleRun:
    def test_deletes_the_row_and_every_owned_directory(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, repository = _manager(config)
        _seed_run(config, repository, "production_day_0001")

        result = manager.delete_run("production_day_0001")

        assert result.row_deleted is True
        assert repository.get_run("production_day_0001") is None
        assert not (config.runs_root / "production_day_0001").exists()
        assert not (config.predictions_root / "production_day_0001").exists()
        assert not (config.generated_root / "production_day_0001").exists()
        assert result.ok

    def test_the_configured_roots_themselves_survive(self, tmp_path: Path):
        """Deleting a run must never remove the shared root directory it lives under."""
        config = _config(tmp_path)
        manager, repository = _manager(config)
        _seed_run(config, repository, "production_day_0001")

        manager.delete_run("production_day_0001")

        assert config.runs_root.exists()
        assert config.predictions_root.exists()
        assert config.generated_root.exists()

    def test_other_runs_survive(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, repository = _manager(config)
        _seed_run(config, repository, "production_day_0001", day=1)
        _seed_run(config, repository, "production_day_0002", day=2)

        manager.delete_run("production_day_0001")

        assert repository.get_run("production_day_0002") is not None
        assert (config.runs_root / "production_day_0002").exists()

    def test_deleting_an_unknown_run_id_is_a_safe_no_op(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, repository = _manager(config)

        result = manager.delete_run("never_existed")

        assert result.row_deleted is False
        assert result.ok

    def test_missing_directories_are_handled_safely(self, tmp_path: Path):
        """A row can outlive its artifacts (hand-deleted, or a partial run); no crash."""
        config = _config(tmp_path)
        manager, repository = _manager(config)
        run = Run(
            run_id="ghost_run",
            production_day=1,
            status=RunStatus.PARTIAL,
            artifact_path=str(config.runs_root / "ghost_run" / "run_0001"),
            predictions_path=str(config.predictions_root / "ghost_run"),
            factory_path=str(config.factory_path),
        )
        repository.upsert_run(run)

        result = manager.delete_run("ghost_run")

        assert result.row_deleted is True
        assert result.ok
        assert result.deleted_directories == ()
        assert len(result.missing_directories) >= 2

    def test_a_path_outside_the_configured_roots_is_skipped_not_deleted(self, tmp_path: Path):
        """The ownership guard: never trust a stored path outright."""
        config = _config(tmp_path)
        manager, repository = _manager(config)
        outside = tmp_path / "somewhere_else"
        outside.mkdir()
        (outside / "precious.txt").write_text("do not delete", encoding="utf-8")

        run = Run(
            run_id="sneaky_run",
            production_day=1,
            status=RunStatus.COMPLETED,
            artifact_path=str(outside / "run_0001"),
            predictions_path=str(outside),
            factory_path=str(config.factory_path),
        )
        repository.upsert_run(run)

        result = manager.delete_run("sneaky_run")

        assert result.row_deleted is True
        assert outside.exists()
        assert (outside / "precious.txt").exists()
        assert outside in result.skipped_directories

    def test_factory_configuration_is_never_touched(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, repository = _manager(config)
        config.factory_path.parent.mkdir(parents=True)
        config.factory_path.write_text('{"stations": []}', encoding="utf-8")
        _seed_run(config, repository, "production_day_0001")

        manager.delete_run("production_day_0001")

        assert config.factory_path.exists()

    def test_double_delete_is_safe(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, repository = _manager(config)
        _seed_run(config, repository, "production_day_0001")

        first = manager.delete_run("production_day_0001")
        second = manager.delete_run("production_day_0001")

        assert first.row_deleted is True
        assert second.row_deleted is False
        assert second.ok


class TestDeleteAllRuns:
    def test_deletes_every_run_and_its_artifacts(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, repository = _manager(config)
        for index in range(1, 4):
            _seed_run(config, repository, f"production_day_{index:04d}", day=index)

        results = manager.delete_all_runs()

        assert len(results) == 3
        assert all(result.ok for result in results)
        assert repository.count_runs() == 0
        assert not any(config.runs_root.iterdir())

    def test_excludes_the_currently_active_run(self, tmp_path: Path):
        """A run still being written to must never have its artifacts pulled out from
        under it."""
        config = _config(tmp_path)
        manager, repository = _manager(config)
        _seed_run(config, repository, "production_day_0001", day=1)
        active = _seed_run(config, repository, "production_day_0002", day=2)

        results = manager.delete_all_runs(exclude_run_ids={active.run_id})

        assert len(results) == 1
        assert results[0].run_id == "production_day_0001"
        assert repository.get_run("production_day_0002") is not None
        assert (config.runs_root / "production_day_0002").exists()

    def test_empty_history_deletes_nothing(self, tmp_path: Path):
        config = _config(tmp_path)
        manager, _ = _manager(config)
        assert manager.delete_all_runs() == []


class TestRunHistoryPageStorageControls:
    """The Streamlit page: counts, confirmation gating, and the resulting state."""

    def _launch(self, tmp_path: Path, monkeypatch):
        pytest.importorskip("streamlit", reason="dashboard/requirements.txt not installed")
        from streamlit.testing.v1 import AppTest

        monkeypatch.setenv("DT_DASHBOARD_FACTORY", str(tmp_path / "config" / "factory.json"))
        monkeypatch.setenv("DT_DASHBOARD_DB", str(tmp_path / "db" / "dashboard.db"))
        monkeypatch.setenv("DT_DASHBOARD_RUNS", str(tmp_path / "runs"))
        monkeypatch.setenv("DT_DASHBOARD_GENERATED", str(tmp_path / "generated"))
        monkeypatch.setenv("DT_DASHBOARD_PREDICTIONS", str(tmp_path / "runtime_output"))

        from dashboard.config import load_config

        config = load_config()
        _, repository = _manager(config)
        _seed_run(config, repository, "production_day_0001", day=1)
        _seed_run(config, repository, "production_day_0002", day=2)

        app = AppTest.from_file(
            str(PROJECT_ROOT / "dashboard" / "app.py"), default_timeout=60
        )
        app.run()
        return app.sidebar.radio[0].set_value("Run History").run(), config

    def test_shows_how_many_runs_are_stored(self, tmp_path: Path, monkeypatch):
        app, _ = self._launch(tmp_path, monkeypatch)
        assert not app.exception, [str(e) for e in app.exception]
        labels = {metric.label: metric.value for metric in app.metric}
        assert labels.get("Stored runs") == "2"

    def test_delete_all_requires_confirmation_before_deleting_anything(
        self, tmp_path: Path, monkeypatch
    ):
        app, config = self._launch(tmp_path, monkeypatch)
        button = next(b for b in app.button if "Delete All Runs" in b.label)
        app = button.click().run()
        assert not app.exception, [str(e) for e in app.exception]

        # Nothing has been deleted yet -- only a confirmation prompt appeared.
        assert (config.runs_root / "production_day_0001").exists()
        assert any("permanently deletes" in str(w.value) for w in app.warning)
        assert any("Yes, delete" in b.label for b in app.button)

    def test_confirming_deletes_the_rows_and_the_artifacts(self, tmp_path: Path, monkeypatch):
        app, config = self._launch(tmp_path, monkeypatch)
        button = next(b for b in app.button if "Delete All Runs" in b.label)
        app = button.click().run()
        confirm = next(b for b in app.button if "Yes, delete" in b.label)
        app = confirm.click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert "No completed production runs yet." in "\n".join(
            str(i.value) for i in app.info
        )
        assert not (config.runs_root / "production_day_0001").exists()
        assert not (config.runs_root / "production_day_0002").exists()

    def test_cancel_leaves_history_untouched(self, tmp_path: Path, monkeypatch):
        app, config = self._launch(tmp_path, monkeypatch)
        button = next(b for b in app.button if "Delete All Runs" in b.label)
        app = button.click().run()
        cancel = next(b for b in app.button if b.label == "Cancel")
        app = cancel.click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert (config.runs_root / "production_day_0001").exists()
        labels = {metric.label: metric.value for metric in app.metric}
        assert labels.get("Stored runs") == "2"

    def test_per_run_delete_removes_only_that_run(self, tmp_path: Path, monkeypatch):
        app, config = self._launch(tmp_path, monkeypatch)
        picker = next(box for box in app.selectbox if box.label == "Select a production run")
        target = next(label for label in picker.options if "production_day_0001" in label)
        app = picker.set_value(target).run()

        delete_button = next(
            b for b in app.button if "Delete this run" in b.label and "production_day_0001" in b.label
        )
        app = delete_button.click().run()
        confirm = next(b for b in app.button if b.label == "Yes, delete this run")
        app = confirm.click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert not (config.runs_root / "production_day_0001").exists()
        assert (config.runs_root / "production_day_0002").exists()

    def test_rebuild_control_still_present(self, tmp_path: Path, monkeypatch):
        """Storage management must not have displaced the existing rebuild feature."""
        app, _ = self._launch(tmp_path, monkeypatch)
        assert any("Rebuild from artifacts" in b.label for b in app.button)
