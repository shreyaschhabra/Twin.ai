"""Event/state-aligned Flow-v3 precursor observations (Sections 15, 18, 31).

One row per meaningful public event per station -- NOT a station-minute
grid. The anchor event is `STATION_PROCESSING_COMPLETED`: each completed
cycle is a genuine service update, so rows exist only while a station is
actually active and stop the instant its last vehicle finishes, with no
pre-activity or post-activity padding rows.

`build_observation_features` is the SINGLE feature-computation function
used by both the offline dataset builder and the runtime replay path
(Section 31 train/runtime parity) -- it only ever looks at a list of
`PublicEvent`s already cut off at the observation time, so offline batch
slicing and incremental runtime accumulation are structurally forced to
agree as long as they hand it the same cutoff list.

Feature groups follow Section 18 exactly. Current queue/occupancy/capacity/
BLOCKED state and anything "future" are never read here -- those live only
in `backend.flow_v3.queue_projection`.
"""

from __future__ import annotations

import statistics
from typing import Optional

from backend.config.schemas import FactoryConfig
from backend.flow_v3.capacity_audit import DEFAULT_VARIANT_MIX, variant_service_time
from backend.observability.policy import ObservabilityClass, PublicEvent

RECENT_WINDOW_SECONDS = 300.0
PRIOR_WINDOW_SECONDS = 300.0

_COARSE_STATES = ("IDLE", "WAITING", "RUNNING", "FLOW_STOP", "EQUIPMENT_STOP")

BANNED_QUEUE_TERMS = (
    "occupancy", "queue", "capacity_headroom", "distance_to_full", "blocked_state", "future_",
)


def _zone(station_id: str) -> str:
    number = int(station_id[1:])
    if number <= 12:
        return "body_joining"
    if number <= 20:
        return "paint_surface"
    if number <= 38:
        return "final_assembly"
    return "inspection_eol"


def _durations_in_window(completions: list[PublicEvent], start: float, end: float) -> list[float]:
    return [e.value for e in completions if start < e.simulation_time <= end and e.value is not None]


def _timestamps_in_window(events: list[PublicEvent], start: float, end: float) -> list[float]:
    return [e.simulation_time for e in events if start < e.simulation_time <= end]


def _service_feature_block(
    completions: list[PublicEvent], entries: list[PublicEvent], t: float, baseline_cycle_time: float,
) -> dict:
    recent = [e for e in completions if t - RECENT_WINDOW_SECONDS < e.simulation_time <= t]
    prior = [e for e in completions if t - RECENT_WINDOW_SECONDS - PRIOR_WINDOW_SECONDS < e.simulation_time <= t - RECENT_WINDOW_SECONDS]
    entry_time_by_vehicle = {e.vehicle_id: e.simulation_time for e in entries if e.vehicle_id is not None}

    def _effective_cycle_time(window: list[PublicEvent]) -> tuple[Optional[float], bool, list[float]]:
        durations = [e.value for e in window if e.value is not None]
        if durations:
            return statistics.fmean(durations), True, durations
        # Duration hidden at this maturity (PARTIAL/POOR): cross-vehicle
        # inter-completion cadence is NOT used here -- it is confounded by
        # upstream arrival rate (a station starved of arrivals looks
        # "slow" even when perfectly healthy), which would silently
        # reintroduce the arrival/queue confound this feature layer is
        # meant to exclude. Instead use per-vehicle entry-to-completion
        # span, matched by vehicle_id (present at every maturity) -- a
        # station-local occupancy-per-visit proxy, not a cross-station
        # arrival-rate artifact.
        spans = [
            e.simulation_time - entry_time_by_vehicle[e.vehicle_id]
            for e in window
            if e.vehicle_id in entry_time_by_vehicle
        ]
        spans = [s for s in spans if s > 0]
        if spans:
            return statistics.fmean(spans), False, spans
        return None, False, []

    recent_cycle, recent_is_direct, recent_samples = _effective_cycle_time(recent)
    prior_cycle, _, _ = _effective_cycle_time(prior)
    # Variability must come from whichever sample source actually produced
    # the mean above -- computing it only from the (often entirely absent,
    # at PARTIAL/POOR maturity) direct-duration list would silently force
    # this feature to a constant 0 for exactly the stations that rely on
    # the span-based fallback, which is most of the positive-capable set.
    durations = recent_samples

    return {
        "svc_recent_cycle_time_seconds": recent_cycle,
        "svc_cycle_time_is_measured_duration": recent_is_direct,
        "svc_cycle_time_ratio_to_baseline": (recent_cycle / baseline_cycle_time) if recent_cycle else None,
        "svc_cycle_time_trend_seconds": (recent_cycle - prior_cycle) if (recent_cycle and prior_cycle) else None,
        "svc_cycle_time_std_seconds": statistics.pstdev(durations) if len(durations) >= 2 else 0.0,
        "svc_completion_count_recent": len(recent),
        "svc_rate_recent_per_hour": len(recent) * (3600.0 / RECENT_WINDOW_SECONDS),
        "svc_rate_prior_per_hour": len(prior) * (3600.0 / PRIOR_WINDOW_SECONDS),
        "svc_departure_rate_trend": len(recent) * (3600.0 / RECENT_WINDOW_SECONDS) - len(prior) * (3600.0 / PRIOR_WINDOW_SECONDS),
    }


