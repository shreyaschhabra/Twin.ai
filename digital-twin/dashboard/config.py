"""Dashboard configuration.

Every path the dashboard touches is declared here and overridable by environment
variable, so the dashboard can be pointed at a different factory, database, or run root
without code changes. Defaults deliberately match the existing repository layout
(``cli.py``'s ``DEFAULT_FACTORY``, ``DEFAULT_RUNS``, ``DEFAULT_GENERATED`` and
``system_runtime``'s ``DEFAULT_OUTPUT_DIR``) so the dashboard reads the same artifacts
the existing tooling writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Environment variable names, documented so operators can find them.
ENV_FACTORY = "DT_DASHBOARD_FACTORY"
ENV_DATABASE = "DT_DASHBOARD_DB"
ENV_RUNS_ROOT = "DT_DASHBOARD_RUNS"
ENV_GENERATED_ROOT = "DT_DASHBOARD_GENERATED"
ENV_PREDICTIONS_ROOT = "DT_DASHBOARD_PREDICTIONS"
ENV_DEMO_SEED = "DT_DASHBOARD_DEMO_SEED"
ENV_ALLOW_DEMO_FACTORY = "DT_DASHBOARD_ALLOW_DEMO_FACTORY"

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DashboardConfig:
    """Resolved paths and defaults for one dashboard process."""

    project_root: Path
    #: Authoritative factory topology, shared with the simulator and runtime.
    factory_path: Path
    #: Dashboard-owned SQLite file. Safe to delete.
    database_path: Path
    #: Where the existing pipeline writes completed simulator run directories.
    runs_root: Path
    #: Where the existing scenario generator writes scenario/defect pairs.
    generated_root: Path
    #: Where the coordinated runtime writes prediction streams, health and manifests.
    predictions_root: Path
    #: Seed used when a demo factory has to be generated.
    demo_seed: int = 42
    #: Whether a missing factory.json may be filled in with a demo definition.
    allow_demo_factory: bool = True
    #: Defaults mirroring `cli.py`'s random-run options; used to describe a planned run.
    default_seed: int = 42
    default_duration_ms: int = 28_800_000
    #: Playback speed: 1.0x is approximately real-time. Valid range is 0.75x-20x on
    #: the coordinated pathway; see `existing_runtime_adapter.PLAYBACK_SPEED_MIN/MAX`.
    default_multiplier: float = 1.0

    @property
    def dashboard_root(self) -> Path:
        return self.project_root / "dashboard"


def load_config(project_root: Path | None = None) -> DashboardConfig:
    """Build the configuration, applying environment overrides."""
    root = Path(project_root) if project_root else _PROJECT_ROOT
    return DashboardConfig(
        project_root=root,
        factory_path=_env_path(ENV_FACTORY, root / "simulation" / "config" / "factory.json"),
        database_path=_env_path(ENV_DATABASE, root / "dashboard" / "data" / "dashboard.db"),
        runs_root=_env_path(ENV_RUNS_ROOT, root / "simulation" / "training" / "runs"),
        generated_root=_env_path(
            ENV_GENERATED_ROOT, root / "simulation" / "training" / "generated"
        ),
        predictions_root=_env_path(ENV_PREDICTIONS_ROOT, root / "runtime_output"),
        demo_seed=_env_int(ENV_DEMO_SEED, 42),
        allow_demo_factory=_env_flag(ENV_ALLOW_DEMO_FACTORY, True),
    )
