"""Load a run's two prediction streams into the existing analytics state objects.

This is the single seam the stakeholder views use to turn a
:class:`dashboard.domain.run.Run` into something queryable. It reuses the existing
readers -- it does not add a competing JSONL parser:

* :class:`dashboard.live.stream.JsonlTailer` reads the file the runtime wrote,
* :class:`dashboard.live.bottleneck_state.LiveBottleneckState` /
  :class:`dashboard.live.defect_state.LiveDefectState` accumulate the per-station /
  per-unit history and descriptive analytics,
* :func:`dashboard.ingestion.runtime_reader.health_view` reads
  ``system_health.json`` for the authoritative coordinated-runtime status.

The raw latest record per station / unit is kept alongside the state objects only
because the analytics points intentionally do not carry the SHAP driver lists, and
the Supervisor / Plant Manager views need "top driver(s)".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dashboard.ingestion.runtime_reader import HealthView, health_view, read_system_health
from dashboard.live.bottleneck_state import LiveBottleneckState
from dashboard.live.defect_state import LiveDefectState
from dashboard.live.stream import JsonlTailer

#: Stream filenames under a run's prediction output directory. Mirrors
#: ``system_runtime.output_paths`` / ``dashboard.live.session``.
BOTTLENECK_STREAM = "bottleneck_predictions.jsonl"
DEFECT_STREAM = "defect_predictions.jsonl"

#: ``state_confidence`` at or below this is surfaced as a low-confidence prediction
#: (reconstructed / DARK state), never silently trusted as direct telemetry.
LOW_CONFIDENCE = 0.75

SCOPE_CURRENT = "Current Run"
SCOPE_ALL = "All Runs"
_SCOPE_DAY_PREFIX = "Production Day "


def read_stream_records(path: str | Path) -> list[dict[str, Any]]:
    """Every JSON object in a prediction stream, in emission order. Missing = []."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    return JsonlTailer(file_path).read_all().records


def _humanise(feature: str) -> str:
    return feature.replace("_", " ").strip().capitalize() or feature


#: SHAP features that are not an actionable "driver" for an operator -- the station's
#: own identity always dominates the model but tells a supervisor nothing to do.
_NON_ACTIONABLE_DRIVERS = {"station_id", "station_index", "prediction_station_index"}


def bottleneck_drivers(record: dict[str, Any], *, limit: int = 2) -> list[str]:
    """Top risk-raising driver names from a bottleneck record's ``explanation``.

    Prefers drivers whose ``direction`` is ``increases_risk``; falls back to the
    first few listed when none are marked. The station's own identity is dropped --
    it dominates every prediction but is not something an operator can act on.
    Returns human-readable feature names.
    """
    raw = ((record.get("explanation") or {}).get("top_drivers")) or []
    raising = [
        d for d in raw
        if isinstance(d, dict)
        and d.get("direction") != "decreases_risk"
        and d.get("feature")
        and d.get("feature") not in _NON_ACTIONABLE_DRIVERS
    ]
    chosen = raising or [
        d for d in raw
        if isinstance(d, dict) and d.get("feature") and d.get("feature") not in _NON_ACTIONABLE_DRIVERS
    ]
    return [_humanise(str(d["feature"])) for d in chosen[:limit]]


def defect_drivers(record: dict[str, Any], *, limit: int = 2) -> list[str]:
    """Top risk-raising driver labels from a defect record's ``top_risk_drivers``."""
    raw = record.get("top_risk_drivers") or []
    out: list[str] = []
    for driver in raw:
        if not isinstance(driver, dict):
            continue
        label = driver.get("label") or driver.get("feature")
        if label:
            out.append(str(label))
        if len(out) >= limit:
            break
    return out