def _micro_stop_feature_block(micro_stops: list[PublicEvent], t: float) -> dict:
    recent = [e for e in micro_stops if t - RECENT_WINDOW_SECONDS < e.simulation_time <= t]
    prior = [e for e in micro_stops if t - RECENT_WINDOW_SECONDS - PRIOR_WINDOW_SECONDS < e.simulation_time <= t - RECENT_WINDOW_SECONDS]
    recent_minutes = RECENT_WINDOW_SECONDS / 60.0
    prior_minutes = PRIOR_WINDOW_SECONDS / 60.0
    seconds = sum(e.value for e in recent if e.value is not None)
    durations = [e.value for e in recent if e.value is not None]
    recent_rate = len(recent) / recent_minutes
    prior_rate = len(prior) / prior_minutes
    return {
        "ms_count_recent": len(recent),
        "ms_seconds_recent": seconds,
        "ms_mean_duration_seconds": statistics.fmean(durations) if durations else 0.0,
        "ms_rate_per_minute": recent_rate,
        "ms_rate_trend": recent_rate - prior_rate,
    }


def _sensor_feature_block(readings: list[PublicEvent], t: float, sensor_baseline: Optional[float]) -> dict:
    recent = [e for e in readings if t - RECENT_WINDOW_SECONDS < e.simulation_time <= t and e.value is not None]
    prior = [e for e in readings if t - RECENT_WINDOW_SECONDS - PRIOR_WINDOW_SECONDS < e.simulation_time <= t - RECENT_WINDOW_SECONDS and e.value is not None]
    last_time = max((e.simulation_time for e in readings if e.simulation_time <= t), default=None)
    recent_mean = statistics.fmean(e.value for e in recent) if recent else None
    prior_mean = statistics.fmean(e.value for e in prior) if prior else None
    return {
        "sensor_recent_mean": recent_mean,
        "sensor_trend": (recent_mean - prior_mean) if (recent_mean is not None and prior_mean is not None) else None,
        "sensor_drift_from_baseline": (
            abs(recent_mean - sensor_baseline) if (recent_mean is not None and sensor_baseline is not None) else None
        ),
        "sensor_missing_recent": recent_mean is None,
        "sensor_freshness_seconds": (t - last_time) if last_time is not None else None,
    }


def _vehicle_mix_feature_block(config: FactoryConfig, station_id: str, entries: list[PublicEvent], t: float) -> dict:
    recent = [e for e in entries if t - RECENT_WINDOW_SECONDS < e.simulation_time <= t and e.vehicle_variant]
    counts = {variant_id: 0 for variant_id in config.vehicle_variants}
    for event in recent:
        if event.vehicle_variant in counts:
            counts[event.vehicle_variant] += 1
    total = sum(counts.values())
    proportions = {
        variant_id: (counts[variant_id] / total if total else DEFAULT_VARIANT_MIX.get(variant_id, 0.0))
        for variant_id in counts
    }
    services = {
        variant_id: variant_service_time(config, station_id, variant_id)
        for variant_id in config.vehicle_variants
    }
    demand = sum(
        proportions[v] * services[v] for v in proportions if services.get(v) is not None
    )
    out = {f"mix_prop_{variant_id.lower()}": proportions[variant_id] for variant_id in proportions}
    out["mix_workload_weighted_expected_service_seconds"] = demand
    out["mix_entries_recent"] = total
    return out


