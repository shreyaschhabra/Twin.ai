"""Runtime Light-Zone bottleneck feature builder.

This module is the inference-time counterpart of the frozen
``build_causal_datasets.py::bottleneck_rows`` logic.

It intentionally:
- builds ONLY the 28 bottleneck features;
- keeps the original 10-minute and previous-10-minute causal windows;
- keeps the original queue/cycle/rate/slope/uncertainty formulas;
- never creates ``y_bottleneck`` and never reads future data;
- has no defect, sensor_reading, manual_check, inspection, or units logic.

Typical runtime use
-------------------
    builder = LightZoneRuntimeFeatureBuilder.from_stations_csv("stations.csv")
    X = builder.process_event(event_dict)   # one-row DataFrame, exact 28 columns
    prediction = model.predict_proba(X)

The runtime controller should call this builder only for LIGHT stations.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


SCHEMA_VERSION = "causal-features-v1"
RECENT_MS = 600_000  # exact frozen 10-minute window

# Exact frozen order from validate_causal_dataset_contract.py.
BOTTLENECK_FEATURES = [
    "capacity_headroom",
    "station_id",
    "base_cycle_time_ms",
    "station_archetype",
    "configured_cycle_std_ms",
    "station_index",
    "buffer_capacity",
    "line_fraction",
    "queue_max_10m",
    "queue_mean_10m",
    "current_occupancy",
    "queue_std_10m",
    "capacity_utilization",
    "arrival_rate_per_min_prev10m",
    "service_rate_per_min_prev10m",
    "service_rate_per_min_10m",
    "arrival_rate_per_min_10m",
    "utilization_headroom",
    "cycle_max_10m",
    "flow_pressure_10m",
    "queue_delta_10m",
    "cycle_mean_10m",
    "queue_slope_10m",
    "net_flow_rate_10m",
    "cycle_std_10m",
    "state_confidence",
    "progress_std",
    "eta_std",
]

REQUIRED_STATION_COLUMNS = {
    "station_id",
    "buffer_capacity",
    "base_cycle_time_ms",
    "archetype",
    "cycle_time_std_ms",
}

REQUIRED_EVENT_FIELDS = {
    "timestamp_ms",
    "station_id",
    "event_type",
}


def station_num(value: Any) -> int:
    """Preserve the original station-index conversion exactly."""
    return int(str(value).replace("S", ""))


def _number_or_nan(value: Any) -> float:
    """Equivalent to pd.to_numeric(..., errors='coerce') for one value."""
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


def _prefix_range_stats(
    values: list[float],
    count_prefix: list[int],
    sum_prefix: list[float],
    sum2_prefix: list[float],
    lo: int,
    hi: int,
) -> tuple[float, float, float]:
    """Exact frozen ``range_stats`` prefix-sum semantics."""
    n = int(count_prefix[hi] - count_prefix[lo])
    if not n:
        return np.nan, np.nan, np.nan

    total = sum_prefix[hi] - sum_prefix[lo]
    total2 = sum2_prefix[hi] - sum2_prefix[lo]
    mean = total / n
    std = (
        np.sqrt(max(0.0, (total2 - n * mean * mean) / (n - 1)))
        if n > 1
        else np.nan
    )
    maximum = float(np.nanmax(np.asarray(values[lo:hi], dtype=float)))
    return float(mean), float(std) if np.isfinite(std) else np.nan, maximum


@dataclass
class _StationHistory:
    times: list[int]
    sequences: list[int]
    queues: list[float]
    cycles: list[float]
    event_types: list[str]
    arrivals_prefix: list[int]
    services_prefix: list[int]
    queue_count_prefix: list[int]
    queue_sum_prefix: list[float]
    queue_sum2_prefix: list[float]
    cycle_count_prefix: list[int]
    cycle_sum_prefix: list[float]
    cycle_sum2_prefix: list[float]
    last_direct_queue: float
    last_observed_index: int

    @classmethod
    def empty(cls) -> "_StationHistory":
        return cls(
            times=[],
            sequences=[],
            queues=[],
            cycles=[],
            event_types=[],
            arrivals_prefix=[0],
            services_prefix=[0],
            queue_count_prefix=[0],
            queue_sum_prefix=[0.0],
            queue_sum2_prefix=[0.0],
            cycle_count_prefix=[0],
            cycle_sum_prefix=[0.0],
            cycle_sum2_prefix=[0.0],
            last_direct_queue=0.0,
            last_observed_index=-1,
        )


class LightZoneRuntimeFeatureBuilder:
    """Build the frozen 28 bottleneck features one station event at a time.

    Events must arrive in causal order for each station. Equal timestamps are
    allowed and are ordered by ``event_sequence``. If ``event_sequence`` is
    absent, a global sequence is assigned in arrival order, matching the
    offline builder's ``np.arange(len(station_events))`` behavior.
    """

    def __init__(self, stations: pd.DataFrame):
        missing = REQUIRED_STATION_COLUMNS - set(stations.columns)
        if missing:
            raise ValueError(
                "stations data is missing required column(s): "
                + ", ".join(sorted(missing))
            )

        st = stations.copy()
        st["station_id"] = st["station_id"].astype(str).str.strip()

        if st["station_id"].duplicated().any():
            duplicates = st.loc[st["station_id"].duplicated(), "station_id"].tolist()
            raise ValueError(f"Duplicate station IDs found: {duplicates}")

        # Preserve the offline builder's topology derivation.
        st["station_index"] = st["station_id"].map(station_num) - 1

        self._stations = st.set_index("station_id", drop=False)
        self._station_count = len(st)
        self._history = {
            station_id: _StationHistory.empty()
            for station_id in self._stations.index
        }
        self._next_global_sequence = 0

    @classmethod
    def from_stations_csv(cls, path: str | Path) -> "LightZoneRuntimeFeatureBuilder":
        return cls(pd.read_csv(path))

    @property
    def feature_names(self) -> list[str]:
        return BOTTLENECK_FEATURES.copy()

    def reset(self) -> None:
        """Clear runtime history while keeping the same station configuration."""
        self._history = {
            station_id: _StationHistory.empty()
            for station_id in self._stations.index
        }
        self._next_global_sequence = 0

    def _resolve_sequence(self, event: Mapping[str, Any]) -> int:
        raw = event.get("event_sequence")
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            seq = self._next_global_sequence
        else:
            try:
                seq = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid event_sequence: {raw!r}") from exc

        self._next_global_sequence = max(self._next_global_sequence, seq + 1)
        return seq

    def _build(self, event: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        missing = REQUIRED_EVENT_FIELDS - set(event.keys())
        if missing:
            raise ValueError(
                "station event is missing required field(s): "
                + ", ".join(sorted(missing))
            )

        station_id = str(event["station_id"]).strip()
        if station_id not in self._stations.index:
            raise ValueError(f"Unknown station_id: {station_id}")

        try:
            t = int(pd.to_numeric(event["timestamp_ms"], errors="raise"))
        except Exception as exc:
            raise ValueError(f"Invalid timestamp_ms: {event['timestamp_ms']!r}") from exc

        seq = self._resolve_sequence(event)
        event_type = str(event.get("event_type", ""))
        queue_value = _number_or_nan(event.get("queue_length_after"))
        cycle_value = _number_or_nan(event.get("cycle_time_ms"))

        h = self._history[station_id]

        # Offline generation sorts by (timestamp_ms, event_sequence). At runtime,
        # allowing an older event after a newer one would silently introduce a
        # different causal history, so reject it instead.
        if h.times:
            previous_key = (h.times[-1], h.sequences[-1])
            current_key = (t, seq)
            if current_key < previous_key:
                raise ValueError(
                    f"Out-of-order event for {station_id}: {current_key} < {previous_key}. "
                    "Runtime Light-Zone events must be supplied in causal order."
                )

        h.times.append(t)
        h.sequences.append(seq)
        h.queues.append(queue_value)
        h.cycles.append(cycle_value)
        h.event_types.append(event_type)
        h.arrivals_prefix.append(
            h.arrivals_prefix[-1] + int(event_type == "UNIT_ARRIVED")
        )
        h.services_prefix.append(
            h.services_prefix[-1] + int(event_type == "PROCESSING_COMPLETED")
        )

        q_valid = int(np.isfinite(queue_value))
        q_safe = queue_value if q_valid else 0.0
        h.queue_count_prefix.append(h.queue_count_prefix[-1] + q_valid)
        h.queue_sum_prefix.append(h.queue_sum_prefix[-1] + q_safe)
        h.queue_sum2_prefix.append(h.queue_sum2_prefix[-1] + q_safe * q_safe)

        c_valid = int(np.isfinite(cycle_value))
        c_safe = cycle_value if c_valid else 0.0
        h.cycle_count_prefix.append(h.cycle_count_prefix[-1] + c_valid)
        h.cycle_sum_prefix.append(h.cycle_sum_prefix[-1] + c_safe)
        h.cycle_sum2_prefix.append(h.cycle_sum2_prefix[-1] + c_safe * c_safe)

        i = len(h.times) - 1
        hi = i + 1
        lo10 = bisect_left(h.times, t - RECENT_MS)
        lo20 = bisect_left(h.times, t - 2 * RECENT_MS)
        prev_hi = lo10

        q10 = _prefix_range_stats(
            h.queues, h.queue_count_prefix, h.queue_sum_prefix, h.queue_sum2_prefix, lo10, hi
        )
        qp = _prefix_range_stats(
            h.queues, h.queue_count_prefix, h.queue_sum_prefix, h.queue_sum2_prefix, lo20, prev_hi
        )
        c10 = _prefix_range_stats(
            h.cycles, h.cycle_count_prefix, h.cycle_sum_prefix, h.cycle_sum2_prefix, lo10, hi
        )

        # Exact replayed queue occupancy: current direct queue when present,
        # otherwise the last directly observed queue, otherwise 0.0.
        observed_now = np.isfinite(queue_value)
        if observed_now:
            h.last_direct_queue = float(queue_value)
            h.last_observed_index = i
        occ = float(h.last_direct_queue)

        arrivals10 = int(h.arrivals_prefix[hi] - h.arrivals_prefix[lo10])
        services10 = int(h.services_prefix[hi] - h.services_prefix[lo10])
        arrivals_prev = int(h.arrivals_prefix[prev_hi] - h.arrivals_prefix[lo20])
        services_prev = int(h.services_prefix[prev_hi] - h.services_prefix[lo20])

        # Exact queue slope calculation over direct finite queue observations in
        # the causal 10-minute window. Units remain queue-units per millisecond,
        # exactly as in the frozen offline builder.
        q_window = np.asarray(h.queues[lo10:hi], dtype=float)
        t_window = np.asarray(h.times[lo10:hi], dtype=np.int64)
        slope_mask = np.isfinite(q_window)
        slope_times = t_window[slope_mask]
        slope_values = q_window[slope_mask]

        slope = np.nan
        slope_std = np.nan
        distinct_slope_times = np.unique(slope_times).size
        if len(slope_times) > 1 and distinct_slope_times > 1:
            slope_x = slope_times.astype(float) - float(slope_times[0])
            fit = np.polyfit(slope_x, slope_values, 1)
            slope = float(fit[0])

            if distinct_slope_times >= 3:
                residual = slope_values - (fit[0] * slope_x + fit[1])
                dof = len(slope_x) - 2
                sxx = float(np.sum((slope_x - slope_x.mean()) ** 2))
                if dof > 0 and sxx > 0:
                    s_err = np.sqrt(np.sum(residual**2) / dof)
                    slope_std = float(s_err / np.sqrt(sxx))

        # Exact Light-Zone uncertainty behavior.
        if observed_now:
            state_confidence = 1.0
            progress_std = 0.0
        elif h.last_observed_index < 0:
            state_confidence = 0.0
            progress_std = np.nan
        else:
            oi = h.last_observed_index
            elapsed = float(t - h.times[oi])
            steps_missing = i - oi
            state_confidence = float(np.exp(-elapsed / RECENT_MS))
            volatility = q10[1]
            progress_std = (
                float(volatility * np.sqrt(steps_missing))
                if np.isfinite(volatility)
                else np.nan
            )

        station = self._stations.loc[station_id]
        capacity = float(station.buffer_capacity)
        idx = int(station.station_index)
        headroom = capacity - occ

        eta_std = np.nan
        if (
            np.isfinite(slope)
            and slope > 0
            and np.isfinite(headroom)
            and np.isfinite(slope_std)
            and np.isfinite(progress_std)
        ):
            slope_term = (headroom / slope**2) ** 2 * slope_std**2
            state_term = (1.0 / slope) ** 2 * progress_std**2
            eta_std = float(np.sqrt(slope_term + state_term))

        features: dict[str, Any] = {
            "capacity_headroom": headroom,
            "station_id": station_id,
            "base_cycle_time_ms": station.base_cycle_time_ms,
            "station_archetype": station.archetype,
            "configured_cycle_std_ms": station.cycle_time_std_ms,
            "station_index": idx,
            "buffer_capacity": capacity,
            "line_fraction": idx / max(1, self._station_count - 1),
            "queue_max_10m": q10[2],
            "queue_mean_10m": q10[0],
            "current_occupancy": occ,
            "queue_std_10m": q10[1],
            "capacity_utilization": occ / capacity if capacity else np.nan,
            "arrival_rate_per_min_prev10m": arrivals_prev / 10,
            "service_rate_per_min_prev10m": services_prev / 10,
            "service_rate_per_min_10m": services10 / 10,
            "arrival_rate_per_min_10m": arrivals10 / 10,
            "utilization_headroom": 1 - occ / capacity if capacity else np.nan,
            "cycle_max_10m": c10[2],
            "flow_pressure_10m": arrivals10 - services10,
            "queue_delta_10m": q10[0] - qp[0],
            "cycle_mean_10m": c10[0],
            "queue_slope_10m": slope,
            "net_flow_rate_10m": (arrivals10 - services10) / 10,
            "cycle_std_10m": c10[1],
            "state_confidence": state_confidence,
            "progress_std": progress_std,
            "eta_std": eta_std,
        }

        # Hard projection protects XGBoost feature order from accidental dict or
        # future code changes.
        features = {name: features[name] for name in BOTTLENECK_FEATURES}

        metadata = {
            "prediction_time": t,
            "prediction_event_sequence": seq,
            "station_id_buffer_id": station_id,
            "capacity": capacity,
            "currently_at_capacity": bool(occ >= capacity),
            "topology_configuration_version": SCHEMA_VERSION,
        }
        return features, metadata

    def process_event(self, event: Mapping[str, Any] | pd.Series) -> pd.DataFrame:
        """Consume one LIGHT station event and return XGBoost's exact 28-column row."""
        if isinstance(event, pd.Series):
            event = event.to_dict()
        features, _ = self._build(event)
        return pd.DataFrame([features], columns=BOTTLENECK_FEATURES)

    def process_event_with_metadata(
        self, event: Mapping[str, Any] | pd.Series
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Consume one event and return (28-feature DataFrame, causal metadata)."""
        if isinstance(event, pd.Series):
            event = event.to_dict()
        features, metadata = self._build(event)
        return pd.DataFrame([features], columns=BOTTLENECK_FEATURES), metadata

    def replay_events(self, events: pd.DataFrame) -> pd.DataFrame:
        """Replay a completed station_events table through the runtime path.

        This is for parity testing/debugging only. The runtime controller should
        normally call ``process_event`` as each new LIGHT event arrives.
        """
        required = REQUIRED_EVENT_FIELDS - set(events.columns)
        if required:
            raise ValueError(
                "station_events data is missing required column(s): "
                + ", ".join(sorted(required))
            )

        rows: list[dict[str, Any]] = []
        for arrival_sequence, (_, row) in enumerate(events.iterrows()):
            event = row.to_dict()
            if "event_sequence" not in events.columns:
                event["event_sequence"] = arrival_sequence
            features, metadata = self._build(event)
            rows.append({**metadata, **features})

        metadata_columns = [
            "station_id_buffer_id",
            "prediction_time",
            "prediction_event_sequence",
            "capacity",
            "topology_configuration_version",
            "currently_at_capacity",
        ]
        return pd.DataFrame(rows)[metadata_columns + BOTTLENECK_FEATURES]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay station_events.csv through the runtime Light-Zone 28-feature "
            "builder. This mode is intended for parity testing."
        )
    )
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    builder = LightZoneRuntimeFeatureBuilder.from_stations_csv(args.stations)
    events = pd.read_csv(args.events)
    result = builder.replay_events(events)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == ".parquet":
        result.to_parquet(args.output, index=False)
    else:
        result.to_csv(args.output, index=False)

    print(f"Wrote {len(result)} runtime Light-Zone feature rows to: {args.output}")
    print(f"Feature count: {len(BOTTLENECK_FEATURES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
