"""Build the Flow-v3 controlled corpus (Section 14-18): run the predeclared
manifest, project each run through the observability boundary, detect
congestion regimes from internal truth, and emit event/state-aligned
precursor observations with the future-service-capability regression
target.

Usage:
    python scripts/build_flow_v3_corpus.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow_v3.capacity_audit import DEFAULT_VARIANT_MIX, variant_service_time
from backend.flow_v3.congestion import detect_congestion_regimes
from backend.flow_v3.corpus_design import (
    RunSpec,
    SCENARIO_START_SECONDS,
    STD_INTERARRIVAL_SECONDS,
    build_run_manifest,
    build_unseen_degradation_manifest,
)
from backend.flow_v3.observations import RECENT_WINDOW_SECONDS, build_observation_features
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_capability_v2 import MIX_SHIFT_INTENSITY
from backend.flow_v3.scenario_physics import (
    PROVISIONAL_HEADWAY_SECONDS,
    build_arrival_burst,
    build_equipment_degradation,
    build_manual_variation,
    build_micro_stops,
)
from backend.observability.policy import build_public_event_stream, public_events_as_of
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = ROOT / "configs"
OUT_DIR = ROOT / "data" / "processed" / "flow_v3"
FUTURE_WINDOW_SECONDS = RECENT_WINDOW_SECONDS  # symmetric 5-minute look-back / look-forward
OBSERVATION_STATIONS = ("S11", "S20", "S21", "S22", "S24", "S26", "S33", "S34", "S38")
WARMUP_SECONDS = 1800.0  # skip line-fill transient before the first observation


def _heaviest_variant(config) -> str:
    totals = {variant_id: 0.0 for variant_id in config.vehicle_variants}
    for station_id in OBSERVATION_STATIONS:
        for variant_id in totals:
            service = variant_service_time(config, station_id, variant_id)
            if service is not None:
                totals[variant_id] += service
    return max(totals, key=totals.get)


def build_vehicle_mix_overload(scenario_id: str, severity: str, start_time: float, highest_variant: str) -> ScenarioDefinition:
    intensity = MIX_SHIFT_INTENSITY[severity]
    duration_minutes = {"MILD": 30.0, "MODERATE": 45.0, "SEVERE": 60.0}[severity]
    mix = {
        variant_id: (1 - intensity) * DEFAULT_VARIANT_MIX[variant_id] + intensity * (1.0 if variant_id == highest_variant else 0.0)
        for variant_id in DEFAULT_VARIANT_MIX
    }
    return ScenarioDefinition(
        scenario_id=scenario_id,
        family=ScenarioFamily.VEHICLE_MIX_OVERLOAD,
        start_time=start_time,
        duration=duration_minutes * 60.0,
        severity={"MILD": 0.25, "MODERATE": 0.55, "SEVERE": 0.90}[severity],
        temporal_profile="SUSTAINED_MIX",
        variant_mix_override=mix,
    )


def _build_scenarios(config, spec: RunSpec, highest_variant: str) -> list[ScenarioDefinition]:
    if spec.mechanism == "HEALTHY_CONTROL":
        return []
    if spec.mechanism == ScenarioFamily.MANUAL_VARIATION.value:
        return [build_manual_variation(
            config, scenario_id=spec.run_id, station_id=spec.station_id,
            severity=spec.severity, profile=spec.profile, start_time=spec.scenario_start_seconds,
        )]
    if spec.mechanism == ScenarioFamily.MICRO_STOPS.value:
        return [build_micro_stops(
            scenario_id=spec.run_id, station_id=spec.station_id,
            severity=spec.severity, profile=spec.profile, start_time=spec.scenario_start_seconds,
        )]
    if spec.mechanism == ScenarioFamily.ARRIVAL_BURST.value:
        return [build_arrival_burst(
            scenario_id=spec.run_id, severity=spec.severity, profile=spec.profile,
            start_time=spec.scenario_start_seconds,
        )]
    if spec.mechanism == ScenarioFamily.VEHICLE_MIX_OVERLOAD.value:
        return [build_vehicle_mix_overload(spec.run_id, spec.severity, spec.scenario_start_seconds, highest_variant)]
    if spec.mechanism == ScenarioFamily.EQUIPMENT_DEGRADATION.value:
        return [build_equipment_degradation(
            scenario_id=spec.run_id, station_id=spec.station_id,
            severity=spec.severity, profile=spec.profile, start_time=spec.scenario_start_seconds,
        )]
    raise ValueError(f"unhandled mechanism {spec.mechanism!r}")


def _internal_events_frame(events, run_id: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "shift_id": run_id,
        "event_type": e.event_type,
        "station_id": e.station_id,
        "buffer_id": e.buffer_id,
        "from_state": e.from_state,
        "to_state": e.to_state,
        "simulation_time": e.simulation_time,
    } for e in events])


def _sensor_baseline(sensor_models, station_id: str, config) -> float | None:
    station = config.stations[station_id]
    for sensor_name in station.available_sensors:
        model = sensor_models.get((station_id, sensor_name))
        if model is not None:
            return float(model.baseline)
    return None


def run_one(config, sensor_models, spec: RunSpec, highest_variant: str) -> dict:
    scenarios = _build_scenarios(config, spec, highest_variant)
    result = run_simulation(
        config, n_vehicles=spec.n_vehicles, seed=spec.seed,
        mean_interarrival_seconds=PROVISIONAL_HEADWAY_SECONDS,
        std_interarrival_seconds=STD_INTERARRIVAL_SECONDS,
        scenarios=scenarios, sensor_models=sensor_models,
    )
    run_end = result.summary["simulated_duration_seconds"]
    public_events = build_public_event_stream(result.events, config)
    internal_df = _internal_events_frame(result.events, spec.run_id)
    regimes, subepisodes = detect_congestion_regimes(internal_df, config)
    if len(regimes):
        regimes.insert(0, "run_id", spec.run_id)
        for column in ("mechanism", "severity", "profile", "partition"):
            regimes[column] = getattr(spec, column if column != "partition" else "partition")

    internal_completions_by_station: dict[str, list] = {}
    for e in result.events:
        if e.event_type == EventType.STATION_PROCESSING_COMPLETED.value and e.station_id in OBSERVATION_STATIONS:
            internal_completions_by_station.setdefault(e.station_id, []).append(e)

    rows = []
    for station_id in OBSERVATION_STATIONS:
        anchors = [
            e for e in public_events
            if e.station_id == station_id and e.event_type == "STATION_PROCESSING_COMPLETED"
            and WARMUP_SECONDS <= e.simulation_time <= run_end - FUTURE_WINDOW_SECONDS
        ]
        if not anchors:
            continue
        station_regimes = regimes[regimes.impact_station_id == station_id] if len(regimes) else regimes
        sensor_baseline = _sensor_baseline(sensor_models, station_id, config)
        future_completions = internal_completions_by_station.get(station_id, [])

        for anchor in anchors:
            t = anchor.simulation_time
            visible = public_events_as_of(public_events, t)
            features = build_observation_features(
                public_events_upto_t=visible, station_id=station_id, observation_time=t,
                config=config, sensor_baseline=sensor_baseline,
            )
            future_durations = [
                e.value for e in future_completions
                if t < e.simulation_time <= t + FUTURE_WINDOW_SECONDS and e.value is not None
            ]
            # Realized service TIME of vehicles actually processed, not a
            # throughput count: a station starved of arrivals is not the
            # same as a station whose service capability has degraded, and
            # a count-based rate would silently conflate the two -- exactly
            # the arrival/queue confound Section 2 keeps out of precursor ML.
            if not future_durations:
                continue  # no future evidence of realized service in window; excluded, not coded as 0
            future_mean_duration = sum(future_durations) / len(future_durations)
            future_rate_vph = 3600.0 / future_mean_duration
            baseline_rate_vph = 3600.0 / config.stations[station_id].baseline_cycle_time_seconds

            if len(station_regimes):
                active = station_regimes[(station_regimes.onset_time <= t) & (station_regimes.end_time >= t)]
                upcoming = station_regimes[station_regimes.onset_time >= t].sort_values("onset_time")
            else:
                active, upcoming = station_regimes, station_regimes
            regime_active = bool(len(active)) if len(regimes) else False
            next_onset = float(upcoming.onset_time.iloc[0]) if len(upcoming) else None

            rows.append({
                "run_id": spec.run_id, "partition": spec.partition, "mechanism": spec.mechanism,
                "severity": spec.severity, "profile": spec.profile,
                "target_station_id": spec.station_id or "LINE",
                **features,
                "future_service_rate_vph": future_rate_vph,
                "future_completions_count": len(future_durations),
                "baseline_service_rate_vph": baseline_rate_vph,
                "future_service_ratio_to_baseline": future_rate_vph / baseline_rate_vph,
                "congestion_regime_active_at_t": regime_active,
                "next_regime_onset_time": next_onset,
                "lead_seconds_to_next_regime": (next_onset - t) if next_onset is not None else None,
            })

    return {
        "rows": rows,
        "regimes": regimes if len(regimes) else None,
        "subepisodes": subepisodes if len(subepisodes) else None,
        "vehicles_completed": result.summary.get("vehicles_completed"),
        "simulated_duration_seconds": run_end,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(CONFIG_DIR / "flow_v3_rebalance.yaml"))
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")
    highest_variant = _heaviest_variant(config)
    print(f"heaviest-workload variant for VEHICLE_MIX_OVERLOAD targeting: {highest_variant}")

    manifest = build_run_manifest()
    degradation_manifest = build_unseen_degradation_manifest()
    manifest_df = pd.DataFrame([vars(s) for s in manifest])
    manifest_df.to_csv(OUT_DIR / "run_manifest.csv", index=False)
    pd.DataFrame([vars(s) for s in degradation_manifest]).to_csv(OUT_DIR / "unseen_degradation_manifest.csv", index=False)
    print(f"predeclared manifest: {len(manifest)} runs + {len(degradation_manifest)} unseen-degradation runs")

    all_rows, all_regimes, all_subepisodes = [], [], []
    t0 = time.time()
    for index, spec in enumerate(manifest + degradation_manifest):
        result = run_one(config, sensor_models, spec, highest_variant)
        all_rows.extend(result["rows"])
        if result["regimes"] is not None:
            all_regimes.append(result["regimes"])
        if result["subepisodes"] is not None:
            all_subepisodes.append(result["subepisodes"])
        if (index + 1) % 10 == 0 or index + 1 == len(manifest) + len(degradation_manifest):
            print(f"  [{index + 1}/{len(manifest) + len(degradation_manifest)}] {spec.run_id} "
                  f"rows_so_far={len(all_rows)} elapsed={time.time() - t0:.1f}s")

    full = pd.DataFrame(all_rows)
    regimes_df = pd.concat(all_regimes, ignore_index=True) if all_regimes else pd.DataFrame()
    subepisodes_df = pd.concat(all_subepisodes, ignore_index=True) if all_subepisodes else pd.DataFrame()

    for partition in ("train", "validation", "test", "unseen_equipment_degradation"):
        subset = full[full.partition == partition]
        subset.to_parquet(OUT_DIR / f"{partition}.parquet", index=False)
        print(f"{partition}: {len(subset)} rows, {subset.run_id.nunique()} runs")

    regimes_df.to_parquet(OUT_DIR / "congestion_regimes.parquet", index=False)
    subepisodes_df.to_parquet(OUT_DIR / "blocking_subepisodes.parquet", index=False)
    print(f"congestion regimes: {len(regimes_df)}; sub-episodes: {len(subepisodes_df)}")
    print(f"total observation rows: {len(full)}; total runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