def _operational_feature_block(state_changes: list[PublicEvent], t: float) -> dict:
    """Fraction of the recent window spent in each coarse state, derived
    only from public STATION_STATE_CHANGED evidence (absent entirely at
    POOR maturity, coarsened at PARTIAL -- both handled identically here
    since the observability policy already normalizes vocabulary)."""
    window_start = t - RECENT_WINDOW_SECONDS
    prior_changes = [e for e in state_changes if e.simulation_time <= window_start]
    in_window = sorted(
        (e for e in state_changes if window_start < e.simulation_time <= t),
        key=lambda e: e.simulation_time,
    )
    if not prior_changes and not in_window:
        return {f"op_frac_{state.lower()}": None for state in _COARSE_STATES} | {"op_state_observed": False}

    current_state = prior_changes[-1].to_state if prior_changes else (in_window[0].from_state if in_window else None)
    cursor = window_start
    durations = {state: 0.0 for state in _COARSE_STATES}
    for event in in_window:
        if current_state in durations:
            durations[current_state] += event.simulation_time - cursor
        cursor = event.simulation_time
        current_state = event.to_state
    if current_state in durations:
        durations[current_state] += t - cursor
    total = sum(durations.values()) or 1.0
    out = {f"op_frac_{state.lower()}": durations[state] / total for state in _COARSE_STATES}
    out["op_state_observed"] = True
    return out


def build_observation_features(
    *,
    public_events_upto_t: list[PublicEvent],
    station_id: str,
    observation_time: float,
    config: FactoryConfig,
    sensor_baseline: Optional[float] = None,
) -> dict:
    """Point-in-time-safe precursor feature row for one station at one
    observation time. `public_events_upto_t` MUST already be filtered to
    `simulation_time <= observation_time` (offline: `public_events_as_of`;
    runtime: whatever has been replayed so far) -- this function performs
    no further cutoff filtering itself, by design, so both call sites are
    forced through the exact same downstream logic."""
    t = observation_time
    station = config.stations[station_id]
    station_events = [e for e in public_events_upto_t if e.station_id == station_id]

    completions = [e for e in station_events if e.event_type == "STATION_PROCESSING_COMPLETED"]
    micro_stops = [e for e in station_events if e.event_type == "MICRO_STOP_OCCURRED"]
    readings = [e for e in station_events if e.event_type == "SENSOR_READING"]
    entries = [e for e in station_events if e.event_type == "VEHICLE_ENTERED_STATION"]
    state_changes = [e for e in station_events if e.event_type == "STATION_STATE_CHANGED"]

    features: dict = {
        "station_id": station_id,
        "observation_time": t,
        "station_type": station.station_type,
        "zone": _zone(station_id),
        "sensor_maturity": station.sensor_maturity.value,
        "baseline_cycle_time_seconds": station.baseline_cycle_time_seconds,
    }
    features.update(_service_feature_block(completions, entries, t, station.baseline_cycle_time_seconds))
    features.update(_micro_stop_feature_block(micro_stops, t))
    features.update(_sensor_feature_block(readings, t, sensor_baseline))
    features.update(_vehicle_mix_feature_block(config, station_id, entries, t))
    features.update(_operational_feature_block(state_changes, t))

    for key in features:
        assert not any(term in key.lower() for term in BANNED_QUEUE_TERMS), (
            f"feature {key!r} looks like banned queue/occupancy state -- physics-only"
        )
    return features


STATIC_FEATURES = ["station_type", "zone", "sensor_maturity", "baseline_cycle_time_seconds"]
CATEGORICAL_FEATURES = ["station_type", "zone", "sensor_maturity"]
