"""Causal runtime feature builder for the finalized V5 defect model.

This is the inference-time counterpart of src/build_causal_features_v5.py.

Frozen task
-----------
At UNIT_ARRIVED to station S_k, predict whether the unit will eventually FAIL
the final INSPECTION station.

Runtime sources
---------------
* stations.csv              topology only
* units.csv                 supplier_batch, vehicle_model
* station_events stream     queue + completed-cycle history + prediction trigger
* sensor_readings stream    torque/vibration/temperature/current
* manual_checks stream      prior manual results

inspection_results.csv is deliberately NEVER read at runtime.

Important V5 sensor rule
------------------------
sensor_readings.csv has no unit_id. A reading is assigned to the unit actively
being processed at that station. It becomes legally usable only when that
PROCESSING_STARTED -> PROCESSING_COMPLETED interval finishes. This preserves the
same availability rule used by the corrected V5 training features.

There is NO Dark Zone logic in this module.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional
import re
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from ..src.feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES, RECENT_MS
except ImportError:  # direct legacy execution
    from feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES, RECENT_MS  # noqa: E402

ST_RE = re.compile(r"^S(\d+)", re.I)
SENSOR_SIGNALS = ("TORQUE", "VIBRATION", "TEMPERATURE", "CURRENT")

REQUIRED_STATION_COLUMNS = {"station_id", "archetype"}
REQUIRED_UNIT_COLUMNS = {"unit_id", "supplier_batch", "vehicle_model"}


def station_number(value: Any) -> int:
    m = ST_RE.match(str(value).strip())
    if not m:
        raise ValueError(f"Invalid station id: {value!r}")
    return int(m.group(1))


def _number_or_nan(value: Any) -> float:
    if value is None:
        return np.nan
    try:
        if pd.isna(value):
            return np.nan
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"mean": np.nan, "max": np.nan, "std": np.nan, "count": 0}
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    n = int(len(a))
    if n == 0:
        return {"mean": np.nan, "max": np.nan, "std": np.nan, "count": 0}
    return {
        "mean": float(np.mean(a)),
        "max": float(np.max(a)),
        "std": float(np.std(a, ddof=1)) if n > 1 else np.nan,
        "count": n,
    }


@dataclass
class DefectFeaturePacket:
    """One exact 30-feature row plus runtime metadata."""

    run_id: str
    unit_id: str
    station_id: str
    station_index: int
    prediction_time_ms: int
    event_id: Optional[str]
    event_sequence: Optional[int]
    final_station_id: str
    final_station_index: int
    features_30: dict[str, Any]
    route: str = "LIGHT"
    prediction_trigger: str = "UNIT_ARRIVED"
    state_confidence: float = 1.0
    data_source: str = "direct_station_event"
    estimated_transition_time_ms: Optional[int] = None
    transition_confirmation_lag_ms: int = 0


@dataclass
class _ActiveProcessing:
    unit_id: str
    station_id: str
    station_index: int
    start_time_ms: int
    start_event_sequence: int
    # (timestamp_ms, sensor_type, value)
    readings: list[tuple[int, str, float]] = field(default_factory=list)


@dataclass
class _CompletedProcessing:
    unit_id: str
    station_id: str
    station_index: int
    start_time_ms: int
    end_time_ms: int
    start_event_sequence: int


class DefectRuntimeFeatureBuilder:
    """Persistent live builder for the exact frozen V5 30-feature contract."""

    def __init__(
        self,
        stations_csv: str | Path,
        units_csv: str | Path,
        *,
        run_id: str = "LIVE",
    ):
        self.run_id = str(run_id)

        stations = pd.read_csv(stations_csv)
        missing_st = REQUIRED_STATION_COLUMNS - set(stations.columns)
        if missing_st:
            raise ValueError(
                "stations.csv missing required column(s): "
                + ", ".join(sorted(missing_st))
            )

        stations = stations.copy()
        stations["station_id"] = stations["station_id"].astype(str).str.strip()
        if stations["station_id"].duplicated().any():
            dup = stations.loc[
                stations["station_id"].duplicated(), "station_id"
            ].tolist()
            raise ValueError(f"Duplicate station IDs: {dup}")

        stations["station_index"] = stations["station_id"].map(station_number) - 1
        self._stations = stations.set_index("station_id", drop=False)
        self._station_count = int(len(stations))

        inspection = stations[
            stations["archetype"].astype(str).str.strip().str.upper().eq("INSPECTION")
        ].sort_values("station_index")
        if inspection.empty:
            raise ValueError("No INSPECTION station found in stations.csv")

        self.final_station_id = str(inspection.iloc[-1]["station_id"])
        self.final_station_index = int(inspection.iloc[-1]["station_index"])

        units = pd.read_csv(units_csv)
        missing_units = REQUIRED_UNIT_COLUMNS - set(units.columns)
        if missing_units:
            raise ValueError(
                "units.csv missing required column(s): "
                + ", ".join(sorted(missing_units))
            )

        units = units.copy()
        units["unit_id"] = units["unit_id"].astype(str)
        if units["unit_id"].duplicated().any():
            dup = units.loc[units["unit_id"].duplicated(), "unit_id"].tolist()
            raise ValueError(f"Duplicate unit IDs: {dup}")
        self._units = units.set_index("unit_id", drop=False)

        # Histories are intentionally simple append-only ledgers. Every query
        # re-applies the frozen station/time causality rules.
        self._sensor_history: dict[
            str, dict[str, list[tuple[int, int, float, int]]]
        ] = defaultdict(lambda: defaultdict(list))
        self._queue_history: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
        self._manual_history: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        self._cycle_history: dict[str, list[tuple[int, int, float]]] = defaultdict(list)

        # Processing state for sensor -> unit assignment.
        self._active: dict[tuple[str, str], _ActiveProcessing] = {}
        self._active_by_station: dict[str, set[tuple[str, str]]] = defaultdict(set)

        # DARK inference state is deliberately separate from direct LIGHT
        # processing intervals.  Internal PROCESSING_STARTED/COMPLETED truth is
        # never exposed.  Sensor observations attributed by the causal PF are
        # buffered until the inferred station transition/zone exit, matching the
        # V5 availability rule that a station's sensor history becomes usable only
        # after that processing interval has completed.
        self._dark_station_by_unit: dict[str, str] = {}
        # Causal time when the runtime learned/accepted the current DARK station.
        self._dark_entry_time_by_unit: dict[str, int] = {}
        # PF-estimated physical transition time.  Kept separately so late evidence
        # can recover dwell duration without ever rewinding the runtime clock.
        self._dark_estimated_entry_time_by_unit: dict[str, int] = {}
        self._dark_pending_sensors: dict[tuple[str, str], list[tuple[int, str, float, float]]] = defaultdict(list)

        # Keeps just-completed intervals long enough to handle a sensor reading
        # delivered later at the SAME timestamp. This makes replay tie-order
        # robust while preserving offline start <= sensor <= end semantics.
        self._completed_same_timestamp: dict[str, list[_CompletedProcessing]] = defaultdict(list)
        self._completed_timestamp: Optional[int] = None

        self._next_station_event_sequence = 0
        self._last_stream_timestamp: Optional[int] = None

        self._diagnostics = {
            "station_events": 0,
            "sensor_readings": 0,
            "manual_checks": 0,
            "predictions_emitted": 0,
            "sensor_readings_buffered": 0,
            "sensor_readings_committed": 0,
            "sensor_readings_unassigned": 0,
            "processing_starts": 0,
            "processing_completions": 0,
            "unmatched_processing_completions": 0,
            "duplicate_processing_starts": 0,
            "dark_inferred_arrivals": 0,
            "dark_inferred_completions": 0,
            "dark_cycle_intervals_from_pf_estimates": 0,
            "dark_cycle_intervals_causal_fallback": 0,
            "dark_sensor_readings_attributed": 0,
            "dark_sensor_readings_dropped_low_confidence": 0,
            "dark_sensor_readings_dropped_unclosed": 0,
        }

        if list(CATEGORICAL_FEATURES) != ["supplier_batch", "vehicle_model"]:
            raise RuntimeError("Unexpected V5 categorical feature contract")
        if len(DEFECT_FEATURES) != 30 or len(set(DEFECT_FEATURES)) != 30:
            raise RuntimeError("V5 runtime expects exactly 30 unique defect features")

    @property
    def feature_names(self) -> list[str]:
        return list(DEFECT_FEATURES)

    def refresh_units(self, units_csv: str | Path) -> int:
        """Refresh append-only simulator unit metadata during live operation.

        The simulator flushes ``units.csv`` before a unit's first public station
        event. Existing unit metadata is immutable: if a previously seen unit is
        rewritten with a different model or supplier batch, live inference stops
        rather than silently changing categorical features mid-run.
        """
        incoming = pd.read_csv(units_csv)
        missing = REQUIRED_UNIT_COLUMNS - set(incoming.columns)
        if missing:
            raise ValueError(
                "units.csv missing required column(s): "
                + ", ".join(sorted(missing))
            )
        incoming = incoming.copy()
        incoming["unit_id"] = incoming["unit_id"].astype(str)
        if incoming["unit_id"].duplicated().any():
            dup = incoming.loc[incoming["unit_id"].duplicated(), "unit_id"].tolist()
            raise ValueError(f"Duplicate unit IDs: {dup}")
        incoming = incoming.set_index("unit_id", drop=False)

        common = self._units.index.intersection(incoming.index)
        for uid in common:
            for col in ("supplier_batch", "vehicle_model"):
                old = str(self._units.at[uid, col])
                new = str(incoming.at[uid, col])
                if old != new:
                    raise ValueError(
                        f"units.csv mutated existing unit {uid!r}: {col} {old!r} -> {new!r}"
                    )

        before = len(self._units)
        self._units = incoming
        return int(len(self._units) - before)

    def reset(self) -> None:
        """Clear live histories while keeping the same station/unit configuration."""
        self._sensor_history.clear()
        self._queue_history.clear()
        self._manual_history.clear()
        self._cycle_history.clear()
        self._active.clear()
        self._active_by_station.clear()
        self._dark_station_by_unit.clear()
        self._dark_entry_time_by_unit.clear()
        self._dark_estimated_entry_time_by_unit.clear()
        self._dark_pending_sensors.clear()
        self._completed_same_timestamp.clear()
        self._completed_timestamp = None
        self._next_station_event_sequence = 0
        self._last_stream_timestamp = None
        for key in self._diagnostics:
            self._diagnostics[key] = 0

    def diagnostics(self) -> dict[str, Any]:
        return {
            **self._diagnostics,
            "active_processing_intervals": int(len(self._active)),
            "final_inspection_station": self.final_station_id,
            "final_station_index": self.final_station_index,
            "feature_count": len(self.feature_names),
        }

    def _station_index(self, station_id: Any) -> int:
        sid = str(station_id).strip()
        if sid not in self._stations.index:
            raise ValueError(f"Unknown station_id: {sid}")
        return int(self._stations.loc[sid, "station_index"])

    def _timestamp(self, value: Any) -> int:
        try:
            return int(pd.to_numeric(value, errors="raise"))
        except Exception as exc:
            raise ValueError(f"Invalid timestamp_ms: {value!r}") from exc

    def _advance_stream_clock(self, timestamp_ms: int) -> None:
        """Require globally nondecreasing live input timestamps."""
        if (
            self._last_stream_timestamp is not None
            and timestamp_ms < self._last_stream_timestamp
        ):
            raise ValueError(
                f"Out-of-order runtime input: {timestamp_ms} < "
                f"{self._last_stream_timestamp}. Feed defect streams in "
                "nondecreasing timestamp order."
            )

        if self._completed_timestamp is not None and timestamp_ms > self._completed_timestamp:
            self._completed_same_timestamp.clear()
            self._completed_timestamp = None

        self._last_stream_timestamp = timestamp_ms

    def _resolve_station_sequence(self, event: Mapping[str, Any]) -> int:
        raw = event.get("event_sequence")
        if raw is None:
            seq = self._next_station_event_sequence
        else:
            try:
                if pd.isna(raw):
                    seq = self._next_station_event_sequence
                else:
                    seq = int(raw)
            except Exception as exc:
                raise ValueError(f"Invalid event_sequence: {raw!r}") from exc

        self._next_station_event_sequence = max(
            self._next_station_event_sequence, seq + 1
        )
        return seq

    # ------------------------------------------------------------------
    # Frozen causal history queries
    # ------------------------------------------------------------------
    def _sensor_stats(
        self,
        unit_id: str,
        signal: str,
        prediction_time: int,
        prediction_station_index: int,
        *,
        window_ms: Optional[int] = None,
    ) -> dict[str, float | int]:
        lower = None if window_ms is None else prediction_time - int(window_ms)
        values: list[float] = []

        for t, sidx, value, available_at in self._sensor_history[unit_id][signal]:
            if t >= prediction_time:
                continue
            if sidx >= prediction_station_index:
                continue
            if available_at >= prediction_time:
                continue
            if lower is not None and t < lower:
                continue
            if np.isfinite(value):
                values.append(float(value))

        return _stats(values)

    def _queue_stats(
        self,
        unit_id: str,
        prediction_time: int,
        prediction_station_index: int,
    ) -> dict[str, float | int]:
        values = [
            float(value)
            for t, sidx, value in self._queue_history[unit_id]
            if t < prediction_time
            and sidx < prediction_station_index
            and np.isfinite(value)
        ]
        return _stats(values)

    def _build_features(
        self,
        *,
        unit_id: str,
        station_id: str,
        station_index: int,
        prediction_time: int,
    ) -> dict[str, Any]:
        if unit_id not in self._units.index:
            raise ValueError(f"Unit {unit_id!r} not present in units.csv")

        sf: dict[str, float] = {}
        for signal, prefix in (
            ("TORQUE", "torque"),
            ("VIBRATION", "vibration"),
            ("TEMPERATURE", "temperature"),
            ("CURRENT", "current"),
        ):
            hist = self._sensor_stats(
                unit_id,
                signal,
                prediction_time,
                station_index,
            )
            recent = self._sensor_stats(
                unit_id,
                signal,
                prediction_time,
                station_index,
                window_ms=RECENT_MS,
            )

            sf[f"{prefix}_mean_history"] = float(hist["mean"])
            sf[f"{prefix}_max_history"] = float(hist["max"])
            sf[f"{prefix}_std_history"] = float(hist["std"])
            sf[f"{prefix}_mean_recent"] = float(recent["mean"])
            sf[f"{prefix}_max_recent"] = float(recent["max"])

        qhist = self._queue_stats(unit_id, prediction_time, station_index)

        manual = [
            (t, sidx, result)
            for t, sidx, result in self._manual_history[unit_id]
            if t < prediction_time and sidx < station_index
        ]
        if not manual:
            manual_fail_count = 0.0
            manual_check_count = 0.0
            last_manual_fail = np.nan
            stations_since_last_manual_fail = np.nan
        else:
            manual.sort(key=lambda x: x[0])
            manual_check_count = float(len(manual))
            manual_fail_count = float(sum(result == "FAIL" for _, _, result in manual))
            last_manual_fail = 1.0 if manual[-1][2] == "FAIL" else 0.0
            failed = [(t, sidx) for t, sidx, result in manual if result == "FAIL"]
            stations_since_last_manual_fail = (
                float(station_index - failed[-1][1]) if failed else np.nan
            )

        cycles = [
            float(value)
            for t, sidx, value in self._cycle_history[unit_id]
            if t < prediction_time
            and sidx < station_index
            and np.isfinite(value)
        ]
        if cycles:
            cycle_history_max = float(np.max(cycles))
            cycle_history_std = (
                float(np.std(np.asarray(cycles, dtype=float), ddof=1))
                if len(cycles) > 1
                else np.nan
            )
        else:
            cycle_history_max = np.nan
            cycle_history_std = np.nan

        ui = self._units.loc[unit_id]

        torque_delta = (
            sf["torque_mean_recent"] - sf["torque_mean_history"]
            if np.isfinite(sf["torque_mean_recent"])
            and np.isfinite(sf["torque_mean_history"])
            else np.nan
        )
        vibration_delta = (
            sf["vibration_mean_recent"] - sf["vibration_mean_history"]
            if np.isfinite(sf["vibration_mean_recent"])
            and np.isfinite(sf["vibration_mean_history"])
            else np.nan
        )

        row = {
            "torque_delta_recent_vs_history": torque_delta,
            "manual_fail_count_cum": manual_fail_count,
            "prediction_station_index": station_index,
            "torque_mean_history": sf["torque_mean_history"],
            "line_fraction": station_index / max(1, self._station_count - 1),
            "last_manual_fail": last_manual_fail,
            "manual_check_count_cum": manual_check_count,
            "torque_mean_recent": sf["torque_mean_recent"],
            "queue_history_mean": qhist["mean"],
            "current_mean_recent": sf["current_mean_recent"],
            "current_missing_recent": (
                0.0 if np.isfinite(sf["current_mean_recent"]) else 1.0
            ),
            "vibration_delta_recent_vs_history": vibration_delta,
            "current_mean_history": sf["current_mean_history"],
            "torque_max_recent": sf["torque_max_recent"],
            "temperature_mean_history": sf["temperature_mean_history"],
            "torque_max_history": sf["torque_max_history"],
            "supplier_batch": ui["supplier_batch"],
            "current_max_history": sf["current_max_history"],
            "cycle_history_max": cycle_history_max,
            "temperature_max_recent": sf["temperature_max_recent"],
            "vibration_mean_history": sf["vibration_mean_history"],
            "temperature_max_history": sf["temperature_max_history"],
            "stations_since_last_manual_fail": stations_since_last_manual_fail,
            "vehicle_model": ui["vehicle_model"],
            "vibration_max_history": sf["vibration_max_history"],
            "vibration_max_recent": sf["vibration_max_recent"],
            "temperature_mean_recent": sf["temperature_mean_recent"],
            "torque_std_history": sf["torque_std_history"],
            "queue_history_std": qhist["std"],
            "cycle_history_std": cycle_history_std,
        }

        return {name: row[name] for name in DEFECT_FEATURES}

    # ------------------------------------------------------------------
    # Station events
    # ------------------------------------------------------------------
    def process_station_event(
        self,
        event: Mapping[str, Any] | pd.Series,
    ) -> Optional[DefectFeaturePacket]:
        e = dict(event)
        required = {"timestamp_ms", "station_id", "event_type"}
        missing = required - set(e)
        if missing:
            raise ValueError(
                "station event missing required field(s): "
                + ", ".join(sorted(missing))
            )

        t = self._timestamp(e["timestamp_ms"])
        self._advance_stream_clock(t)
        seq = self._resolve_station_sequence(e)
        station_id = str(e["station_id"]).strip()
        sidx = self._station_index(station_id)
        event_type = str(e["event_type"]).strip().upper()

        raw_uid = e.get("unit_id")
        unit_id = None
        if raw_uid is not None:
            try:
                if not pd.isna(raw_uid):
                    unit_id = str(raw_uid)
            except Exception:
                unit_id = str(raw_uid)

        self._diagnostics["station_events"] += 1

        # V5 queue history used every station-event row with a non-null queue value.
        queue_value = _number_or_nan(e.get("queue_length_after"))
        # Exact V5 training parity: queue history contains only the queue
        # encountered when this unit ARRIVED at a station.
        if (
            event_type == "UNIT_ARRIVED"
            and unit_id is not None
            and np.isfinite(queue_value)
        ):
            self._queue_history[unit_id].append((t, sidx, float(queue_value)))

        if event_type == "PROCESSING_STARTED" and unit_id is not None:
            self._start_processing(
                unit_id=unit_id,
                station_id=station_id,
                station_index=sidx,
                timestamp_ms=t,
                event_sequence=seq,
            )

        if event_type == "PROCESSING_COMPLETED" and unit_id is not None:
            cycle_value = _number_or_nan(e.get("cycle_time_ms"))
            if np.isfinite(cycle_value):
                self._cycle_history[unit_id].append((t, sidx, float(cycle_value)))

            self._complete_processing(
                unit_id=unit_id,
                station_id=station_id,
                timestamp_ms=t,
            )

        # Frozen prediction trigger: station ENTRY / UNIT_ARRIVED, through final QA.
        if (
            event_type == "UNIT_ARRIVED"
            and unit_id is not None
            and sidx <= self.final_station_index
        ):
            features = self._build_features(
                unit_id=unit_id,
                station_id=station_id,
                station_index=sidx,
                prediction_time=t,
            )
            self._diagnostics["predictions_emitted"] += 1
            return DefectFeaturePacket(
                run_id=self.run_id,
                unit_id=unit_id,
                station_id=station_id,
                station_index=sidx,
                prediction_time_ms=t,
                event_id=(
                    str(e["event_id"])
                    if e.get("event_id") is not None
                    and not pd.isna(e.get("event_id"))
                    else None
                ),
                event_sequence=seq,
                final_station_id=self.final_station_id,
                final_station_index=self.final_station_index,
                features_30=features,
                route="LIGHT",
                prediction_trigger="UNIT_ARRIVED",
                state_confidence=1.0,
                data_source="direct_station_event",
            )

        return None

    def _start_processing(
        self,
        *,
        unit_id: str,
        station_id: str,
        station_index: int,
        timestamp_ms: int,
        event_sequence: int,
    ) -> None:
        key = (unit_id, station_id)
        if key in self._active:
            # Offline V5 keeps the newer duplicate start. Discard readings attached
            # to the superseded incomplete interval rather than leaking them.
            self._diagnostics["duplicate_processing_starts"] += 1
            old = self._active[key]
            self._active_by_station[station_id].discard(key)

        self._active[key] = _ActiveProcessing(
            unit_id=unit_id,
            station_id=station_id,
            station_index=station_index,
            start_time_ms=timestamp_ms,
            start_event_sequence=event_sequence,
        )
        self._active_by_station[station_id].add(key)
        self._diagnostics["processing_starts"] += 1

    def _complete_processing(
        self,
        *,
        unit_id: str,
        station_id: str,
        timestamp_ms: int,
    ) -> None:
        key = (unit_id, station_id)
        active = self._active.pop(key, None)
        self._active_by_station[station_id].discard(key)

        if active is None:
            self._diagnostics["unmatched_processing_completions"] += 1
            return

        if timestamp_ms <= active.start_time_ms:
            # Same as offline V5: invalid/non-positive duration interval is not usable.
            return

        committed = 0
        for sensor_t, signal, value in active.readings:
            if sensor_t <= timestamp_ms and np.isfinite(value):
                self._sensor_history[unit_id][signal].append(
                    (
                        int(sensor_t),
                        int(active.station_index),
                        float(value),
                        int(timestamp_ms),
                    )
                )
                committed += 1

        self._diagnostics["sensor_readings_committed"] += committed
        self._diagnostics["processing_completions"] += 1

        completed = _CompletedProcessing(
            unit_id=unit_id,
            station_id=station_id,
            station_index=active.station_index,
            start_time_ms=active.start_time_ms,
            end_time_ms=timestamp_ms,
            start_event_sequence=active.start_event_sequence,
        )
        if self._completed_timestamp != timestamp_ms:
            self._completed_same_timestamp.clear()
            self._completed_timestamp = timestamp_ms
        self._completed_same_timestamp[station_id].append(completed)

    # ------------------------------------------------------------------
    # DARK inferred station lifecycle
    # ------------------------------------------------------------------
    def _close_inferred_dark_station(
        self,
        unit_id: str,
        station_id: str,
        timestamp_ms: int,
        *,
        estimated_exit_time_ms: int | None = None,
    ) -> None:
        """Close one inferred DARK station without conflating two clocks.

        ``timestamp_ms`` is the causal confirmation/availability time and therefore
        may never move backward. ``estimated_exit_time_ms`` is the PF's best
        estimate of when the physical transition happened.  For late PF revisions
        we use estimated physical entry/exit times for the cycle *duration*, but the
        ledger entry is appended only when this method is called causally.

        The cycle timestamp stored in ``_cycle_history`` is the physical estimated
        completion time.  That makes the newly learned completed upstream cycle
        usable by a prediction emitted at the current confirmation time, matching
        what the model expects, without changing any previously emitted row.
        """
        uid = str(unit_id)
        sid = str(station_id)
        causal_close = int(timestamp_ms)
        key = (uid, sid)
        causal_entry = self._dark_entry_time_by_unit.get(uid)
        estimated_entry = self._dark_estimated_entry_time_by_unit.get(uid)
        estimated_exit = (
            causal_close
            if estimated_exit_time_ms is None
            else min(int(estimated_exit_time_ms), causal_close)
        )
        sidx = self._station_index(sid)

        if estimated_entry is not None and estimated_exit > int(estimated_entry):
            dwell_ms = float(estimated_exit - int(estimated_entry))
            self._cycle_history[uid].append((estimated_exit, sidx, dwell_ms))
            self._diagnostics["dark_cycle_intervals_from_pf_estimates"] += 1
        elif causal_entry is not None and causal_close > int(causal_entry):
            # Defensive fallback for an estimator revision whose physical times are
            # non-positive/inconsistent. This still uses only causally elapsed time.
            dwell_ms = float(causal_close - int(causal_entry))
            self._cycle_history[uid].append((causal_close, sidx, dwell_ms))
            self._diagnostics["dark_cycle_intervals_causal_fallback"] += 1

        committed = 0
        for sensor_t, signal, value, confidence in self._dark_pending_sensors.pop(key, []):
            if sensor_t <= int(timestamp_ms) and np.isfinite(value):
                self._sensor_history[str(unit_id)][signal].append(
                    (int(sensor_t), sidx, float(value), int(timestamp_ms))
                )
                committed += 1
        self._diagnostics["sensor_readings_committed"] += committed
        self._diagnostics["dark_inferred_completions"] += 1

    def process_inferred_dark_arrival(
        self,
        *,
        unit_id: str,
        station_id: str,
        timestamp_ms: int,
        queue_estimate: Any = None,
        state_confidence: float = 0.0,
        trigger: str = "dark_inferred_station",
        estimated_transition_time_ms: int | None = None,
    ) -> Optional[DefectFeaturePacket]:
        """Create one causal V5 prediction at an inferred DARK station entry.

        This uses only PF-derived state from public boundaries/evidence.  No hidden
        simulator processing event is required.  A station transition closes the
        previous inferred interval, making its sensor/cycle history available to
        downstream predictions exactly at the causal transition time.
        """
        uid = str(unit_id)
        sid = str(station_id).strip()
        t = self._timestamp(timestamp_ms)
        estimate_t = (
            t if estimated_transition_time_ms is None
            else self._timestamp(estimated_transition_time_ms)
        )
        if estimate_t > t:
            raise ValueError(
                f"DARK estimated transition time {estimate_t} cannot be later than "
                f"causal confirmation time {t}"
            )
        self._advance_stream_clock(t)
        sidx = self._station_index(sid)
        if uid not in self._units.index:
            raise ValueError(f"Unit {uid!r} not present in units.csv")

        previous = self._dark_station_by_unit.get(uid)
        if previous == sid:
            return None
        if previous is not None:
            self._close_inferred_dark_station(
                uid, previous, t, estimated_exit_time_ms=estimate_t
            )

        self._dark_station_by_unit[uid] = sid
        self._dark_entry_time_by_unit[uid] = t
        self._dark_estimated_entry_time_by_unit[uid] = estimate_t
        queue = _number_or_nan(queue_estimate)
        if np.isfinite(queue):
            self._queue_history[uid].append((t, sidx, float(queue)))

        features = self._build_features(
            unit_id=uid, station_id=sid, station_index=sidx, prediction_time=t
        )
        self._diagnostics["predictions_emitted"] += 1
        self._diagnostics["dark_inferred_arrivals"] += 1
        return DefectFeaturePacket(
            run_id=self.run_id,
            unit_id=uid,
            station_id=sid,
            station_index=sidx,
            prediction_time_ms=t,
            event_id=None,
            event_sequence=None,
            final_station_id=self.final_station_id,
            final_station_index=self.final_station_index,
            features_30=features,
            route="DARK_INFERRED",
            prediction_trigger=str(trigger),
            state_confidence=float(np.clip(state_confidence, 0.0, 1.0)),
            data_source="particle_filter_estimate",
            estimated_transition_time_ms=estimate_t,
            transition_confirmation_lag_ms=max(0, t - estimate_t),
        )

    def process_dark_sensor_reading(
        self,
        reading: Mapping[str, Any] | pd.Series,
        *,
        unit_id: str,
        attribution_confidence: float,
        min_confidence: float = 0.55,
    ) -> bool:
        """Buffer one observable DARK sensor reading for a PF-attributed unit.

        Association is performed outside this feature builder by the DARK PF.
        Low-confidence readings are intentionally dropped rather than guessed.
        Accepted readings remain unavailable to model features until the inferred
        station transition/zone exit closes that DARK interval.
        """
        r = dict(reading)
        t = self._timestamp(r.get("timestamp_ms"))
        self._advance_stream_clock(t)
        sid = str(r.get("station_id", "")).strip()
        self._station_index(sid)
        signal = str(r.get("sensor_type", "")).strip().upper()
        value = _number_or_nan(r.get("value"))
        conf = float(attribution_confidence)
        self._diagnostics["sensor_readings"] += 1
        if signal not in SENSOR_SIGNALS or not np.isfinite(value):
            return False
        if not np.isfinite(conf) or conf < float(min_confidence):
            self._diagnostics["sensor_readings_unassigned"] += 1
            self._diagnostics["dark_sensor_readings_dropped_low_confidence"] += 1
            return False

        uid = str(unit_id)
        self._dark_pending_sensors[(uid, sid)].append(
            (t, signal, float(value), conf)
        )
        self._diagnostics["sensor_readings_buffered"] += 1
        self._diagnostics["dark_sensor_readings_attributed"] += 1
        return True

    def finalize_dark_vehicle(self, unit_id: str, timestamp_ms: int) -> None:
        """Close the currently inferred DARK interval at an observable zone exit."""
        uid = str(unit_id)
        t = self._timestamp(timestamp_ms)
        self._advance_stream_clock(t)
        sid = self._dark_station_by_unit.pop(uid, None)
        if sid is not None:
            self._close_inferred_dark_station(
                uid, sid, t, estimated_exit_time_ms=t
            )
        self._dark_entry_time_by_unit.pop(uid, None)
        self._dark_estimated_entry_time_by_unit.pop(uid, None)

        # Any other station buffer for this unit was never accepted as a causal
        # station transition. Drop it explicitly at zone exit rather than letting
        # ambiguous telemetry leak into future features or accumulate in memory.
        leftovers = [key for key in self._dark_pending_sensors if key[0] == uid]
        for key in leftovers:
            self._diagnostics["dark_sensor_readings_dropped_unclosed"] += len(
                self._dark_pending_sensors.get(key, [])
            )
            self._dark_pending_sensors.pop(key, None)

    # ------------------------------------------------------------------
    # Sensor readings
    # ------------------------------------------------------------------
    def process_sensor_reading(
        self,
        reading: Mapping[str, Any] | pd.Series,
    ) -> None:
        r = dict(reading)
        required = {"timestamp_ms", "station_id", "sensor_type", "value"}
        missing = required - set(r)
        if missing:
            raise ValueError(
                "sensor reading missing required field(s): "
                + ", ".join(sorted(missing))
            )

        t = self._timestamp(r["timestamp_ms"])
        self._advance_stream_clock(t)
        station_id = str(r["station_id"]).strip()
        self._station_index(station_id)  # validates station
        signal = str(r["sensor_type"]).strip().upper()
        value = _number_or_nan(r["value"])

        self._diagnostics["sensor_readings"] += 1

        if signal not in SENSOR_SIGNALS or not np.isfinite(value):
            return

        # Candidate intervals that contain t. Prefer latest processing_start,
        # exactly like the offline station-wise merge_asof assignment.
        active_candidates = [
            self._active[key]
            for key in self._active_by_station.get(station_id, set())
            if self._active[key].start_time_ms <= t
        ]
        completed_candidates = [
            c
            for c in self._completed_same_timestamp.get(station_id, [])
            if c.start_time_ms <= t <= c.end_time_ms
        ]

        candidates: list[tuple[int, int, str, Any]] = []
        for a in active_candidates:
            candidates.append(
                (a.start_time_ms, a.start_event_sequence, "active", a)
            )
        for c in completed_candidates:
            candidates.append(
                (c.start_time_ms, c.start_event_sequence, "completed", c)
            )

        if not candidates:
            self._diagnostics["sensor_readings_unassigned"] += 1
            return

        _, _, kind, chosen = max(candidates, key=lambda x: (x[0], x[1]))

        if kind == "active":
            chosen.readings.append((t, signal, float(value)))
            self._diagnostics["sensor_readings_buffered"] += 1
            return

        # Late same-timestamp sensor after PROCESSING_COMPLETED. It is still
        # causally unavailable until completion, so commit with available_at=end.
        self._sensor_history[chosen.unit_id][signal].append(
            (
                t,
                int(chosen.station_index),
                float(value),
                int(chosen.end_time_ms),
            )
        )
        self._diagnostics["sensor_readings_committed"] += 1

    # ------------------------------------------------------------------
    # Manual checks
    # ------------------------------------------------------------------
    def process_manual_check(
        self,
        check: Mapping[str, Any] | pd.Series,
    ) -> None:
        c = dict(check)
        required = {"timestamp_ms", "station_id", "unit_id", "result"}
        missing = required - set(c)
        if missing:
            raise ValueError(
                "manual check missing required field(s): "
                + ", ".join(sorted(missing))
            )

        t = self._timestamp(c["timestamp_ms"])
        self._advance_stream_clock(t)
        station_id = str(c["station_id"]).strip()
        sidx = self._station_index(station_id)
        unit_id = str(c["unit_id"])
        result = str(c["result"]).strip().upper()

        self._diagnostics["manual_checks"] += 1

        if result not in {"PASS", "FAIL"}:
            return
        self._manual_history[unit_id].append((t, sidx, result))
