"""Tests for run-plan preflight and command rendering.

The contract these enforce: a command the dashboard displays must either run, or be
replaced by a blocker explaining why it cannot. Every check here corresponds to a real
failure observed against this repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.orchestration.existing_runtime_adapter import (
    COMPLETED_RUN_FILES,
    PATHWAY_BOTTLENECK,
    ExistingRuntimeAdapter,
    ModelCoverage,
    station_runtime_label,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def adapter() -> ExistingRuntimeAdapter:
    return ExistingRuntimeAdapter(PROJECT_ROOT)


def _factory(station_count: int = 8, dark: tuple[int, int] | None = None) -> dict:
    stations = []
    for index in range(station_count):
        station = {
            "id": index,
            "name": f"Station {index}",
            "archetype": "AUTOMATED",
            "meanCycleTimeMs": 40_000,
            "cycleTimeCV": 0.1,
            "bufferCapacity": 4,
            "sensorCoverage": "HIGH",
        }
        if index == 0:
            station["source"] = True
        if index == station_count - 1:
            station["sink"] = True
        stations.append(station)
    factory = {"stations": stations}
    if dark:
        factory["darkZones"] = [
            {
                "id": "DZ_01",
                "name": "Corridor",
                "startStationId": dark[0],
                "endStationId": dark[1],
                "observability": {"sensorTelemetry": True},
            }
        ]
    return factory


def _plan(adapter: ExistingRuntimeAdapter, tmp_path: Path, **overrides):
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


class TestStationLabels:
    def test_labels_are_one_based(self):
        """Verified against a completed run's stations.csv: factory id 0 is S01."""
        assert station_runtime_label(0) == "S01"
        assert station_runtime_label(11) == "S12"
        assert station_runtime_label(31) == "S32"


class TestCommandRendering:
    def test_powershell_prefixes_environment(self, adapter, tmp_path: Path):
        rendered = _plan(adapter, tmp_path).command_line("powershell")
        assert rendered.startswith('$env:PYTHONUTF8="1"; ')

    def test_bash_prefixes_environment(self, adapter, tmp_path: Path):
        assert _plan(adapter, tmp_path).command_line("bash").startswith("PYTHONUTF8=1 ")

    def test_cmd_prefixes_environment(self, adapter, tmp_path: Path):
        assert _plan(adapter, tmp_path).command_line("cmd").startswith("set PYTHONUTF8=1 && ")

    def test_utf8_is_required_on_every_shell(self, adapter, tmp_path: Path):
        """Upstream dark_zone modules print non-ASCII; redirected stdout needs UTF-8."""
        plan = _plan(adapter, tmp_path)
        for shell in ("powershell", "cmd", "bash"):
            assert "PYTHONUTF8" in plan.command_line(shell)

    def test_paths_with_spaces_are_quoted(self, adapter, tmp_path: Path):
        spaced = tmp_path / "my runs"
        plan = _plan(adapter, tmp_path, runs_dir=spaced)
        for shell in ("powershell", "cmd", "bash"):
            rendered = plan.command_line(shell)
            assert "my runs" in rendered
            assert f"--runs {spaced}" not in rendered, "unquoted path would split on the space"

    def test_unknown_shell_is_rejected(self, adapter, tmp_path: Path):
        with pytest.raises(ValueError):
            _plan(adapter, tmp_path).command_line("fish")

    def test_subprocess_environment_includes_overrides(self, adapter, tmp_path: Path):
        assert _plan(adapter, tmp_path).subprocess_environment()["PYTHONUTF8"] == "1"


