"""Run lifecycle coordination for the dashboard.

The RUN FACTORY action means "one complete execution of the existing pipeline", which
the dashboard records as one production day. This module owns that bookkeeping and
nothing else: it plans runs, reports readiness, and hands completed artifacts to the
ingestor. It never simulates, never predicts, and never writes upstream state.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dashboard.config import DashboardConfig
from dashboard.domain.run import Run, RunStatus
from dashboard.factory.manager import FactoryStatus, factory_state
from dashboard.orchestration.existing_runtime_adapter import (
    AdapterBoundary,
    ExistingRuntimeAdapter,
    PATHWAY_COORDINATED,
    RandomRunPlan,
)
from dashboard.storage.repositories import RunRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunReadiness:
    """Whether a factory run could be started, and what is blocking it."""

    ready: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ready


@dataclass(frozen=True)
class RunDeletionResult:
    """What happened when one run's history row and artifacts were deleted."""

    run_id: str
    #: History row was found and removed from the dashboard database.
    row_deleted: bool
    #: Directories that existed and were removed.
    deleted_directories: tuple[Path, ...] = ()
    #: Directories the run recorded but that were already gone (deleted safely, no-op).
    missing_directories: tuple[Path, ...] = ()
    #: Paths this run recorded that fall outside the dashboard's own configured roots --
    #: skipped rather than deleted, since they are not artifacts this dashboard owns.
    skipped_directories: tuple[Path, ...] = ()
    #: Real failures (permission errors, a file in use, etc.), one message per path.
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