@dataclass
class RunStreams:
    """One run's bottleneck + defect history, plus its coordinated-runtime health.

    ``bottleneck`` and ``defect`` are the existing analytics state objects, already
    populated. They are never merged.
    """

    run: Any  # dashboard.domain.run.Run -- imported lazily to keep this module light
    bottleneck: LiveBottleneckState
    defect: LiveDefectState
    health: HealthView
    health_raw: dict[str, Any] = field(default_factory=dict)
    bottleneck_exists: bool = False
    defect_exists: bool = False
    #: station_id -> the last raw bottleneck record seen for it (for SHAP drivers).
    latest_bottleneck_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: unit_id -> the last raw defect record seen for it (for SHAP drivers).
    latest_defect_records: dict[str, dict[str, Any]] = field(default_factory=dict)

    # -- identity -------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return str(getattr(self.run, "run_id", "—"))

    @property
    def production_day(self) -> int:
        return int(getattr(self.run, "production_day", 0) or 0)

    @property
    def is_demo(self) -> bool:
        return bool(getattr(self.run, "is_demo", False))

    # -- health ------------------------------------------------------------------

    @property
    def degraded(self) -> bool:
        """True when the coordinated runtime is recorded as anything but PASS.

        ``system_health.json`` stays authoritative; absence is treated as "unknown",
        not as failure.
        """
        return self.health.available and not self.health.is_pass

    def subsystem_status(self, name: str) -> str:
        block = self.health_raw.get(name)
        if isinstance(block, dict) and block.get("status"):
            return str(block["status"])
        if self.health.available:
            return "PASS" if self.health.is_pass else "UNKNOWN"
        return "—"

    # -- throughput ------------------------------------------------------------------

    def units_produced(self) -> int:
        """Best available unit count: simulator metadata first, else distinct defect units."""
        metadata = getattr(self.run, "metadata", {}) or {}
        run_metadata = metadata.get("run_metadata") or {}
        for key in ("units_created", "units_completed", "unit_count", "units"):
            value = run_metadata.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
        return len(self.defect.units)


def _predictions_dir(run: Any) -> Path | None:
    raw = getattr(run, "predictions_path", None)
    return Path(raw) if raw else None


def load_run_streams(run: Any) -> RunStreams:
    """Build a :class:`RunStreams` for one run. Missing files degrade to empty state."""
    predictions_dir = _predictions_dir(run)
    bottleneck_rows: list[dict[str, Any]] = []
    defect_rows: list[dict[str, Any]] = []
    if predictions_dir is not None:
        bottleneck_rows = read_stream_records(predictions_dir / BOTTLENECK_STREAM)
        defect_rows = read_stream_records(predictions_dir / DEFECT_STREAM)

    bottleneck = LiveBottleneckState()
    bottleneck.ingest(bottleneck_rows)
    defect = LiveDefectState()
    defect.ingest(defect_rows)

    latest_bottleneck: dict[str, dict[str, Any]] = {}
    for row in bottleneck_rows:
        station_id = row.get("station_id")
        if station_id is not None:
            latest_bottleneck[str(station_id)] = row
    latest_defect: dict[str, dict[str, Any]] = {}
    for row in defect_rows:
        unit_id = row.get("unit_id")
        if unit_id is not None:
            latest_defect[str(unit_id)] = row

    health = health_view(predictions_dir) if predictions_dir is not None else HealthView(available=False)
    health_raw = (read_system_health(predictions_dir) or {}) if predictions_dir is not None else {}

    return RunStreams(
        run=run,
        bottleneck=bottleneck,
        defect=defect,
        health=health,
        health_raw=health_raw,
        bottleneck_exists=bool(
            predictions_dir is not None and (predictions_dir / BOTTLENECK_STREAM).is_file()
        ),
        defect_exists=bool(
            predictions_dir is not None and (predictions_dir / DEFECT_STREAM).is_file()
        ),
        latest_bottleneck_records=latest_bottleneck,
        latest_defect_records=latest_defect,
    )


def load_scope(runs: list[Any]) -> list[RunStreams]:
    """Load every run in a scope, oldest production day first for trend charts."""
    ordered = sorted(runs, key=lambda run: getattr(run, "production_day", 0) or 0)
    return [load_run_streams(run) for run in ordered]


# -- scope selection --------------------------------------------------------------


def scope_options(runs: list[Any]) -> list[str]:
    """Choices for a scope selector: Current Run, All Runs, then each production day."""
    options = [SCOPE_CURRENT, SCOPE_ALL]
    options += [
        f"{_SCOPE_DAY_PREFIX}{run.production_day}"
        for run in sorted(runs, key=lambda run: getattr(run, "production_day", 0) or 0)
    ]
    return options


def resolve_scope(
    runs: list[Any], choice: str | None, *, selected_run_id: str | None = None
) -> list[Any]:
    """Turn a scope selector choice into the concrete list of runs it covers.

    ``runs`` is expected in the repository's order (most recent production day
    first). "Current Run" honours ``selected_run_id`` when it is still present,
    otherwise the most recent run. An unknown choice falls back to the current run.
    """
    if not runs:
        return []
    if choice == SCOPE_ALL:
        return list(runs)
    if choice and choice.startswith(_SCOPE_DAY_PREFIX):
        try:
            day = int(choice[len(_SCOPE_DAY_PREFIX):])
        except ValueError:
            day = None
        picked = [run for run in runs if getattr(run, "production_day", None) == day]
        return picked or [runs[0]]
    if selected_run_id:
        picked = [run for run in runs if getattr(run, "run_id", None) == selected_run_id]
        if picked:
            return picked
    return [runs[0]]