class TestPreflightBlockers:
    def test_occupied_generated_directory_blocks(self, adapter, tmp_path: Path):
        generated = tmp_path / "generated"
        generated.mkdir()
        (generated / "scenario_0001.json").write_text("{}", encoding="utf-8")
        plan = _plan(adapter, tmp_path, generated_dir=generated)
        assert not plan.runnable
        assert any("already contains files" in b for b in plan.blockers)

    def test_existing_run_directory_blocks(self, adapter, tmp_path: Path):
        runs = tmp_path / "runs"
        (runs / "run_0001").mkdir(parents=True)
        plan = _plan(adapter, tmp_path, runs_dir=runs)
        assert not plan.runnable
        assert any("already exists" in b for b in plan.blockers)

    def test_empty_generated_directory_does_not_block(self, adapter, tmp_path: Path):
        generated = tmp_path / "generated"
        generated.mkdir()
        plan = _plan(adapter, tmp_path, generated_dir=generated)
        assert not any("already contains" in b for b in plan.blockers)

    def test_missing_simulator_blocks(self, tmp_path: Path):
        isolated = ExistingRuntimeAdapter(tmp_path)
        plan = _plan(isolated, tmp_path)
        assert not plan.runnable
        assert any("simulator is not built" in b for b in plan.blockers)

    def test_clean_plan_is_runnable(self, adapter, tmp_path: Path):
        plan = _plan(adapter, tmp_path)
        assert plan.runnable, plan.blockers


class TestModelCoverage:
    def test_base_model_can_score_the_repository_factory(self, adapter):
        factory = json.loads(
            (PROJECT_ROOT / "simulation" / "config" / "factory.json").read_text(encoding="utf-8")
        )
        assert adapter.check_bottleneck_model(factory, "base").usable

    def test_missing_station_levels_are_reported(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter, "_model_dark_stations", lambda model_id: None)
        monkeypatch.setattr(
            adapter, "_model_station_levels", lambda model_id: {"S02", "S03"}
        )
        coverage = adapter.check_bottleneck_model(_factory(5), "stale")
        assert not coverage.usable
        assert coverage.missing_labels == ("S04", "S05")
        assert "unknown model-category outputs" in (coverage.reason or "")

    def test_corridor_mismatch_is_reported(self, adapter, monkeypatch):
        """The failure mode seen as S15:sensor_coverage expected='NONE'."""
        monkeypatch.setattr(
            adapter, "_model_dark_stations", lambda model_id: {"S03", "S04", "S05"}
        )
        coverage = adapter.check_bottleneck_model(_factory(8, dark=(2, 3)), "stale")
        assert not coverage.usable
        assert "factory-contract check" in (coverage.reason or "")

    def test_source_station_is_not_required(self, adapter, monkeypatch):
        """The source emits no bottleneck prediction, so S01 need not be a known level."""
        monkeypatch.setattr(adapter, "_model_dark_stations", lambda model_id: None)
        monkeypatch.setattr(
            adapter, "_model_station_levels", lambda model_id: {"S02", "S03", "S04", "S05"}
        )
        assert adapter.check_bottleneck_model(_factory(5), "ok").usable

    def test_unreadable_model_is_not_usable(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter, "_model_dark_stations", lambda model_id: None)
        monkeypatch.setattr(adapter, "_model_station_levels", lambda model_id: None)
        assert not adapter.check_bottleneck_model(_factory(5), "broken").usable

    def test_choose_prefers_a_usable_model_and_explains_the_switch(self, adapter, monkeypatch):
        def coverage(factory, model_id):
            return ModelCoverage(model_id, usable=(model_id == "base"), reason="stale model")

        monkeypatch.setattr(adapter, "selected_bottleneck_model_id", lambda: "factory-a")
        monkeypatch.setattr(adapter, "bottleneck_model_ids", lambda: ["base", "factory-a"])
        monkeypatch.setattr(adapter, "check_bottleneck_model", coverage)

        chosen, notes = adapter.choose_bottleneck_model(_factory(5))
        assert chosen == "base"
        assert any("saved model selection is unchanged" in note for note in notes)

    def test_choose_returns_none_when_nothing_works(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter, "selected_bottleneck_model_id", lambda: "factory-a")
        monkeypatch.setattr(adapter, "bottleneck_model_ids", lambda: ["factory-a"])
        monkeypatch.setattr(
            adapter,
            "check_bottleneck_model",
            lambda factory, model_id: ModelCoverage(model_id, usable=False, reason="no good"),
        )
        chosen, notes = adapter.choose_bottleneck_model(_factory(5))
        assert chosen is None
        assert notes


