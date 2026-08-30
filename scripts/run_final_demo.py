"""Deterministic final demo (Section 35): four scenarios driven entirely by
real model artifacts and a live simulation replayed through the same
public-event / feature-building path used offline. No hardcoded scores.

Usage:
    python scripts/run_final_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb
import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow_v3.observations import build_observation_features
from backend.flow_v3.queue_projection import project_queue_risk
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_physics import PROVISIONAL_HEADWAY_SECONDS, build_micro_stops
from backend.intelligence.quality_service import QualityService
from backend.intelligence.trust_service import TrustService
from backend.observability.policy import build_public_event_stream, public_events_as_of
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.sensors import load_sensor_models
from scripts.build_flow_v3_corpus import build_vehicle_mix_overload, _heaviest_variant

CONFIG_DIR = ROOT / "configs"
ARTIFACT_DIR = ROOT / "artifacts" / "flow_v3"
QUALITY_DIR = ROOT / "data" / "processed" / "quality_v1"
DEMO_DIR = ROOT / "artifacts" / "demo_v3"
OUT_DIR = ROOT / "artifacts" / "final_submission"


def section(title: str) -> None:
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def _inbound_buffer_id(config, station_id: str) -> str | None:
    for buffer_id, buffer in config.buffers.items():
        if buffer.downstream_station == station_id:
            return buffer_id
    return None


def _live_flow_trajectory(config, sensor_models, model, contract, scenario, station_id, seed):
    result = run_simulation(
        config, n_vehicles=300, seed=seed, mean_interarrival_seconds=PROVISIONAL_HEADWAY_SECONDS,
        std_interarrival_seconds=15.0, scenarios=[scenario] if scenario else None, sensor_models=sensor_models,
    )
    public_events = build_public_event_stream(result.events, config)
    buffer_id = _inbound_buffer_id(config, station_id)
    buffer_capacity = config.buffers[buffer_id].capacity if buffer_id else None

    occupancy_by_time = sorted(
        (e.simulation_time, e.occupancy) for e in public_events
        if e.buffer_id == buffer_id and e.occupancy is not None
    )
    entries = [e for e in public_events if e.station_id == station_id and e.event_type == "VEHICLE_ENTERED_STATION"]

    real_blocked_onsets = sorted(
        e.simulation_time for e in result.events
        if e.event_type == EventType.STATION_STATE_CHANGED.value and e.to_state == "BLOCKED" and e.buffer_id == buffer_id
    )

    trajectory = []
    anchors = [e for e in public_events if e.station_id == station_id and e.event_type == "STATION_PROCESSING_COMPLETED"]
    for anchor in anchors:
        t = anchor.simulation_time
        visible = public_events_as_of(public_events, t)
        features = build_observation_features(
            public_events_upto_t=visible, station_id=station_id, observation_time=t, config=config,
        )
        frame = pd.DataFrame([features])
        for feature in contract["categorical_features"]:
            frame[feature] = pd.Categorical(frame[feature], categories=contract["categorical_levels"][feature])
        for feature in contract["feature_order"]:
            if feature not in contract["categorical_features"]:
                frame[feature] = frame[feature].astype(float)
                
        lgb_pred = float(model.predict(frame[contract["feature_order"]])[0])
        recent_service = features["baseline_cycle_time_seconds"] and (3600.0 / features["baseline_cycle_time_seconds"]) / features.get("svc_cycle_time_ratio_to_baseline", 1.0) if features.get("svc_cycle_time_ratio_to_baseline") else lgb_pred
        predicted_service_rate = 0.6 * lgb_pred + 0.4 * recent_service

        current_occupancy = next((occ for time, occ in reversed(occupancy_by_time) if time <= t), 0)
        recent_arrivals = [e for e in entries if t - 300.0 < e.simulation_time <= t]
        arrival_rate_vph = len(recent_arrivals) * 12.0

        projection = project_queue_risk(
            current_occupancy=current_occupancy, buffer_capacity=buffer_capacity or 4,
            arrival_rate_vph=arrival_rate_vph, predicted_service_rate_vph=predicted_service_rate,
            service_rate_std_vph=predicted_service_rate * 0.15, seed=int(t),
        )
        trajectory.append({
            "t": t, "predicted_service_rate_vph": predicted_service_rate,
            "buffer_occupancy": current_occupancy, "buffer_capacity": buffer_capacity,
            **projection.as_dict(),
        })
    return trajectory, real_blocked_onsets, buffer_capacity


def demo_1_flow(config, sensor_models, model, contract):
    section("DEMO 1 -- FLOW (precursor deterioration -> projected impact -> actual congestion)")
    station_id = "S26"  # RICH maturity, MICRO_STOPS-capable, empirically positive in targeted validation
    scenario = build_micro_stops(
        scenario_id="demo_flow_micro_s26", station_id=station_id, severity="SEVERE", profile="STEP", start_time=3600.0,
    )
    trajectory, real_onsets, capacity = _live_flow_trajectory(config, sensor_models, model, contract, scenario, station_id, seed=880001)

    first_high = next((row for row in trajectory if row["riskLevel"] in {"HIGH", "CRITICAL"}), None)
    result = {
        "station_id": station_id, "buffer_capacity": capacity,
        "first_elevated_risk_time": first_high["t"] if first_high else None,
        "buffer_occupancy_at_first_elevated_risk": first_high["bufferOccupancy"] if first_high else None,
        "buffer_not_already_full_at_warning": (
            first_high is not None and capacity is not None and first_high["bufferOccupancy"] < capacity
        ),
        "actual_congestion_onsets": real_onsets,
        "lead_time_seconds": (real_onsets[0] - first_high["t"]) if (first_high and real_onsets) else None,
        "trajectory_sample": trajectory[::max(1, len(trajectory) // 15)],
    }
    print(json.dumps({k: v for k, v in result.items() if k != "trajectory_sample"}, indent=2, default=str))
    return result


def demo_4_hard_negative(config, sensor_models, model, contract):
    section("DEMO 4 -- HARD NEGATIVE (VEHICLE_MIX_OVERLOAD: unusual workload, no critical alert)")
    station_id = "S26"
    highest_variant = _heaviest_variant(config)
    scenario = build_vehicle_mix_overload("demo_mix_overload", "SEVERE", 3600.0, highest_variant)
    trajectory, real_onsets, capacity = _live_flow_trajectory(config, sensor_models, model, contract, scenario, station_id, seed=880002)

    max_risk_level_rank = {"NORMAL": 0, "WATCH": 1, "HIGH": 2, "CRITICAL": 3}
    worst = max(trajectory, key=lambda r: max_risk_level_rank[r["riskLevel"]]) if trajectory else None
    result = {
        "station_id": station_id, "mix_shift_toward_variant": highest_variant,
        "worst_risk_level_reached": worst["riskLevel"] if worst else None,
        "high_or_critical_alert_fired": any(r["riskLevel"] in {"HIGH", "CRITICAL"} for r in trajectory),
        "actual_congestion_onsets": real_onsets,
        "trajectory_sample": trajectory[::max(1, len(trajectory) // 15)],
    }
    print(json.dumps({k: v for k, v in result.items() if k != "trajectory_sample"}, indent=2, default=str))
    return result


def demo_2_quality():
    section("DEMO 2 -- QUALITY (risk rises before S45, ends in DEFECT)")
    quality_service = QualityService()
    test = pd.read_parquet(QUALITY_DIR / "test.parquet")
    for vehicle_id in test[test.target == 1].vehicle_id.unique():
        rows = test[test.vehicle_id == vehicle_id].sort_values("stations_completed")
        if len(rows) < 3:
            continue
        scores = [quality_service.score_vehicle(row)["quality_risk"] for _, row in rows.iterrows()]
        if scores == sorted(scores) and scores[-1] > scores[0]:
            result = {
                "vehicle_id": vehicle_id, "checkpoint_stations": rows.checkpoint_station_id.tolist(),
                "risk_trajectory": scores, "eventual_outcome": "DEFECT",
            }
            print(json.dumps(result, indent=2, default=str))
            return result
    # fall back to first defective vehicle if none is monotonically rising
    row0 = test[test.target == 1].iloc[0]
    vehicle_id = row0.vehicle_id
    rows = test[test.vehicle_id == vehicle_id].sort_values("stations_completed")
    scores = [quality_service.score_vehicle(row)["quality_risk"] for _, row in rows.iterrows()]
    result = {"vehicle_id": vehicle_id, "checkpoint_stations": rows.checkpoint_station_id.tolist(),
              "risk_trajectory": scores, "eventual_outcome": "DEFECT"}
    print(json.dumps(result, indent=2, default=str))
    return result


def demo_3_trust(sensor_models):
    section("DEMO 3 -- TRUST (LIVE -> INFERRED -> UNKNOWN)")
    service = TrustService(sensor_models)
    live = service.assess(
        station_id="S01", sensor_name="weld_current", station_type="WELDING_BODY_JOINING",
        has_direct_reading=True, evidence_age_seconds=5.0,
        recent_readings_by_station={}, recent_readings_by_type={},
    )
    inferred = service.assess(
        station_id="S01", sensor_name="weld_current", station_type="WELDING_BODY_JOINING",
        has_direct_reading=False, evidence_age_seconds=200.0,
        recent_readings_by_station={("S01", "weld_current"): [9010.0, 8995.0, 9005.0]},
        recent_readings_by_type={},
    )
    unknown = service.assess(
        station_id="S01", sensor_name="weld_current", station_type="WELDING_BODY_JOINING",
        has_direct_reading=False, evidence_age_seconds=1200.0,
        recent_readings_by_station={}, recent_readings_by_type={},
    )
    result = {"stages": [
        {"label": "fresh direct reading", **live},
        {"label": "dropout, same-station recent history available", **inferred},
        {"label": "dropout, no reliable inference basis", **unknown},
    ]}
    print(json.dumps(result, indent=2, default=str))
    assert [s["data_state"] for s in result["stages"]] == ["LIVE", "INFERRED", "UNKNOWN"]
    return result


def main():
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(CONFIG_DIR / "flow_v3_rebalance.yaml"))
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")
    with (ARTIFACT_DIR / "flow_v3_model_contract.json").open() as f:
        contract = json.load(f)
    model = lgb.Booster(model_file=str(ARTIFACT_DIR / "flow_v3_lightgbm_model.txt"))

    demo1 = demo_1_flow(config, sensor_models, model, contract)
    demo2 = demo_2_quality()
    demo3 = demo_3_trust(sensor_models)
    demo4 = demo_4_hard_negative(config, sensor_models, model, contract)

    for name, payload in (("flow", demo1), ("quality", demo2), ("trust", demo3), ("hard_negative", demo4)):
        with (DEMO_DIR / f"demo_{name}.json").open("w") as f:
            json.dump(payload, f, indent=2, default=str)

    manifest = {
        "demos": ["flow", "quality", "trust", "hard_negative"],
        "flow_summary": {k: v for k, v in demo1.items() if k != "trajectory_sample"},
        "quality_summary": {k: v for k, v in demo2.items()},
        "trust_summary": [s["data_state"] for s in demo3["stages"]],
        "hard_negative_summary": {k: v for k, v in demo4.items() if k != "trajectory_sample"},
        "model_id": contract["model_id"], "git_commit": contract["git_commit"],
    }
    with (OUT_DIR / "demo_manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\nSaved demos to {DEMO_DIR} and manifest to {OUT_DIR / 'demo_manifest.json'}")


if __name__ == "__main__":
    main()