class RunManager:
    """Plans production runs and reconciles them with the dashboard's history."""

    def __init__(
        self,
        config: DashboardConfig,
        adapter: ExistingRuntimeAdapter,
        repository: RunRepository | None = None,
    ):
        self.config = config
        self.adapter = adapter
        self.repository = repository

    # -- readiness --------------------------------------------------------------------

    def check_readiness(self) -> RunReadiness:
        """Report whether the existing pipeline could run, without starting anything."""
        blockers: list[str] = []
        warnings: list[str] = []

        if self.repository is None:
            # Without history the dashboard cannot record the production day a run
            # would become, so it does not offer to start one.
            blockers.append(
                "Dashboard database unavailable, so the run could not be recorded."
            )

        state = factory_state(self.config.factory_path)
        if state.status == FactoryStatus.MISSING:
            blockers.append(f"No factory configuration at {state.path}")
        elif state.status == FactoryStatus.INVALID:
            blockers.append(
                f"Factory configuration is invalid: {'; '.join(state.validation.errors[:3])}"
            )
        else:
            warnings.extend(state.validation.warnings)
            if state.is_demo:
                warnings.append(
                    "The configured factory is a generated demo definition, not a real "
                    "plant configuration."
                )

        if not self.adapter.simulator_available():
            blockers.append(
                "The C++ simulator is not built under simulation/build. Build it before "
                "starting a run."
            )

        return RunReadiness(
            ready=not blockers, blockers=tuple(blockers), warnings=tuple(warnings)
        )

    # -- planning ---------------------------------------------------------------------

    def next_production_day(self) -> int:
        return self.repository.next_production_day() if self.repository else 1

    def _next_free_run_id(self, start_day: int) -> tuple[str, int]:
        """First production-day id whose destination directories are all unoccupied.

        History may lag the filesystem -- a run can have been executed from the CLI and
        not yet ingested. Skipping occupied ids keeps the emitted command runnable
        instead of colliding with `cli.py`'s "directory already contains files" guard.
        """
        day = start_day
        for _ in range(1000):
            run_id = f"production_day_{day:04d}"
            generated = self.config.generated_root / run_id
            runs = self.config.runs_root / run_id
            occupied = (generated.exists() and any(generated.iterdir())) or (
                runs / "run_0001"
            ).exists()
            if not occupied:
                return run_id, day
            day += 1
        return f"production_day_{day:04d}", day

    def plan_next_run(
        self,
        *,
        pathway: str = PATHWAY_COORDINATED,
        duration_ms: int | None = None,
        multiplier: float | None = None,
        particles: int = 3000,
    ) -> RandomRunPlan:
        """Describe the next production day's run. Executes nothing.

        The plan is preflighted against the configured factory so the command it carries
        is one that will actually run.
        """
        run_id, day = self._next_free_run_id(self.next_production_day())
        state = factory_state(self.config.factory_path)
        return self.adapter.plan_random_run(
            factory_path=self.config.factory_path,
            generated_dir=self.config.generated_root / run_id,
            runs_dir=self.config.runs_root / run_id,
            output_dir=self.config.predictions_root / run_id,
            run_id=run_id,
            seed=self.config.default_seed + day,
            duration_ms=duration_ms or self.config.default_duration_ms,
            multiplier=multiplier if multiplier is not None else self.config.default_multiplier,
            particles=particles,
            pathway=pathway,
            factory=state.data,
        )

    def start_run(self, plan: RandomRunPlan, *, on_output=None) -> None:
        """Hand execution to the existing system.

        The adapter invokes the established CLI command; it does not duplicate runtime
        coordination in the dashboard.
        """
        self.adapter.execute_planned_run(plan, on_output=on_output)

    # -- history ----------------------------------------------------------------------

    def current_run(self) -> Run | None:
        """The most recent recorded run, or None when history is empty."""
        return self.repository.latest_run() if self.repository else None

    def run_history(self, limit: int = 200) -> list[Run]:
        return self.repository.list_runs(limit=limit) if self.repository else []

    def record_planned_run(self, plan: RandomRunPlan, *, is_demo: bool = False) -> Run:
        """Persist a PENDING row so a started run is visible before it completes."""
        if self.repository is None:
            raise RuntimeError("RunManager has no repository; cannot record a run")
        day = self.repository.next_production_day()
        run = Run(
            run_id=plan.run_id,
            production_day=day,
            status=RunStatus.PENDING,
            scenario_reference=str(plan.generated_dir),
            scenario_description=f"Random scenario, seed {plan.seed}",
            multiplier=plan.multiplier if plan.multiplier is not None else 0.0,
            seed=plan.seed,
            duration_ms=plan.duration_ms,
            factory_path=str(plan.factory_path),
            artifact_path=str(plan.expected_run_dir),
            predictions_path=str(plan.output_dir),
            is_demo=is_demo,
            metadata={"pathway": plan.pathway, "command": plan.command},
        )
        return self.repository.upsert_run(run)

    def discover_unrecorded_runs(self) -> list[Path]:
        """Completed run directories on disk that history does not know about yet."""
        if self.repository is None:
            return []
        known = {run.artifact_path for run in self.repository.list_runs(limit=1000)}
        return [
            run.path
            for run in self.adapter.list_completed_runs(self.config.runs_root)
            if str(run.path) not in known
        ]

    # -- storage management -------------------------------------------------------------

    def _owned_run_directories(self, run: Run) -> list[tuple[Path, Path]]:
        """The directories one run could own, paired with the root that must contain them.

        Ownership is decided by containment under the dashboard's own configured roots,
        never by trusting a stored path outright -- a row with a path pointing somewhere
        else (hand-edited, or from a differently-configured dashboard instance) has that
        path skipped rather than deleted. ``generated_dir`` is not stored on ``Run`` at
        all; it is derived the same way :meth:`plan_next_run` derives it, from
        ``run_id`` under the configured generated root.
        """
        candidates: list[tuple[Path, Path]] = []
        if run.artifact_path:
            # artifact_path is "<runs_root>/<run_id>/run_0001"; the whole "<run_id>"
            # directory is what this dashboard created for the run.
            candidates.append((Path(run.artifact_path).parent, self.config.runs_root))
        if run.predictions_path:
            candidates.append((Path(run.predictions_path), self.config.predictions_root))
        candidates.append((self.config.generated_root / run.run_id, self.config.generated_root))
        return candidates

    def delete_run(self, run_id: str) -> RunDeletionResult:
        """Delete one run's history row and the artifacts this dashboard created for it.

        Never deletes the factory configuration, trained models, source code, or
        anything outside ``runs_root`` / ``generated_root`` / ``predictions_root``. A
        directory that is already gone is treated as successfully deleted, not an error.
        """
        if self.repository is None:
            raise RuntimeError("RunManager has no repository; cannot delete run history")

        run = self.repository.get_run(run_id)
        if run is None:
            return RunDeletionResult(run_id=run_id, row_deleted=False)

        deleted: list[Path] = []
        missing: list[Path] = []
        skipped: list[Path] = []
        errors: list[str] = []

        for directory, root in self._owned_run_directories(run):
            try:
                resolved_dir = directory.resolve()
                resolved_root = root.resolve()
            except OSError as error:
                errors.append(f"{directory}: {error}")
                continue
            # Must be a proper descendant of the root -- the root itself is never one
            # run's artifact, so equality is refused, not treated as owned.
            if resolved_root not in resolved_dir.parents:
                skipped.append(directory)
                continue
            if not directory.exists():
                missing.append(directory)
                continue
            try:
                shutil.rmtree(directory)
                deleted.append(directory)
            except FileNotFoundError:
                missing.append(directory)
            except OSError as error:
                errors.append(f"{directory}: {error}")

        self.repository.delete_run(run_id)
        return RunDeletionResult(
            run_id=run_id,
            row_deleted=True,
            deleted_directories=tuple(deleted),
            missing_directories=tuple(missing),
            skipped_directories=tuple(skipped),
            errors=tuple(errors),
        )

    def delete_all_runs(self, *, exclude_run_ids: set[str] = frozenset()) -> list[RunDeletionResult]:
        """Delete every recorded run's history row and owned artifacts.

        ``exclude_run_ids`` lets the caller keep a currently-executing run out of the
        purge -- deleting a running run's output directory out from under its writer
        would corrupt a live prediction stream.
        """
        if self.repository is None:
            raise RuntimeError("RunManager has no repository; cannot delete run history")
        runs = self.repository.list_runs(limit=100_000)
        return [
            self.delete_run(run.run_id) for run in runs if run.run_id not in exclude_run_ids
        ]