class TestModelSelectionInCommand:
    def test_verified_plan_pins_the_model_explicitly(self, adapter, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(adapter, "choose_bottleneck_model", lambda factory: ("base", []))
        plan = _plan(adapter, tmp_path, factory=_factory(5))
        assert "--bottleneck-model-id" in plan.command
        assert plan.command[plan.command.index("--bottleneck-model-id") + 1] == "base"

    def test_bottleneck_pathway_uses_model_id_flag(self, adapter, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(adapter, "choose_bottleneck_model", lambda factory: ("base", []))
        plan = _plan(
            adapter, tmp_path, factory=_factory(5), pathway=PATHWAY_BOTTLENECK, multiplier=30.0
        )
        assert "--model-id" in plan.command
        assert "--bottleneck-model-id" not in plan.command

    def test_no_usable_model_blocks_the_command(self, adapter, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            adapter, "choose_bottleneck_model", lambda factory: (None, ["every model is stale"])
        )
        plan = _plan(adapter, tmp_path, factory=_factory(5))
        assert not plan.runnable
        assert "every model is stale" in plan.blockers

    def test_plan_without_a_factory_skips_model_selection(self, adapter, tmp_path: Path):
        plan = _plan(adapter, tmp_path)
        assert "--bottleneck-model-id" not in plan.command

    def test_missing_defect_dependency_blocks_coordinated_runs(
        self, adapter, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(
            adapter, "defect_dependencies_ready", lambda: (False, "catboost is missing")
        )
        plan = _plan(adapter, tmp_path)
        assert not plan.runnable
        assert "catboost is missing" in plan.blockers


class TestRunIdSelection:
    def test_planner_skips_occupied_run_ids(self, tmp_path: Path):
        from dashboard.config import DashboardConfig
        from dashboard.orchestration.run_manager import RunManager

        config = DashboardConfig(
            project_root=PROJECT_ROOT,
            factory_path=PROJECT_ROOT / "simulation" / "config" / "factory.json",
            database_path=tmp_path / "dashboard.db",
            runs_root=tmp_path / "runs",
            generated_root=tmp_path / "generated",
            predictions_root=tmp_path / "out",
        )
        (config.runs_root / "production_day_0001" / "run_0001").mkdir(parents=True)
        (config.runs_root / "production_day_0002" / "run_0001").mkdir(parents=True)

        from dashboard.storage.database import DashboardDatabase
        from dashboard.storage.repositories import RunRepository

        database = DashboardDatabase(config.database_path)
        database.initialize()
        manager = RunManager(config, ExistingRuntimeAdapter(PROJECT_ROOT), RunRepository(database))

        plan = manager.plan_next_run()
        assert plan.run_id == "production_day_0003"
        assert plan.runnable, plan.blockers

    def test_completed_run_directories_never_collide(self, tmp_path: Path):
        """The exact 'directory already contains files' error must not be emitted."""
        from dashboard.config import DashboardConfig
        from dashboard.orchestration.run_manager import RunManager
        from dashboard.storage.database import DashboardDatabase
        from dashboard.storage.repositories import RunRepository

        config = DashboardConfig(
            project_root=PROJECT_ROOT,
            factory_path=PROJECT_ROOT / "simulation" / "config" / "factory.json",
            database_path=tmp_path / "dashboard.db",
            runs_root=tmp_path / "runs",
            generated_root=tmp_path / "generated",
            predictions_root=tmp_path / "out",
        )
        run = config.runs_root / "production_day_0001" / "run_0001"
        run.mkdir(parents=True)
        for name in COMPLETED_RUN_FILES:
            (run / name).write_text("x", encoding="utf-8")

        database = DashboardDatabase(config.database_path)
        database.initialize()
        manager = RunManager(config, ExistingRuntimeAdapter(PROJECT_ROOT), RunRepository(database))
        assert manager.plan_next_run().runnable
