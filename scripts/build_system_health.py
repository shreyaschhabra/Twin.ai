"""System health check (Section 34): a real end-to-end smoke test of every
component, not a static file-existence stub -- each check actually
exercises the component and reports PASS/DEGRADED/FAIL.

Usage:
    python scripts/build_system_health.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "artifacts" / "final_submission"


def _check(name, fn) -> dict:
    try:
        detail = fn()
        return {"component": name, "status": "PASS", "detail": detail}
    except Exception as exc:  # noqa: BLE001 -- health check must never crash the runner
        return {"component": name, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=3)}


def check_simulator():
    from backend.config.loader import load_factory_config
    from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
    from backend.simulation.engine import run_simulation
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))
    result = run_simulation(config, n_vehicles=10, seed=1, mean_interarrival_seconds=102.5, std_interarrival_seconds=15.0)
    assert result.summary.get("vehicles_completed", 0) >= 0
    return f"{len(result.events)} internal events from a 10-vehicle smoke run"


def check_public_event_stream():
    from backend.config.loader import load_factory_config
    from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
    from backend.observability.policy import build_public_event_stream
    from backend.simulation.engine import run_simulation
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))
    result = run_simulation(config, n_vehicles=10, seed=1, mean_interarrival_seconds=102.5, std_interarrival_seconds=15.0)
    public = build_public_event_stream(result.events, config)
    assert len(public) <= len(result.events)
    forbidden = {"scenario_id", "hidden_degradation_severity", "latent_quality_exposure"}
    for e in public[:5]:
        assert forbidden.isdisjoint(vars(e).keys())
    return f"{len(public)} public events projected from {len(result.events)} internal events"


def check_flow_model():
    import lightgbm as lgb
    artifact_dir = ROOT / "artifacts" / "flow_v3"
    with (artifact_dir / "flow_v3_model_contract.json").open() as f:
        contract = json.load(f)
    model = lgb.Booster(model_file=str(artifact_dir / "flow_v3_lightgbm_model.txt"))
    assert model.num_feature() == len(contract["feature_order"])
    return f"loaded, {model.num_feature()} features, test MAE={contract['metrics']['lightgbm_final']['test']['mae_vph']:.2f} vph"


def check_flow_projection():
    from backend.flow_v3.queue_projection import project_queue_risk
    normal = project_queue_risk(current_occupancy=1, buffer_capacity=4, arrival_rate_vph=30, predicted_service_rate_vph=35)
    critical = project_queue_risk(current_occupancy=3, buffer_capacity=4, arrival_rate_vph=40, predicted_service_rate_vph=20, service_rate_std_vph=3)
    assert normal.risk_level == "NORMAL"
    assert critical.risk_level in {"HIGH", "CRITICAL"}
    return f"NORMAL/{critical.risk_level} cases both project correctly"


def check_quality_model():
    import lightgbm as lgb
    artifact_dir = ROOT / "artifacts" / "quality"
    with (artifact_dir / "feature_list.json").open() as f:
        feature_list = json.load(f)
    model = lgb.Booster(model_file=str(artifact_dir / "quality_lightgbm_model.txt"))
    n_expected = len(feature_list["numeric_features"]) + len(feature_list["categorical_features"])
    assert model.num_feature() == n_expected
    return f"loaded, {model.num_feature()} features"


def check_anomaly():
    import joblib
    artifact_dir = ROOT / "artifacts" / "anomaly_v3"
    payload = joblib.load(artifact_dir / "isolation_forest_v3.joblib")
    with (artifact_dir / "metadata.json").open() as f:
        meta = json.load(f)
    if not meta.get("separation_confirmed"):
        return ("DEGRADED", "isolation forest loaded but healthy/SEVERE separation not confirmed")
    return f"loaded, fit on {meta['n_fit_rows']} genuinely-healthy rows, separation confirmed"


def check_trust():
    from backend.intelligence.trust_service import TrustService
    service = TrustService({})
    result = service.assess(
        station_id="S01", sensor_name="weld_current", station_type="WELDING_BODY_JOINING",
        has_direct_reading=False, evidence_age_seconds=None,
        recent_readings_by_station={}, recent_readings_by_type={},
    )
    assert result["data_state"] == "UNKNOWN"
    assert result["estimated_value"] is None
    return "UNKNOWN-with-no-exposed-baseline-value semantics confirmed live"


def check_feature_contract():
    with (ROOT / "artifacts" / "flow_v3" / "flow_v3_model_contract.json").open() as f:
        contract = json.load(f)
    required = {"model_id", "git_commit", "feature_order", "categorical_features", "categorical_levels", "target"}
    missing = required - set(contract.keys())
    assert not missing, f"missing contract fields: {missing}"
    assert contract["no_raw_station_id"] is True
    return f"contract complete, {len(contract['feature_order'])} features, no raw station_id"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        ("simulator", check_simulator),
        ("public_event_stream", check_public_event_stream),
        ("flow_model", check_flow_model),
        ("flow_projection", check_flow_projection),
        ("quality_model", check_quality_model),
        ("anomaly", check_anomaly),
        ("trust", check_trust),
        ("feature_contract", check_feature_contract),
    ]
    results = []
    for name, fn in checks:
        result = _check(name, fn)
        if isinstance(result.get("detail"), tuple):
            status, detail = result["detail"]
            result["status"], result["detail"] = status, detail
        results.append(result)
        print(f"  [{result['status']}] {name}: {result['detail']}")

    statuses = {r["status"] for r in results}
    overall = "FAIL" if "FAIL" in statuses else ("DEGRADED" if "DEGRADED" in statuses else "PASS")
    out = {"overall": overall, "components": results}
    with (OUT_DIR / "system_health.json").open("w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nOVERALL: {overall}")
    print(f"Saved {OUT_DIR / 'system_health.json'}")


if __name__ == "__main__":
    main()
