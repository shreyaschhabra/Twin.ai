"""Ingestion tests: only completed runs enter history, and history can be rebuilt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.config import DashboardConfig
from dashboard.domain.run import RunStatus
from dashboard.ingestion.bottleneck_reader import read_bottleneck_summary
from dashboard.ingestion.defect_reader import read_defect_summary
from dashboard.ingestion.run_ingestor import IncompleteRunError, RunIngestor, factory_fingerprint
from dashboard.ingestion.runtime_reader import health_view
from dashboard.orchestration.existing_runtime_adapter import (
    COMPLETED_RUN_FILES,
    COORDINATED_RUN_FILES,
)
from dashboard.storage.database import DashboardDatabase
from dashboard.storage.repositories import RunRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        project_root=PROJECT_ROOT,
        factory_path=PROJECT_ROOT / "simulation" / "config" / "factory.json",
        database_path=tmp_path / "dashboard.db",
        runs_root=tmp_path / "runs",
        generated_root=tmp_path / "generated",
        predictions_root=tmp_path / "runtime_output",
    )


@pytest.fixture
def repo(config: DashboardConfig) -> RunRepository:
    database = DashboardDatabase(config.database_path)
    database.initialize()
    return RunRepository(database)


@pytest.fixture
def ingestor(config: DashboardConfig, repo: RunRepository) -> RunIngestor:
    return RunIngestor(config, repo)


def _completed_run(root: Path, name: str, *, coordinated: bool = True, seed: int = 42) -> Path:
    run = root / name
    run.mkdir(parents=True, exist_ok=True)
    for filename in COORDINATED_RUN_FILES if coordinated else COMPLETED_RUN_FILES:
        if filename == "run_metadata.json":
            (run / filename).write_text(
                json.dumps(
                    {
                        "run_id": f"scenario_{name}",
                        "random_seed": seed,
                        "simulation_duration_ms": 28_800_000,
                        "station_count": 32,
                        "units_created": 400,
                        "schema_version": "2.1",
                    }
                ),
                encoding="utf-8",
            )
        else:
            (run / filename).write_text("header\n", encoding="utf-8")
    return run


def _predictions(root: Path, *, bottleneck: int = 2, defect: int = 2, health: str | None = "PASS") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if bottleneck >= 0:
        (root / "bottleneck_predictions.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "run_id": "r",
                        "timestamp_ms": 1000 * (index + 1),
                        "station_id": index,
                        "vehicle_id": f"U{index}",
                        "zone": "DARK" if index else "LIGHT",
                        "route": "DARK_CORRIDOR" if index else "LIGHT",
                        "bottleneck_probability": 0.4,
                        "warning": index == 1,
                        "diagnostics": {"unknown_categories": []},
                    }
                )
                for index in range(bottleneck)
            )
            + "\n",
            encoding="utf-8",
        )
    if defect >= 0:
        (root / "defect_predictions.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "run_id": "r",
                        "timestamp_ms": 2000 * (index + 1),
                        "unit_id": f"U{index}",
                        "station_id": index,
                        "route": "LIGHT",
                        "defect_probability": 0.7,
                        "threshold_crossed": True,
                        "warning": index == 0,
                    }
                )
                for index in range(defect)
            )
            + "\n",
            encoding="utf-8",
        )
    if health:
        (root / "system_health.json").write_text(
            json.dumps({"overall_status": health}), encoding="utf-8"
        )
    return root


class TestStreamReaders:
    def test_missing_streams_are_not_errors(self, tmp_path: Path):
        bottleneck = read_bottleneck_summary(tmp_path / "absent.jsonl")
        defect = read_defect_summary(tmp_path / "absent.jsonl")
        assert bottleneck.exists is False and bottleneck.record_count == 0
        assert defect.exists is False and defect.record_count == 0

    def test_bottleneck_uses_the_warning_field(self, tmp_path: Path):
        summary = read_bottleneck_summary(
            _predictions(tmp_path) / "bottleneck_predictions.jsonl"
        )
        assert summary.record_count == 2
        assert summary.warning_count == 1
        assert summary.zones == {"LIGHT": 1, "DARK": 1}
        assert summary.first_timestamp_ms == 1000

    def test_defect_counts_warning_and_threshold_separately(self, tmp_path: Path):
        summary = read_defect_summary(_predictions(tmp_path) / "defect_predictions.jsonl")
        assert summary.record_count == 2
        # `warning` is suppressed at final inspection, so it may trail threshold_crossed.
        assert summary.warning_count == 1
        assert summary.threshold_crossed_count == 2

    def test_malformed_lines_are_counted_not_fatal(self, tmp_path: Path):
        path = tmp_path / "bottleneck_predictions.jsonl"
        path.write_text('{"warning": true}\nnot json\n\n', encoding="utf-8")
        summary = read_bottleneck_summary(path)
        assert summary.record_count == 1
        assert summary.malformed_lines == 1

    def test_health_view_only_trusts_pass(self, tmp_path: Path):
        assert health_view(tmp_path).available is False
        _predictions(tmp_path, health="DEGRADED")
        view = health_view(tmp_path)
        assert view.available and view.is_degraded and not view.is_pass


class TestSingleRunIngestion:
    def test_incomplete_run_is_refused(self, ingestor: RunIngestor, tmp_path: Path):
        partial = tmp_path / "runs" / "run_0001"
        partial.mkdir(parents=True)
        (partial / "stations.csv").write_text("x", encoding="utf-8")
        with pytest.raises(IncompleteRunError):
            ingestor.ingest_completed_run(partial)

    def test_completed_run_is_recorded(
        self, ingestor: RunIngestor, repo: RunRepository, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001")
        run = ingestor.ingest_completed_run(run_dir)
        assert run.production_day == 1
        assert run.status is RunStatus.COMPLETED
        assert run.seed == 42
        assert run.duration_ms == 28_800_000
        assert run.scenario_name == "scenario_run_0001"
        assert repo.count_runs() == 1

    def test_records_prediction_stream_summaries(
        self, ingestor: RunIngestor, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001")
        predictions = _predictions(config.predictions_root / "run_0001")
        run = ingestor.ingest_completed_run(run_dir, predictions_dir=predictions)
        assert run.metadata["bottleneck_stream"]["record_count"] == 2
        assert run.metadata["defect_stream"]["record_count"] == 2
        assert run.metadata["system_health_overall_status"] == "PASS"

    def test_one_missing_stream_marks_the_run_partial(
        self, ingestor: RunIngestor, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001")
        predictions = _predictions(config.predictions_root / "run_0001", defect=-1)
        run = ingestor.ingest_completed_run(run_dir, predictions_dir=predictions)
        assert run.status is RunStatus.PARTIAL

    def test_records_coordinated_readiness(
        self, ingestor: RunIngestor, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001", coordinated=False)
        run = ingestor.ingest_completed_run(run_dir)
        assert run.metadata["coordinated_ready"] is False
        assert "runtime_events.csv" in run.metadata["missing_coordinated_files"]

    def test_re_ingesting_keeps_the_production_day(
        self, ingestor: RunIngestor, repo: RunRepository, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001")
        first = ingestor.ingest_completed_run(run_dir)
        second = ingestor.ingest_completed_run(run_dir)
        assert first.production_day == second.production_day
        assert repo.count_runs() == 1

    def test_records_the_factory_fingerprint(
        self, ingestor: RunIngestor, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001")
        run = ingestor.ingest_completed_run(run_dir)
        assert run.factory_fingerprint == factory_fingerprint(config.factory_path)


class TestRebuild:
    def test_no_artifacts_yields_no_history(self, ingestor: RunIngestor):
        result = ingestor.rebuild_from_artifacts()
        assert result.count == 0
        assert result.ingested == ()

    def test_rebuild_assigns_sequential_production_days(
        self, ingestor: RunIngestor, repo: RunRepository, config: DashboardConfig
    ):
        for index in range(1, 4):
            _completed_run(config.runs_root, f"run_{index:04d}", seed=index)
        result = ingestor.rebuild_from_artifacts()
        assert result.count == 3
        days = sorted(run.production_day for run in repo.list_runs())
        assert days == [1, 2, 3]

    def test_rebuild_after_deleting_the_database_restores_history(
        self, config: DashboardConfig
    ):
        """The database is disposable precisely because of this."""
        for index in range(1, 3):
            _completed_run(config.runs_root, f"run_{index:04d}", seed=index)

        database = DashboardDatabase(config.database_path)
        database.initialize()
        repo = RunRepository(database)
        RunIngestor(config, repo).rebuild_from_artifacts()
        before = {run.run_id for run in repo.list_runs()}

        database.delete()
        assert not database.exists()

        database.initialize()
        RunIngestor(config, RunRepository(database)).rebuild_from_artifacts()
        after = {run.run_id for run in RunRepository(database).list_runs()}
        assert before == after

    def test_rebuild_skips_incomplete_directories(
        self, ingestor: RunIngestor, config: DashboardConfig
    ):
        _completed_run(config.runs_root, "run_0001")
        junk = config.runs_root / "run_0002"
        junk.mkdir(parents=True)
        (junk / "stations.csv").write_text("x", encoding="utf-8")
        result = ingestor.rebuild_from_artifacts()
        assert result.count == 1

    def test_rebuild_does_not_modify_artifacts(
        self, ingestor: RunIngestor, config: DashboardConfig
    ):
        run_dir = _completed_run(config.runs_root, "run_0001")
        before = {p.name: p.read_bytes() for p in run_dir.iterdir()}
        ingestor.rebuild_from_artifacts()
        after = {p.name: p.read_bytes() for p in run_dir.iterdir()}
        assert before == after


class TestRunIdentity:
    """Every batch writes its run as `run_0001`, so ids must not collide."""

    def test_nested_runs_get_distinct_ids(self, ingestor: RunIngestor, repo, config):
        for batch in ("production_day_0001", "production_day_0002", "random_test"):
            _completed_run(config.runs_root / batch, "run_0001")
        result = ingestor.rebuild_from_artifacts()
        assert result.count == 3
        assert repo.count_runs() == 3, "runs overwrote each other"
        assert len({run.run_id for run in repo.list_runs()}) == 3

    def test_run_id_traces_back_to_the_artifact_path(self, ingestor, repo, config):
        _completed_run(config.runs_root / "production_day_0001", "run_0001")
        ingestor.rebuild_from_artifacts()
        assert repo.list_runs()[0].run_id == "production_day_0001/run_0001"

    def test_flat_runs_keep_their_own_name(self, ingestor, repo, config):
        _completed_run(config.runs_root, "run_0001")
        ingestor.rebuild_from_artifacts()
        assert repo.list_runs()[0].run_id == "run_0001"


class TestPredictionPairing:
    """Outputs are named by run id, runs by batch/run_0001 -- they must still pair."""

    def test_manifest_pairs_outputs_to_the_run_directory(self, ingestor, config):
        run_dir = _completed_run(config.runs_root / "production_day_0001", "run_0001")
        outputs = _predictions(config.predictions_root / "production_day_0001")
        (outputs / "system_run_manifest.json").write_text(
            json.dumps({"run_id": "production_day_0001", "run_dir": str(run_dir)}),
            encoding="utf-8",
        )
        ingestor.rebuild_from_artifacts()
        run = ingestor.repository.list_runs()[0]
        assert run.predictions_path == str(outputs)
        assert run.metadata["bottleneck_stream"]["record_count"] == 2

    def test_batch_name_fallback_when_no_manifest(self, ingestor, config):
        _completed_run(config.runs_root / "production_day_0001", "run_0001")
        outputs = _predictions(config.predictions_root / "production_day_0001")
        ingestor.rebuild_from_artifacts()
        assert ingestor.repository.list_runs()[0].predictions_path == str(outputs)

    def test_runs_without_outputs_record_none(self, ingestor, config):
        _completed_run(config.runs_root / "production_day_0001", "run_0001")
        ingestor.rebuild_from_artifacts()
        assert ingestor.repository.list_runs()[0].predictions_path is None


class TestHealthDerivedStatus:
    """system_health.json is authoritative; a failed run must never read COMPLETED."""

    def test_failed_health_marks_the_run_failed(self, ingestor, config):
        run_dir = _completed_run(config.runs_root, "run_0001")
        outputs = _predictions(config.predictions_root / "run_0001", health="FAILED")
        run = ingestor.ingest_completed_run(run_dir, predictions_dir=outputs)
        assert run.status is RunStatus.FAILED

    def test_degraded_health_marks_the_run_partial(self, ingestor, config):
        run_dir = _completed_run(config.runs_root, "run_0001")
        outputs = _predictions(config.predictions_root / "run_0001", health="DEGRADED")
        run = ingestor.ingest_completed_run(run_dir, predictions_dir=outputs)
        assert run.status is RunStatus.PARTIAL

    def test_pass_health_marks_the_run_completed(self, ingestor, config):
        run_dir = _completed_run(config.runs_root, "run_0001")
        outputs = _predictions(config.predictions_root / "run_0001", health="PASS")
        run = ingestor.ingest_completed_run(run_dir, predictions_dir=outputs)
        assert run.status is RunStatus.COMPLETED

    def test_simulator_only_run_stays_completed(self, ingestor, config):
        run_dir = _completed_run(config.runs_root, "run_0001")
        assert ingestor.ingest_completed_run(run_dir).status is RunStatus.COMPLETED
