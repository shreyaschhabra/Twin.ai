"""Trust-layer validation (Section 30): compact tests for isolated missing
points, contiguous outages, and (cheaply) an outage during a degradation
scenario. Uses a small live simulation run rather than a stored dataset so
the readings_df schema (station_id, sensor_name, station_type, value,
simulation_time, measurement_status, sensor_maturity) is built directly
and correctly, with no guessing about column availability.

Usage:
    python scripts/validate_trust_v3.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_physics import PROVISIONAL_HEADWAY_SECONDS, build_equipment_degradation
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.sensors import load_sensor_models
from backend.trust.virtual_sensor import estimate_virtual_sensor_value, evaluate_virtual_sensor

CONFIG_DIR = ROOT / "configs"
ARTIFACT_DIR = ROOT / "artifacts" / "final_submission"


def section(title: str) -> None:
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def _readings_frame(events, config) -> pd.DataFrame:
    rows = [
        {
            "station_id": e.station_id, "sensor_name": e.sensor_name, "value": e.value,
            "simulation_time": e.simulation_time, "measurement_status": e.measurement_status,
            "station_type": config.stations[e.station_id].station_type,
            "sensor_maturity": config.stations[e.station_id].sensor_maturity.value,
        }
        for e in events if e.event_type == EventType.SENSOR_READING.value
    ]
    return pd.DataFrame(rows)


def _contiguous_outage_eval(readings: pd.DataFrame, sensor_models, outage_readings: int = 8) -> dict:
    """For each (station, sensor) with enough history, blank out a
    contiguous stretch of `outage_readings` consecutive readings and score
    the virtual-sensor estimate against the true values, tracking how the
    estimate/data-state degrades as the outage lengthens."""
    available = readings[readings.measurement_status == "available"].sort_values("simulation_time")
    results = []
    for (station_id, sensor_name), group in available.groupby(["station_id", "sensor_name"]):
        group = group.reset_index(drop=True)
        if len(group) < outage_readings + 5:
            continue
        start = len(group) // 3
        outage = group.iloc[start:start + outage_readings]
        station_type = group.station_type.iloc[0]
        history_before = group.iloc[:start].value.tolist()
        type_history = available[
            (available.station_type == station_type) & (available.sensor_name == sensor_name)
            & (available.simulation_time < outage.simulation_time.iloc[0])
        ].value.tolist()

        for position, row in enumerate(outage.itertuples()):
            est, method, reliable = estimate_virtual_sensor_value(
                station_id, sensor_name, station_type,
                {(station_id, sensor_name): history_before[-10:]},
                {(station_type, sensor_name): type_history[-50:]},
                sensor_models,
            )
            data_state = "INFERRED" if (est is not None and reliable) else "UNKNOWN"
            results.append({
                "station_id": station_id, "sensor_name": sensor_name,
                "position_in_outage": position, "data_state": data_state,
                "error": abs(est - row.value) if (est is not None and reliable) else None,
            })
            # Same-station history does NOT grow during the outage (that's
            # the point of an outage) -- only type history keeps accruing
            # from other stations.

    df = pd.DataFrame(results)
    if df.empty:
        return {"n_scored": 0}
    by_position = df.groupby("position_in_outage").agg(
        unknown_rate=("data_state", lambda s: float((s == "UNKNOWN").mean())),
        inferred_rate=("data_state", lambda s: float((s == "INFERRED").mean())),
        mean_error=("error", "mean"),
    )
    return {
        "n_scored": int(len(df)),
        "overall_unknown_rate": float((df.data_state == "UNKNOWN").mean()),
        "overall_inferred_rate": float((df.data_state == "INFERRED").mean()),
        "overall_inferred_mae": float(df.error.dropna().mean()) if df.error.notna().any() else None,
        "by_position_in_outage": by_position.reset_index().to_dict(orient="records"),
    }


def main():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(CONFIG_DIR / "flow_v3_rebalance.yaml"))
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")

    section("1. ISOLATED MISSING POINT (random masking, healthy run)")
    healthy = run_simulation(
        config, n_vehicles=150, seed=990001, mean_interarrival_seconds=PROVISIONAL_HEADWAY_SECONDS,
        std_interarrival_seconds=15.0, sensor_models=sensor_models,
    )
    readings = _readings_frame(healthy.events, config)
    print(f"total SENSOR_READING rows: {len(readings)}, available: {(readings.measurement_status == 'available').sum()}")
    isolated = evaluate_virtual_sensor(readings, sensor_models, mask_fraction=0.2, seed=20260830)
    print(json.dumps(isolated, indent=2))

    section("2. CONTIGUOUS OUTAGE (with same-type fallback available)")
    contiguous = _contiguous_outage_eval(readings, sensor_models, outage_readings=8)
    print(json.dumps({k: v for k, v in contiguous.items() if k != "by_position_in_outage"}, indent=2))
    for row in contiguous.get("by_position_in_outage", []):
        print(f"  position {row['position_in_outage']}: UNKNOWN rate={row['unknown_rate']:.3f}, "
              f"INFERRED rate={row['inferred_rate']:.3f}, mean error={row['mean_error']}")

    section("2b. PROLONGED OUTAGE (zone down: same-type fallback unavailable)")
    # Simulate a condition where the entire zone/type is down, so `type_history` is empty
    def _zone_down_outage_eval(readings: pd.DataFrame, sensor_models, outage_readings: int = 8) -> dict:
        available = readings[readings.measurement_status == "available"].sort_values("simulation_time")
        results = []
        for (station_id, sensor_name), group in available.groupby(["station_id", "sensor_name"]):
            group = group.reset_index(drop=True)
            if len(group) < outage_readings + 5:
                continue
            start = len(group) // 3
            outage = group.iloc[start:start + outage_readings]
            history_before = group.iloc[:start].value.tolist()
            
            for position, row in enumerate(outage.itertuples()):
                # Simulate aging out: same-station history drops as the outage prolongs
                aged_history = history_before[-(10 - position):] if (10 - position) > 0 else []
                # Pass empty type_history to simulate the entire station type being unavailable
                est, method, reliable = estimate_virtual_sensor_value(
                    station_id, sensor_name, group.station_type.iloc[0],
                    {(station_id, sensor_name): aged_history},
                    {},  # NO same-type fallback available
                    sensor_models,
                )
                data_state = "INFERRED" if (est is not None and reliable) else "UNKNOWN"
                results.append({"position_in_outage": position, "data_state": data_state})
                
        df = pd.DataFrame(results)
        if df.empty:
            return {"n_scored": 0}
        by_position = df.groupby("position_in_outage").agg(
            unknown_rate=("data_state", lambda s: float((s == "UNKNOWN").mean())),
            inferred_rate=("data_state", lambda s: float((s == "INFERRED").mean()))
        )
        return {
            "n_scored": int(len(df)),
            "overall_unknown_rate": float((df.data_state == "UNKNOWN").mean()),
            "overall_inferred_rate": float((df.data_state == "INFERRED").mean()),
            "by_position_in_outage": by_position.reset_index().to_dict(orient="records"),
        }
        
    prolonged = _zone_down_outage_eval(readings, sensor_models, outage_readings=12)
    print(json.dumps({k: v for k, v in prolonged.items() if k != "by_position_in_outage"}, indent=2))
    for row in prolonged.get("by_position_in_outage", []):
        print(f"  position {row['position_in_outage']}: UNKNOWN rate={row['unknown_rate']:.3f}, "
              f"INFERRED rate={row['inferred_rate']:.3f}")

    section("3. OUTAGE DURING EQUIPMENT_DEGRADATION (unseen family; evaluation only)")
    degraded_station = "S27"
    scenario = build_equipment_degradation(
        scenario_id="trust_validate_degradation", station_id=degraded_station,
        severity="SEVERE", profile="GRADUAL", start_time=3600.0,
    )
    degraded = run_simulation(
        config, n_vehicles=150, seed=990002, mean_interarrival_seconds=PROVISIONAL_HEADWAY_SECONDS,
        std_interarrival_seconds=15.0, scenarios=[scenario], sensor_models=sensor_models,
    )
    degraded_readings = _readings_frame(degraded.events, config)
    degraded_contiguous = _contiguous_outage_eval(
        degraded_readings[degraded_readings.station_id == degraded_station], sensor_models, outage_readings=6,
    )
    print(json.dumps({k: v for k, v in degraded_contiguous.items() if k != "by_position_in_outage"}, indent=2))

    section("4. SAVE")
    out = {
        "isolated_missing_point": isolated,
        "contiguous_outage": {k: v for k, v in contiguous.items()},
        "prolonged_zone_outage": {k: v for k, v in prolonged.items()},
        "contiguous_outage_during_degradation": {k: v for k, v in degraded_contiguous.items()},
        "note": (
            "error_by_maturity/mean_error are raw absolute units, not normalized across sensors of "
            "different physical scale (e.g. weld_current ~9000A vs a 0-1 checklist fraction) -- a "
            "low absolute error for 'poor' maturity reflects small-scale signals, not a stronger "
            "estimator, and should not be read as poor-maturity sensors being more predictable. "
            "This run's factory topology has well-populated same-station-type pools for every "
            "sensor tested, so the outage never actually falls through to UNKNOWN here -- that is "
            "a genuine property of this instrumentation layout (shared sensor families across "
            "multiple same-type stations), not evidence the UNKNOWN path is unreachable; "
            "backend/trust tests already cover the case where no reliable fallback exists."
        ),
    }
    with (ARTIFACT_DIR / "trust_metrics.json").open("w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Saved {ARTIFACT_DIR / 'trust_metrics.json'}")


if __name__ == "__main__":
    main()
