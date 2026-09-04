"""Composition root for the dashboard.

Wires config, factory state, database, repositories, adapter and run manager into one
object the UI can hold. Deliberately free of Streamlit so the whole startup path is
testable headlessly -- and so the "does the app start with no database / no factory /
no runs" questions can be answered without launching a browser.

Constructing a context performs no simulation, no prediction, and no run execution. It
touches the filesystem only to read the factory file and to create/open the dashboard's
own SQLite file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from dashboard.config import DashboardConfig, load_config
from dashboard.domain.run import Run
from dashboard.factory.manager import FactoryState, FactoryStatus, ensure_factory, factory_state
from dashboard.ingestion.run_ingestor import RunIngestor
from dashboard.orchestration.existing_runtime_adapter import ExistingRuntimeAdapter
from dashboard.orchestration.run_manager import RunManager, RunReadiness
from dashboard.storage.database import DashboardDatabase
from dashboard.storage.repositories import RunRepository

logger = logging.getLogger(__name__)


@dataclass
class DashboardContext:
    """Everything one dashboard session needs, with degradation instead of crashes."""

    config: DashboardConfig
    adapter: ExistingRuntimeAdapter
    factory: FactoryState
    database: DashboardDatabase
    database_ready: bool = False
    database_error: str | None = None
    repository: RunRepository | None = None
    run_manager: RunManager | None = None
    ingestor: RunIngestor | None = None
    notices: list[str] = field(default_factory=list)

    # -- derived state ----------------------------------------------------------------

    @property
    def factory_status(self) -> str:
        return self.factory.status

    @property
    def has_history(self) -> bool:
        return bool(self.repository and self.repository.count_runs())

    def latest_run(self) -> Run | None:
        if not self.repository:
            return None
        try:
            return self.repository.latest_run()
        except Exception as error:  # pragma: no cover - defensive around a stale db
            logger.warning("could not read latest run: %s", error)
            return None

    def run_history(self, limit: int = 200) -> list[Run]:
        if not self.repository:
            return []
        try:
            return self.repository.list_runs(limit=limit)
        except Exception as error:  # pragma: no cover - defensive around a stale db
            logger.warning("could not read run history: %s", error)
            return []

    def readiness(self) -> RunReadiness:
        if self.run_manager is None:
            return RunReadiness(ready=False, blockers=("Dashboard database unavailable.",))
        return self.run_manager.check_readiness()

    def refresh_factory(self) -> FactoryState:
        self.factory = factory_state(self.config.factory_path)
        return self.factory


def build_context(
    config: DashboardConfig | None = None,
    *,
    generate_missing_factory: bool | None = None,
    initialize_database: bool = True,
) -> DashboardContext:
    """Build a dashboard context, tolerating every missing prerequisite.

    A missing factory, a missing database, an empty run history and an absent
    coordinated runtime are all normal startup states here, not errors.
    """
    config = config or load_config()
    notices: list[str] = []
    adapter = ExistingRuntimeAdapter(config.project_root)

    allow_generate = (
        config.allow_demo_factory if generate_missing_factory is None else generate_missing_factory
    )
    factory = _resolve_factory(config, allow_generate, notices)

    database = DashboardDatabase(config.database_path)
    database_ready = False
    database_error: str | None = None
    repository: RunRepository | None = None
    run_manager: RunManager | None = None
    ingestor: RunIngestor | None = None

    if initialize_database:
        try:
            database.initialize()
            database_ready = True
        except Exception as error:
            database_error = str(error)
            notices.append(f"Dashboard database unavailable: {error}")
            logger.warning("dashboard database unavailable: %s", error)

    if database_ready:
        repository = RunRepository(database)
        run_manager = RunManager(config, adapter, repository)
        ingestor = RunIngestor(config, repository, adapter)
    else:
        run_manager = RunManager(config, adapter, None)

    return DashboardContext(
        config=config,
        adapter=adapter,
        factory=factory,
        database=database,
        database_ready=database_ready,
        database_error=database_error,
        repository=repository,
        run_manager=run_manager,
        ingestor=ingestor,
        notices=notices,
    )


def _resolve_factory(
    config: DashboardConfig, allow_generate: bool, notices: list[str]
) -> FactoryState:
    path = Path(config.factory_path)
    if path.exists():
        state = factory_state(path)
        if state.status == FactoryStatus.INVALID:
            notices.append(
                f"Factory configuration at {path} is not valid for the simulator "
                "and was left untouched."
            )
        return state

    if not allow_generate:
        notices.append(f"No factory configuration at {path}.")
        return factory_state(path)

    try:
        state = ensure_factory(path, seed=config.demo_seed)
    except Exception as error:
        notices.append(f"Could not generate a demo factory at {path}: {error}")
        logger.warning("demo factory generation failed: %s", error)
        return factory_state(path)

    notices.append(
        f"No factory configuration existed, so a demo definition was generated at {path}. "
        "Its station parameters are illustrative prototype values, not measured plant data."
    )
    return state
