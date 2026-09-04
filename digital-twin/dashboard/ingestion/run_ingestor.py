"""Ingestion of completed run artifacts into the dashboard's run history.

Direction of flow is one-way and strictly downstream::

    factory.json -> existing scenario generator -> existing random-run / simulation
    -> existing prediction/runtime outputs -> completed run artifacts
    -> [ this module ] -> SQLite -> stakeholder views

Two rules shape everything here:

* A run enters the database only once its artifacts satisfy the existing completed-run
  contract. Partial or in-flight runs are refused, not guessed at.
* Nothing is invented. There is no synthetic history; :func:`rebuild_from_artifacts`
  reconstructs the database purely from directories that already exist on disk, which
  is what makes the database safe to delete.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dashboard.config import DashboardConfig
from dashboard.domain.run import Run, RunStatus
from dashboard.ingestion.bottleneck_reader import read_bottleneck_summary
from dashboard.ingestion.defect_reader import read_defect_summary
from dashboard.ingestion.runtime_reader import (
    HEALTH_DEGRADED,
    HEALTH_PASS,
    read_run_metadata,
    read_system_health,
    read_system_manifest,
)
from dashboard.orchestration.existing_runtime_adapter import ExistingRuntimeAdapter
from dashboard.storage.repositories import RunRepository

logger = logging.getLogger(__name__)


class IncompleteRunError(ValueError):
    """Raised when a run directory does not yet satisfy the completed-run contract."""

    def __init__(self, run_dir: Path, missing: tuple[str, ...]):
        super().__init__(
            f"{run_dir} is not a completed simulator run; missing: {', '.join(missing)}"
        )
        self.run_dir = run_dir
        self.missing = missing


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of rebuilding or ingesting history."""

    ingested: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.ingested)


def factory_fingerprint(factory_path: str | Path) -> str | None:
    """Short content hash of a factory file, so a run records which plant it ran on."""
    path = Path(factory_path)
    if not path.is_file():
        return None
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return digest[:16]


def _artifact_timestamp(path: Path) -> str | None:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()


def derive_run_id(run_dir: Path, runs_root: Path) -> str:
    """Stable, unique id for a completed run directory.

    The existing pipeline writes every single-run batch as ``<batch>/run_0001``, so the
    directory's own name collides across batches. Using the path relative to the runs
    root keeps ids unique and traceable back to the artifacts they describe.
    """
    run_dir = Path(run_dir)
    try:
        relative = run_dir.resolve().relative_to(Path(runs_root).resolve())
    except (ValueError, OSError):
        return run_dir.name
    return "/".join(relative.parts) if relative.parts else run_dir.name


def index_prediction_outputs(predictions_root: Path) -> dict[str, Path]:
    """Map completed run directories to the output directory holding their predictions.

    ``system_run_manifest.json`` records the ``run_dir`` its predictions came from, which
    is authoritative -- the coordinated runtime's output directory is named by run id,
    not by the run directory, so matching on names alone is unreliable.
    """
    index: dict[str, Path] = {}
    root = Path(predictions_root)
    if not root.is_dir():
        return index
    try:
        candidates = [root, *(child for child in root.iterdir() if child.is_dir())]
    except OSError:
        return index
    for directory in candidates:
        manifest = directory / "system_run_manifest.json"
        if not manifest.is_file():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_dir = payload.get("run_dir") if isinstance(payload, dict) else None
        if run_dir:
            index[str(Path(str(run_dir)).resolve())] = directory
    return index


