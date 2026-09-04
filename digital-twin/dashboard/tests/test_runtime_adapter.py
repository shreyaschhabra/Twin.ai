"""Adapter tests: the dashboard's only seam onto the existing system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.orchestration.existing_runtime_adapter import (
    COMPLETED_RUN_FILES,
    COORDINATED_RUN_FILES,
    PATHWAY_BOTTLENECK,
    PATHWAY_COORDINATED,
    AdapterBoundary,
    ExistingRuntimeAdapter,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def adapter() -> ExistingRuntimeAdapter:
    return ExistingRuntimeAdapter(PROJECT_ROOT)


def _make_run(root: Path, name: str = "run_0001", *, coordinated: bool = False) -> Path:
    run = root / name
    run.mkdir(parents=True, exist_ok=True)
    names = COORDINATED_RUN_FILES if coordinated else COMPLETED_RUN_FILES
    for filename in names:
        if filename.endswith(".json"):
            (run / filename).write_text(json.dumps({"run_id": name}), encoding="utf-8")
        else:
            (run / filename).write_text("header\n", encoding="utf-8")
    return run


class TestDiscovery:
    def test_default_factory_path_matches_cli(self, adapter: ExistingRuntimeAdapter):
        assert adapter.default_factory_path() == (
            PROJECT_ROOT / "simulation" / "config" / "factory.json"
        )

    def test_discover_factory_prefers_configured(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        configured = tmp_path / "factory.json"
        configured.write_text("{}", encoding="utf-8")
        assert adapter.discover_factory(configured) == configured.resolve()

    def test_discover_factory_falls_back_to_repository_default(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        found = adapter.discover_factory(tmp_path / "absent.json")
        assert found is None or found.name == "factory.json"

    def test_simulator_candidates_are_under_the_build_tree(
        self, adapter: ExistingRuntimeAdapter
    ):
        for candidate in adapter.simulator_candidates():
            assert "build" in candidate.parts

    def test_resolve_simulator_never_builds(self, tmp_path: Path):
        """A page render must never trigger a CMake build."""
        isolated = ExistingRuntimeAdapter(tmp_path)
        assert isolated.resolve_simulator() is None
        assert isolated.simulator_available() is False
        assert not (tmp_path / "simulation" / "build").exists()


class TestCompletedRuns:
    def test_empty_directory_is_not_a_completed_run(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        assert adapter.is_completed_run(tmp_path) is False
        assert adapter.inspect_run(tmp_path) is None

    def test_missing_files_are_named(self, adapter: ExistingRuntimeAdapter, tmp_path: Path):
        assert set(adapter.missing_run_files(tmp_path)) == set(COMPLETED_RUN_FILES)

    def test_base_completed_run(self, adapter: ExistingRuntimeAdapter, tmp_path: Path):
        run = _make_run(tmp_path)
        assert adapter.is_completed_run(run) is True
        assert adapter.is_coordinated_ready(run) is False

    def test_coordinated_ready_run(self, adapter: ExistingRuntimeAdapter, tmp_path: Path):
        run = _make_run(tmp_path, coordinated=True)
        assert adapter.is_coordinated_ready(run) is True

    def test_inspect_reports_coordinated_gaps(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        run = _make_run(tmp_path)
        inspected = adapter.inspect_run(run)
        assert inspected is not None
        assert inspected.run_id == "run_0001"
        assert inspected.is_coordinated_ready is False
        assert "runtime_events.csv" in inspected.missing

    def test_list_completed_runs_handles_missing_root(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        assert adapter.list_completed_runs(tmp_path / "absent") == []
        assert adapter.list_completed_runs(None) == []

    def test_list_completed_runs_finds_flat_layout(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        for index in range(3):
            _make_run(tmp_path, f"run_{index:04d}")
        assert len(adapter.list_completed_runs(tmp_path)) == 3

    def test_list_completed_runs_finds_nested_batches(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        _make_run(tmp_path / "batch_a")
        _make_run(tmp_path / "batch_b")
        found = adapter.list_completed_runs(tmp_path)
        assert len(found) == 2

    def test_run_metadata_is_parsed(self, adapter: ExistingRuntimeAdapter, tmp_path: Path):
        run = _make_run(tmp_path)
        assert (adapter.read_run_metadata(run) or {})["run_id"] == "run_0001"

    def test_run_metadata_missing_is_none(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        assert adapter.read_run_metadata(tmp_path) is None


class TestPredictionArtifacts:
    def test_output_paths_use_contract_filenames(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        paths = adapter.prediction_output_paths(tmp_path)
        assert paths["bottleneck"].name == "bottleneck_predictions.jsonl"
        assert paths["defect"].name == "defect_predictions.jsonl"
        assert paths["health"].name == "system_health.json"
        assert paths["manifest"].name == "system_run_manifest.json"

    def test_streams_stay_separate(self, adapter: ExistingRuntimeAdapter, tmp_path: Path):
        paths = adapter.prediction_output_paths(tmp_path)
        assert paths["bottleneck"] != paths["defect"]

    def test_missing_health_and_manifest_are_none(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        assert adapter.read_system_health(tmp_path) is None
        assert adapter.read_system_manifest(tmp_path) is None

    def test_health_and_manifest_are_read(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        (tmp_path / "system_health.json").write_text(
            json.dumps({"overall_status": "PASS"}), encoding="utf-8"
        )
        (tmp_path / "system_run_manifest.json").write_text(
            json.dumps({"run_id": "r"}), encoding="utf-8"
        )
        assert (adapter.read_system_health(tmp_path) or {})["overall_status"] == "PASS"
        assert (adapter.read_system_manifest(tmp_path) or {})["run_id"] == "r"

    def test_corrupt_artifact_degrades_to_none(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        (tmp_path / "system_health.json").write_text("{broken", encoding="utf-8")
        assert adapter.read_system_health(tmp_path) is None


class TestExistingFunctionReuse:
    def test_scenario_generator_is_the_existing_one(self, adapter: ExistingRuntimeAdapter):
        generate = adapter.scenario_generator()
        assert generate is not None
        assert generate.__module__.endswith("scenario_generator")
        assert generate.__name__ == "generate"

    def test_run_orchestrator_is_the_existing_one(self, adapter: ExistingRuntimeAdapter):
        run_generated = adapter.run_orchestrator()
        assert run_generated is not None
        assert run_generated.__module__.endswith("orchestrator")
        assert run_generated.__name__ == "run_generated"


class TestRunPlanning:
    def _plan(self, adapter: ExistingRuntimeAdapter, tmp_path: Path, **overrides):
        options = {
            "factory_path": tmp_path / "factory.json",
            "generated_dir": tmp_path / "generated",
            "runs_dir": tmp_path / "runs",
            "output_dir": tmp_path / "out",
            "run_id": "production_day_0001",
            "seed": 7,
            "duration_ms": 600_000,
        }
        options.update(overrides)
        return adapter.plan_random_run(**options)

    def test_coordinated_plan_uses_the_existing_cli_entry_point(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        plan = self._plan(adapter, tmp_path)
        assert plan.command[1].endswith("cli.py")
        assert plan.command[2:5] == ["system", "run", "random"]
        assert "--output-dir" in plan.command

    def test_coordinated_plan_defaults_to_real_time_playback(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        """`system run random` is paced by --mult; 1x is the default, real-time speed."""
        plan = self._plan(adapter, tmp_path)
        assert plan.multiplier == 1.0
        assert plan.command[plan.command.index("--mult") + 1] == "1.0"

    def test_coordinated_plan_carries_the_selected_playback_speed(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        plan = self._plan(adapter, tmp_path, multiplier=10.0)
        assert plan.multiplier == 10.0
        assert plan.command[plan.command.index("--mult") + 1] == "10.0"

    def test_coordinated_plan_rejects_a_playback_speed_outside_the_dashboard_range(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        too_slow = self._plan(adapter, tmp_path, multiplier=0.5)
        assert any("Playback speed" in blocker for blocker in too_slow.blockers)
        assert not too_slow.runnable

        too_fast = self._plan(adapter, tmp_path, multiplier=30.0)
        assert any("Playback speed" in blocker for blocker in too_fast.blockers)
        assert not too_fast.runnable

    def test_coordinated_plan_accepts_the_full_dashboard_range(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        for speed in (0.75, 1.0, 20.0):
            plan = self._plan(adapter, tmp_path, multiplier=speed)
            assert not any("Playback speed" in blocker for blocker in plan.blockers)
            assert plan.command[plan.command.index("--mult") + 1] == str(float(speed))

    def test_bottleneck_plan_carries_the_multiplier(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        plan = self._plan(adapter, tmp_path, pathway=PATHWAY_BOTTLENECK, multiplier=30.0)
        assert plan.command[2:4] == ["run", "random"]
        assert plan.multiplier == 30.0
        assert plan.command[plan.command.index("--mult") + 1] == "30.0"

    def test_unknown_pathway_is_rejected(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        with pytest.raises(ValueError):
            self._plan(adapter, tmp_path, pathway="magic")

    def test_expected_run_dir_matches_cli_naming(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        assert self._plan(adapter, tmp_path).expected_run_dir.name == "run_0001"

    def test_planning_writes_nothing(self, adapter: ExistingRuntimeAdapter, tmp_path: Path):
        plan = self._plan(adapter, tmp_path)
        assert not plan.generated_dir.exists()
        assert not plan.runs_dir.exists()
        assert not plan.output_dir.exists()

    def test_execute_is_a_documented_boundary(
        self, adapter: ExistingRuntimeAdapter, tmp_path: Path
    ):
        plan = self._plan(adapter, tmp_path)
        with pytest.raises(AdapterBoundary) as excinfo:
            adapter.execute_planned_run(plan)
        assert "cli.py" in excinfo.value.command_line

    def test_prepare_without_a_simulator_raises_a_boundary(self, tmp_path: Path):
        isolated = ExistingRuntimeAdapter(tmp_path)
        plan = self._plan(isolated, tmp_path, pathway=PATHWAY_COORDINATED)
        with pytest.raises(AdapterBoundary):
            isolated.prepare_random_run(plan)
