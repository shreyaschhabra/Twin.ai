"""Startup and isolation tests.

These encode the safety rules for this step: the dashboard starts with nothing in
place, it never runs a simulation on load, and the existing system never depends on it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dashboard.config import DashboardConfig, load_config
from dashboard.context import build_context
from dashboard.factory.manager import FactoryStatus
from dashboard.orchestration.existing_runtime_adapter import AdapterBoundary

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config(tmp_path: Path, **overrides) -> DashboardConfig:
    values = {
        "project_root": PROJECT_ROOT,
        "factory_path": tmp_path / "config" / "factory.json",
        "database_path": tmp_path / "db" / "dashboard.db",
        "runs_root": tmp_path / "runs",
        "generated_root": tmp_path / "generated",
        "predictions_root": tmp_path / "runtime_output",
    }
    values.update(overrides)
    return DashboardConfig(**values)


class TestColdStart:
    def test_starts_with_no_factory_no_database_no_runs(self, tmp_path: Path):
        context = build_context(_config(tmp_path))
        assert context.database_ready is True
        assert context.run_history() == []
        assert context.latest_run() is None

    def test_generates_a_demo_factory_when_missing(self, tmp_path: Path):
        config = _config(tmp_path)
        context = build_context(config)
        assert context.factory.status == FactoryStatus.VALID
        assert context.factory.is_demo
        assert config.factory_path.is_file()
        assert any("demo" in notice.lower() for notice in context.notices)

    def test_respects_demo_generation_being_disabled(self, tmp_path: Path):
        config = _config(tmp_path, allow_demo_factory=False)
        context = build_context(config)
        assert context.factory.status == FactoryStatus.MISSING
        assert not config.factory_path.exists()

    def test_starts_without_a_database(self, tmp_path: Path):
        context = build_context(_config(tmp_path), initialize_database=False)
        assert context.database_ready is False
        assert context.repository is None
        assert context.run_history() == []
        assert context.latest_run() is None
        assert not context.readiness().ready

    def test_never_overwrites_an_existing_factory(self, tmp_path: Path):
        config = _config(tmp_path)
        config.factory_path.parent.mkdir(parents=True)
        source = (PROJECT_ROOT / "simulation" / "config" / "factory.json").read_bytes()
        config.factory_path.write_bytes(source)

        context = build_context(config)

        assert config.factory_path.read_bytes() == source
        assert context.factory.status == FactoryStatus.VALID
        assert not context.factory.is_demo

    def test_invalid_factory_does_not_crash_startup(self, tmp_path: Path):
        config = _config(tmp_path)
        config.factory_path.parent.mkdir(parents=True)
        config.factory_path.write_text(json.dumps({"stations": []}), encoding="utf-8")

        context = build_context(config)

        assert context.factory.status == FactoryStatus.INVALID
        assert context.notices
        assert not context.readiness().ready

    def test_startup_creates_no_run_or_generated_directories(self, tmp_path: Path):
        config = _config(tmp_path)
        build_context(config)
        assert not config.runs_root.exists()
        assert not config.generated_root.exists()
        assert not config.predictions_root.exists()

    def test_repeated_startup_is_stable(self, tmp_path: Path):
        config = _config(tmp_path)
        first = build_context(config)
        digest = config.factory_path.read_bytes()
        second = build_context(config)
        assert config.factory_path.read_bytes() == digest
        assert first.factory.station_count == second.factory.station_count


class TestNoAutomaticExecution:
    def test_planning_the_next_run_executes_nothing(self, tmp_path: Path):
        config = _config(tmp_path)
        context = build_context(config)
        plan = context.run_manager.plan_next_run()
        assert not plan.generated_dir.exists()
        assert not plan.runs_dir.exists()
        assert not plan.expected_run_dir.exists()

    def test_starting_a_run_is_an_explicit_boundary(self, tmp_path: Path):
        context = build_context(_config(tmp_path))
        plan = context.run_manager.plan_next_run()
        with pytest.raises(AdapterBoundary):
            context.run_manager.start_run(plan)

    def test_production_day_advances_with_history(self, tmp_path: Path):
        context = build_context(_config(tmp_path))
        assert context.run_manager.next_production_day() == 1
        plan = context.run_manager.plan_next_run()
        context.run_manager.record_planned_run(plan)
        assert context.run_manager.next_production_day() == 2

    def test_readiness_reports_blockers_rather_than_acting(self, tmp_path: Path):
        config = _config(tmp_path, allow_demo_factory=False)
        readiness = build_context(config).readiness()
        assert not readiness.ready
        assert readiness.blockers


class TestUpstreamIsolation:
    """The dashboard must never become a dependency of the existing system."""

    def test_no_upstream_module_imports_the_dashboard(self):
        offenders = []
        skip = {".git", ".venv", "__pycache__", "dashboard", "build", ".pytest-tmp"}
        for path in PROJECT_ROOT.rglob("*.py"):
            if any(part in skip for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "import dashboard" in text or "from dashboard" in text:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        assert offenders == [], f"upstream modules must not import the dashboard: {offenders}"

    def test_existing_entry_points_import_without_the_dashboard(self):
        """Deleting the dashboard database or package cannot break the system."""
        code = (
            "import sys; sys.path.insert(0, r'%s'); "
            "sys.path.insert(0, r'%s'); "
            "import simulation.training.scenario_generator as s; "
            "import simulation.training.orchestrator as o; "
            "assert s.generate and o.run_generated; print('ok')"
            % (str(PROJECT_ROOT), str(PROJECT_ROOT / "simulation"))
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

    def test_only_the_adapter_touches_the_existing_system(self):
        """Every simulator/runtime import in the dashboard lives behind one seam."""
        forbidden = ("system_runtime", "scenario_generator", "orchestrator", "import cli")
        dashboard_root = PROJECT_ROOT / "dashboard"
        offenders = []
        for path in dashboard_root.rglob("*.py"):
            if "__pycache__" in path.parts or path.parts[-2] == "tests":
                continue
            if path.name == "existing_runtime_adapter.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith(("import ", "from ")):
                    continue
                if any(token in stripped for token in forbidden):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {stripped}")
        assert offenders == [], offenders


class TestConfiguration:
    def test_environment_overrides_are_applied(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DT_DASHBOARD_FACTORY", str(tmp_path / "f.json"))
        monkeypatch.setenv("DT_DASHBOARD_DB", str(tmp_path / "d.db"))
        monkeypatch.setenv("DT_DASHBOARD_DEMO_SEED", "123")
        monkeypatch.setenv("DT_DASHBOARD_ALLOW_DEMO_FACTORY", "false")
        config = load_config()
        assert config.factory_path == tmp_path / "f.json"
        assert config.database_path == tmp_path / "d.db"
        assert config.demo_seed == 123
        assert config.allow_demo_factory is False

    def test_defaults_match_the_existing_layout(self):
        config = load_config()
        assert config.factory_path == PROJECT_ROOT / "simulation" / "config" / "factory.json"
        assert config.runs_root == PROJECT_ROOT / "simulation" / "training" / "runs"
        assert config.predictions_root == PROJECT_ROOT / "runtime_output"

    def test_bad_integer_override_falls_back(self, monkeypatch):
        monkeypatch.setenv("DT_DASHBOARD_DEMO_SEED", "not-a-number")
        assert load_config().demo_seed == 42
