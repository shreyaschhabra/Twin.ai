"""
Anomaly layer training (Part C): Isolation Forest fit on nominal/low-risk
Flow rows only, plus statistical baselines for the z-score/EWMA signal
features. The EQUIPMENT_DEGRADATION holdout is NEVER used for fitting --
it is reserved entirely for the post-hoc diagnostic in Section 27.

Uses the already-saved data/processed/flow_v2/ (Dataset C) train split's
NEGATIVE rows as the nominal population, and the already-saved
unseen_equipment_degradation.parquet + latent/scenario_truth.parquet for
the before/during degradation diagnostic.

Usage:
    python scripts/train_anomaly_models.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import numpy as np
import pandas as pd

from backend.anomaly.combined import build_anomaly_output
from backend.anomaly.isolation_forest_model import DEFAULT_ANOMALY_FEATURES, isolation_forest_anomaly_score, train_isolation_forest
from backend.anomaly.statistical import SIGNAL_FEATURES, Z_THRESHOLD, compute_statistical_anomaly_score

FLOW_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v2"
DATASET_C_LATENT = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated" / "latent" / "scenario_truth.parquet"
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "anomaly"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    t0 = time.time()
    train = pd.read_parquet(FLOW_DIR / "train.parquet")
    holdout = pd.read_parquet(FLOW_DIR / "unseen_equipment_degradation.parquet")
    scenario_truth = pd.read_parquet(DATASET_C_LATENT)

    section("1. FIT ON NOMINAL/LOW-RISK ROWS ONLY (TRAIN NEGATIVE rows -- degradation holdout untouched)")
    nominal = train[train.target == 0]
    print(f"Nominal fitting population: {len(nominal):,} rows (holdout excluded: {len(holdout):,} rows never touched)")
    pipe, features = train_isolation_forest(nominal)
    print(f"Isolation Forest fit on {len(features)} features: {features}")

    feature_baselines = {
        feat: {"mean": float(nominal[feat].mean()), "std": float(nominal[feat].std())}
        for feat in SIGNAL_FEATURES if feat in nominal.columns
    }

    section("2. NOMINAL VS. CONTROLLED-ABNORMAL SANITY CHECK")
    nominal_sample = nominal.sample(min(20000, len(nominal)), random_state=20240002)
    nominal_scores = isolation_forest_anomaly_score(pipe, features, nominal_sample)
    abnormal_sample = train[train.target == 1]  # true positives = genuinely abnormal by construction
    abnormal_scores = isolation_forest_anomaly_score(pipe, features, abnormal_sample) if len(abnormal_sample) else np.array([])
    print(f"Nominal (n={len(nominal_sample)}) mean anomaly score: {nominal_scores.mean():.4f}")
    if len(abnormal_scores):
        print(f"Abnormal/positive (n={len(abnormal_sample)}) mean anomaly score: {abnormal_scores.mean():.4f}")
        print(f"Separation confirmed: {'YES' if abnormal_scores.mean() > nominal_scores.mean() else 'NO -- INVESTIGATE'}")

    section("3. EQUIPMENT_DEGRADATION HOLDOUT DIAGNOSTIC (evaluation only, never used for fitting/tuning)")
    holdout_scores = isolation_forest_anomaly_score(pipe, features, holdout)
    holdout_eval = holdout.copy()
    holdout_eval["iforest_score"] = holdout_scores

    degradation = scenario_truth[scenario_truth.family == "EQUIPMENT_DEGRADATION"].copy()
    degradation["station_ids_parsed"] = degradation.station_ids.apply(
        lambda s: json.loads(s) if isinstance(s, str) else s
    )

    before_scores, during_scores = [], []
    detection_lead_times = []
    for scen in degradation.itertuples():
        for sid in scen.station_ids_parsed:
            rows = holdout_eval[(holdout_eval.shift_id == scen.shift_id) & (holdout_eval.station_id == sid)]
            if len(rows) == 0:
                continue
            end_time = scen.end_time if pd.notna(scen.end_time) else rows.window_end_time.max()
            before = rows[rows.window_end_time < scen.start_time]
            during = rows[(rows.window_end_time >= scen.start_time) & (rows.window_end_time <= end_time)]
            before_scores.extend(before.iforest_score.tolist())
            during_scores.extend(during.iforest_score.tolist())
            crossed = during[during.iforest_score >= 0.5]
            if len(crossed):
                detection_lead_times.append(float(crossed.window_end_time.min() - scen.start_time))

    before_arr, during_arr = np.array(before_scores), np.array(during_scores)
    detection_rate = float((during_arr >= 0.5).mean()) if len(during_arr) else None
    print(f"Rows scored -- before degradation: {len(before_arr)}, during: {len(during_arr)}")
    if len(before_arr):
        print(f"Mean anomaly score BEFORE degradation onset: {before_arr.mean():.4f}")
    if len(during_arr):
        print(f"Mean anomaly score DURING degradation: {during_arr.mean():.4f}")
        print(f"Detection rate (score>=0.5 during degradation): {detection_rate:.3f}" if detection_rate is not None else "n/a")
    if detection_lead_times:
        print(f"Approx. detection lead time (seconds after degradation onset, mean): {np.mean(detection_lead_times):.1f}")
    else:
        print("No clean per-scenario detection lead time computed (documented limitation, not tuned further).")

    section("4. SAVE ARTIFACTS")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipe": pipe, "features": features}, ARTIFACT_DIR / "isolation_forest.joblib")

    metadata = {
        "method": "IsolationForest (200 estimators) + rolling z-score/EWMA statistical layer",
        "fit_population": "Dataset C flow_v2 TRAIN, target==0 rows only (nominal/low-risk)",
        "n_fit_rows": len(nominal),
        "features": features,
        "feature_baselines": feature_baselines,
        "nominal_mean_score": float(nominal_scores.mean()),
        "abnormal_mean_score": float(abnormal_scores.mean()) if len(abnormal_scores) else None,
        "degradation_holdout_diagnostic": {
            "n_before_rows": int(len(before_arr)), "n_during_rows": int(len(during_arr)),
            "mean_score_before": float(before_arr.mean()) if len(before_arr) else None,
            "mean_score_during": float(during_arr.mean()) if len(during_arr) else None,
            "detection_rate_at_0.5": detection_rate,
            "mean_detection_lead_seconds": float(np.mean(detection_lead_times)) if detection_lead_times else None,
        },
        "training_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    with (ARTIFACT_DIR / "metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"Artifacts saved to {ARTIFACT_DIR}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
