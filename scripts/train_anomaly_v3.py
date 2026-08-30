"""Flow-v3 anomaly layer (Section 29): fit on GENUINELY healthy rows only.

Correctness fix vs. the old flow_v2 anomaly layer: that layer fit on
"Flow target == 0" rows, which conflates "no bottleneck yet" with "truly
undisturbed" -- a row can have target==0 while still sitting inside an
active MILD/MODERATE scenario. Flow-v3's corpus predeclares dedicated
HEALTHY_CONTROL runs (Section 14) with no scenario active at all; those,
and only those, are the nominal fitting population here.

Usage:
    python scripts/train_anomaly_v3.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backend.anomaly.isolation_forest_model import isolation_forest_anomaly_score, train_isolation_forest
from backend.anomaly.statistical import Z_THRESHOLD, rolling_zscore
from backend.flow_v3.scenario_physics import DEGRADATION_DURATION_MINUTES

DATA_DIR = ROOT / "data" / "processed" / "flow_v3"
ARTIFACT_DIR = ROOT / "artifacts" / "anomaly_v3"
SCENARIO_START_SECONDS = 7200.0

FLOW_V3_ANOMALY_FEATURES = [
    "svc_cycle_time_ratio_to_baseline", "svc_cycle_time_trend_seconds", "svc_cycle_time_std_seconds",
    "svc_departure_rate_trend", "ms_rate_per_minute", "ms_rate_trend", "ms_mean_duration_seconds",
    "sensor_drift_from_baseline", "sensor_trend",
]


def section(title: str) -> None:
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    train = pd.read_parquet(DATA_DIR / "train.parquet")
    val = pd.read_parquet(DATA_DIR / "validation.parquet")
    degradation = pd.read_parquet(DATA_DIR / "unseen_equipment_degradation.parquet")

    section("0. NOMINAL FITTING POPULATION: HEALTHY_CONTROL RUNS ONLY")
    nominal = train[train.mechanism == "HEALTHY_CONTROL"]
    non_healthy = train[train.mechanism != "HEALTHY_CONTROL"]
    print(f"nominal (HEALTHY_CONTROL) rows: {len(nominal)} from {nominal.run_id.nunique()} runs")
    print(f"excluded from fitting (any active scenario, including MILD/target==0 rows): {len(non_healthy)} rows")

    features = [f for f in FLOW_V3_ANOMALY_FEATURES if f in nominal.columns]
    pipe, features = train_isolation_forest(nominal, features)
    print(f"fit on {len(features)} features: {features}")

    section("1. SEPARATION SANITY CHECK: healthy vs SEVERE-mechanism rows")
    nominal_scores = isolation_forest_anomaly_score(pipe, features, nominal)
    severe = train[train.severity == "SEVERE"]
    severe_scores = isolation_forest_anomaly_score(pipe, features, severe) if len(severe) else np.array([])
    print(f"healthy (n={len(nominal)}) mean score: {nominal_scores.mean():.4f}")
    separation_confirmed = None
    if len(severe_scores):
        print(f"SEVERE (n={len(severe)}) mean score: {severe_scores.mean():.4f}")
        separation_confirmed = bool(severe_scores.mean() > nominal_scores.mean())
        print(f"separation confirmed: {'YES' if separation_confirmed else 'NO -- INVESTIGATE'}")

    section("2. VALIDATION-SET CHECK (never used for fitting)")
    val_nominal = val[val.mechanism == "HEALTHY_CONTROL"]
    val_scores = isolation_forest_anomaly_score(pipe, features, val_nominal) if len(val_nominal) else np.array([])
    if len(val_scores):
        print(f"held-out healthy validation (n={len(val_nominal)}) mean score: {val_scores.mean():.4f} "
              f"(should track the fitting population's mean, not drift)")

    section("3. EQUIPMENT_DEGRADATION UNSEEN HOLDOUT DIAGNOSTIC (never used for fitting/tuning)")
    degradation = degradation.copy()
    degradation["scenario_end_seconds"] = degradation.severity.map(
        lambda s: SCENARIO_START_SECONDS + DEGRADATION_DURATION_MINUTES[s] * 60.0
    )
    degradation_scores = isolation_forest_anomaly_score(pipe, features, degradation)
    degradation["iforest_score"] = degradation_scores
    before = degradation[degradation.observation_time < SCENARIO_START_SECONDS]
    during = degradation[
        (degradation.observation_time >= SCENARIO_START_SECONDS)
        & (degradation.observation_time <= degradation.scenario_end_seconds)
    ]
    detection_rate = float((during.iforest_score >= 0.5).mean()) if len(during) else None
    print(f"before (n={len(before)}) mean score: {before.iforest_score.mean() if len(before) else float('nan'):.4f}")
    print(f"during (n={len(during)}) mean score: {during.iforest_score.mean() if len(during) else float('nan'):.4f}")
    print(f"detection rate (score>=0.5 during degradation): {detection_rate}")

    section("4. STATISTICAL LAYER (rolling z-score) ON HEALTHY VS SEVERE, PER RUN")
    def _zscore_flag_rate(df: pd.DataFrame) -> float:
        flagged = []
        for _, run_df in df.sort_values("observation_time").groupby("run_id"):
            z = rolling_zscore(run_df["svc_cycle_time_ratio_to_baseline"])
            flagged.append((z.abs() > Z_THRESHOLD).mean())
        return float(np.nanmean(flagged)) if flagged else None

    z_healthy = _zscore_flag_rate(nominal)
    z_severe = _zscore_flag_rate(severe) if len(severe) else None
    print(f"z-score flag rate, healthy runs: {z_healthy}")
    print(f"z-score flag rate, SEVERE runs: {z_severe}")

    section("5. SAVE")
    import joblib
    joblib.dump({"pipe": pipe, "features": features}, ARTIFACT_DIR / "isolation_forest_v3.joblib")
    metadata = {
        "method": "IsolationForest (200 estimators) + rolling z-score, fit on GENUINELY HEALTHY rows only",
        "fit_population": "flow_v3 TRAIN rows with mechanism == HEALTHY_CONTROL (no scenario active at all)",
        "n_fit_rows": int(len(nominal)),
        "n_excluded_non_healthy_rows": int(len(non_healthy)),
        "features": features,
        "nominal_mean_score": float(nominal_scores.mean()),
        "severe_mean_score": float(severe_scores.mean()) if len(severe_scores) else None,
        "separation_confirmed": separation_confirmed,
        "held_out_healthy_validation_mean_score": float(val_scores.mean()) if len(val_scores) else None,
        "degradation_holdout_diagnostic": {
            "n_before": int(len(before)), "n_during": int(len(during)),
            "mean_score_before": float(before.iforest_score.mean()) if len(before) else None,
            "mean_score_during": float(during.iforest_score.mean()) if len(during) else None,
            "detection_rate_at_0.5": detection_rate,
        },
        "statistical_layer_zscore_flag_rate": {"healthy": z_healthy, "severe": z_severe},
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    with (ARTIFACT_DIR / "metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"Artifacts saved to {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