class RunIngestor:
    """Turns completed run artifacts into rows of dashboard run history."""

    def __init__(
        self,
        config: DashboardConfig,
        repository: RunRepository,
        adapter: ExistingRuntimeAdapter | None = None,
    ):
        self.config = config
        self.repository = repository
        self.adapter = adapter or ExistingRuntimeAdapter(config.project_root)

    # -- single run --------------------------------------------------------------------

    def ingest_completed_run(
        self,
        run_dir: str | Path,
        *,
        predictions_dir: str | Path | None = None,
        factory_path: str | Path | None = None,
        production_day: int | None = None,
        run_id: str | None = None,
        multiplier: float | None = None,
        particles: int | None = None,
        is_demo: bool = False,
    ) -> Run:
        """Record one completed run. Raises :class:`IncompleteRunError` if premature."""
        run_dir = Path(run_dir).resolve()
        missing = self.adapter.missing_run_files(run_dir)
        if missing:
            raise IncompleteRunError(run_dir, missing)

        metadata = read_run_metadata(run_dir) or {}
        factory = Path(factory_path) if factory_path else Path(self.config.factory_path)
        predictions = Path(predictions_dir) if predictions_dir else None

        summaries: dict[str, Any] = {}
        health: dict[str, Any] | None = None
        manifest: dict[str, Any] | None = None
        status = RunStatus.COMPLETED
        if predictions is not None:
            paths = self.adapter.prediction_output_paths(predictions)
            bottleneck = read_bottleneck_summary(paths["bottleneck"])
            defect = read_defect_summary(paths["defect"])
            summaries = {
                "bottleneck_stream": bottleneck.as_dict(),
                "defect_stream": defect.as_dict(),
            }
            health = read_system_health(predictions)
            manifest = read_system_manifest(predictions)
            # system_health.json stays authoritative: only PASS means healthy. A run
            # whose coordinated stage failed must never read as COMPLETED.
            overall = (health or {}).get("overall_status")
            if overall and overall != HEALTH_PASS:
                status = (
                    RunStatus.PARTIAL if overall == HEALTH_DEGRADED else RunStatus.FAILED
                )
            # The two streams stay separate; a run is PARTIAL when only one is present.
            elif bottleneck.exists != defect.exists:
                status = RunStatus.PARTIAL

        existing = self.repository.find_by_artifact_path(str(run_dir))
        if production_day is None:
            production_day = (
                existing.production_day if existing else self.repository.next_production_day()
            )

        completed_at = _artifact_timestamp(run_dir / "run_metadata.json")
        run = Run(
            run_id=run_id
            or (existing.run_id if existing else derive_run_id(run_dir, self.config.runs_root)),
            production_day=production_day,
            status=status,
            scenario_name=metadata.get("run_id"),
            scenario_reference=str(run_dir),
            scenario_description=self._describe_scenario(metadata),
            multiplier=multiplier if multiplier is not None else 0.0,
            seed=metadata.get("random_seed"),
            duration_ms=metadata.get("simulation_duration_ms"),
            factory_path=str(factory),
            factory_fingerprint=factory_fingerprint(factory),
            artifact_path=str(run_dir),
            predictions_path=str(predictions) if predictions else None,
            completed_at=completed_at,
            is_demo=is_demo,
            metadata={
                "run_metadata": metadata,
                "coordinated_ready": self.adapter.is_coordinated_ready(run_dir),
                "missing_coordinated_files": list(
                    self.adapter.missing_run_files(run_dir, coordinated=True)
                ),
                "system_health_overall_status": (health or {}).get("overall_status"),
                "system_run_manifest_present": manifest is not None,
                "particles": particles or (manifest or {}).get("particles"),
                "system_run_manifest": manifest or {},
                **summaries,
            },
        )
        return self.repository.upsert_run(run)

    @staticmethod
    def _describe_scenario(metadata: dict[str, Any]) -> str:
        seed = metadata.get("random_seed")
        duration = metadata.get("simulation_duration_ms")
        units = metadata.get("units_created")
        parts = []
        if seed is not None:
            parts.append(f"seed {seed}")
        if duration is not None:
            parts.append(f"{int(duration) / 3_600_000:.1f}h simulated")
        if units is not None:
            parts.append(f"{units} units")
        return ", ".join(parts) if parts else "Completed simulator run"

    @staticmethod
    def _locate_predictions(
        run_dir: Path, predictions_root: Path, manifest_index: dict[str, Path]
    ) -> Path | None:
        """Find the prediction outputs belonging to one completed run directory.

        The manifest index is authoritative. The name-based fallbacks cover runs whose
        coordinated stage has not finished writing a manifest: the runtime's output
        directory is named by run id, which for the standard ``<batch>/run_0001`` layout
        is the batch name, not the run directory's own name.
        """
        resolved = str(run_dir.resolve())
        if resolved in manifest_index:
            return manifest_index[resolved]
        for candidate in (
            predictions_root / run_dir.parent.name,
            predictions_root / run_dir.name,
        ):
            if candidate.is_dir():
                return candidate
        return None

    # -- bulk rebuild -------------------------------------------------------------------

    def rebuild_from_artifacts(
        self,
        runs_root: str | Path | None = None,
        *,
        predictions_root: str | Path | None = None,
        clear_existing: bool = True,
    ) -> IngestionResult:
        """Rebuild the whole run history from completed run directories on disk.

        This is what makes the dashboard database disposable: delete it, rebuild it, and
        the same history comes back from the artifacts the existing system produced.
        Production days are assigned in artifact-completion order.
        """
        root = Path(runs_root) if runs_root else Path(self.config.runs_root)
        predictions_root = (
            Path(predictions_root) if predictions_root else Path(self.config.predictions_root)
        )
        discovered = self.adapter.list_completed_runs(root)
        if clear_existing:
            self.repository.delete_all()

        ordered = sorted(
            discovered,
            key=lambda run: (
                _artifact_timestamp(run.path / "run_metadata.json") or "",
                run.path.name,
            ),
        )

        manifest_index = index_prediction_outputs(predictions_root)

        ingested: list[str] = []
        skipped: list[str] = []
        for index, completed in enumerate(ordered, start=1):
            predictions = self._locate_predictions(completed.path, predictions_root, manifest_index)
            try:
                run = self.ingest_completed_run(
                    completed.path,
                    predictions_dir=predictions,
                    production_day=index,
                )
            except (IncompleteRunError, OSError) as error:
                logger.warning("skipping %s: %s", completed.path, error)
                skipped.append(str(completed.path))
                continue
            ingested.append(run.run_id)
        return IngestionResult(ingested=tuple(ingested), skipped=tuple(skipped))
