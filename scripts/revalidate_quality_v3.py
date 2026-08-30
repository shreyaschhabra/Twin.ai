"""Quality revalidation (Sections 25-28). Does NOT rebuild the Quality
architecture -- reuses the already-trained artifacts/quality model and
Dataset A (quality_v1) as-is, and only adds the additional reporting the
Flow-v3 pass asked for: per-checkpoint metrics, vehicle-level early
detection, a cohort-feature ablation, a class-weight comparison (VALIDATION
only), and a quick persistence/calibration check.

Usage:
    python scripts/revalidate_quality_v3.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score

DATA_DIR = ROOT / "data" / "processed" / "quality_v1"
ARTIFACT_DIR = ROOT / "artifacts" / "quality"
OUT_DIR = ROOT / "artifacts" / "final_submission"
CHECKPOINTS = ("S12", "S20", "S27", "S38", "S44")
COHORT_FEATURES = ("cohort_defect_rate_mean", "cohort_sample_size_mean")


def section(title: str) -> None:
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def _row_metrics(y_true, y_score, threshold: float) -> dict:
    y_pred = (y_score >= threshold).astype(int)
    good = y_true == 0
    n_good = int(good.sum())
    false_alerts_per_100_good = float(100.0 * y_pred[good].sum() / n_good) if n_good else None
    return {
        "pr_auc": float(average_precision_score(y_true, y_score)) if y_true.sum() else None,
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "false_alerts_per_100_good": false_alerts_per_100_good,
        "n": int(len(y_true)), "n_positive": int(y_true.sum()),
    }


def _best_threshold_by_f2(y_true, y_score) -> float:
    best_thr, best_f2 = 0.5, -1.0
    for thr in np.linspace(0.05, 0.95, 19):
        pred = (y_score >= thr).astype(int)
        p = precision_score(y_true, pred, zero_division=0)
        r = recall_score(y_true, pred, zero_division=0)
        f2 = 5 * p * r / (4 * p + r) if (4 * p + r) > 0 else 0.0
        if f2 > best_f2:
            best_thr, best_f2 = thr, f2
    return float(best_thr)


def _train_variant(train, val, features, cat_features, params, weight_mode: str):
    if weight_mode == "unweighted":
        scale_pos_weight = 1.0
    elif weight_mode == "sqrt":
        scale_pos_weight = float(np.sqrt((train.target == 0).sum() / max(1, (train.target == 1).sum())))
    else:
        scale_pos_weight = float((train.target == 0).sum() / max(1, (train.target == 1).sum()))
    train_set = lgb.Dataset(train[features], label=train.target, categorical_feature=cat_features, free_raw_data=False)
    val_set = lgb.Dataset(val[features], label=val.target, categorical_feature=cat_features, reference=train_set, free_raw_data=False)
    booster = lgb.train(
        {**params, "objective": "binary", "metric": "average_precision", "verbosity": -1,
         "scale_pos_weight": scale_pos_weight, "seed": 20240002},
        train_set, num_boost_round=300, valid_sets=[val_set],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)],
    )
    return booster, scale_pos_weight


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train = pd.read_parquet(DATA_DIR / "train.parquet")
    val = pd.read_parquet(DATA_DIR / "validation.parquet")
    test = pd.read_parquet(DATA_DIR / "test.parquet")
    with (ARTIFACT_DIR / "feature_list.json").open() as f:
        feature_list = json.load(f)
    features = feature_list["numeric_features"] + feature_list["categorical_features"]
    cat_features = feature_list["categorical_features"]
    with (ARTIFACT_DIR / "threshold.json").open() as f:
        frozen_threshold = json.load(f)["frozen_threshold"]
    with (ARTIFACT_DIR / "training_metadata.json").open() as f:
        meta = json.load(f)
    params = {k: v for k, v in meta["hyperparameters"].items()}

    for frame in (train, val, test):
        for feature in cat_features:
            frame[feature] = pd.Categorical(frame[feature], categories=feature_list["categorical_levels"][feature])

    model = lgb.Booster(model_file=str(ARTIFACT_DIR / "quality_lightgbm_model.txt"))
    test_scores = model.predict(test[features])
    val_scores = model.predict(val[features])

    section("A. PER-CHECKPOINT METRICS (existing production model, TEST)")
    checkpoint_report = {}
    for checkpoint in CHECKPOINTS:
        mask = test.checkpoint_station_id == checkpoint
        if mask.sum() == 0:
            continue
        m = _row_metrics(test.target[mask].to_numpy(), test_scores[mask], frozen_threshold)
        checkpoint_report[checkpoint] = m
        print(f"  {checkpoint}: n={m['n']} pos={m['n_positive']} PR-AUC={m['pr_auc']} "
              f"precision={m['precision']:.3f} recall={m['recall']:.3f} "
              f"false_alerts/100_good={m['false_alerts_per_100_good']}")

    section("B. VEHICLE-LEVEL EARLY DETECTION (existing model, TEST)")
    test_scored = test.copy()
    test_scored["score"] = test_scores
    test_scored["alert"] = test_scored.score >= frozen_threshold
    defective_vehicles = test_scored[test_scored.target == 1].vehicle_id.unique()
    ever_flagged, stations_early, time_early = 0, [], []
    for vehicle_id in defective_vehicles:
        rows = test_scored[test_scored.vehicle_id == vehicle_id].sort_values("stations_completed")
        flagged = rows[rows.alert]
        if len(flagged):
            ever_flagged += 1
            last_row = rows.iloc[-1]
            first_alert = flagged.iloc[0]
            stations_early.append(int(last_row.stations_completed - first_alert.stations_completed))
            time_early.append(float(last_row.snapshot_time - first_alert.snapshot_time))
    early_detection = {
        "n_defective_test_vehicles": int(len(defective_vehicles)),
        "pct_ever_flagged_before_s45": 100.0 * ever_flagged / len(defective_vehicles) if len(defective_vehicles) else None,
        "median_stations_early": float(np.median(stations_early)) if stations_early else None,
        "median_seconds_early": float(np.median(time_early)) if time_early else None,
    }
    print(json.dumps(early_detection, indent=2))

    section("C. COHORT ABLATION (retrain without cohort_defect_rate_mean/cohort_sample_size_mean)")
    ablated_features = [f for f in features if f not in COHORT_FEATURES]
    full_booster, _ = _train_variant(train, val, features, cat_features, params, "full")
    ablated_booster, _ = _train_variant(train, val, ablated_features, cat_features, params, "full")
    full_test_pr_auc = float(average_precision_score(test.target, full_booster.predict(test[features])))
    ablated_test_pr_auc = float(average_precision_score(test.target, ablated_booster.predict(test[ablated_features])))
    cohort_ablation = {
        "full_features_test_pr_auc": full_test_pr_auc,
        "without_cohort_features_test_pr_auc": ablated_test_pr_auc,
        "pr_auc_drop": full_test_pr_auc - ablated_test_pr_auc,
        "note": "Retrained with identical hyperparameters and TRAIN/VAL for a like-for-like comparison; "
                "not the production model, which keeps cohort features.",
    }
    print(json.dumps(cohort_ablation, indent=2))

    section("D. CLASS WEIGHT COMPARISON (VALIDATION only)")
    weight_report = {}
    for mode in ("unweighted", "sqrt", "full"):
        booster, spw = _train_variant(train, val, features, cat_features, params, mode)
        scores = booster.predict(val[features])
        thr = _best_threshold_by_f2(val.target.to_numpy(), scores)
        m = _row_metrics(val.target.to_numpy(), scores, thr)
        m["scale_pos_weight"] = spw
        m["threshold_used"] = thr
        weight_report[mode] = m
        print(f"  {mode} (spw={spw:.2f}): PR-AUC={m['pr_auc']:.3f} precision={m['precision']:.3f} "
              f"recall={m['recall']:.3f} false_alerts/100_good={m['false_alerts_per_100_good']:.2f} "
              f"@thr={thr:.2f}")
    current_mode = "full" if abs(meta["scale_pos_weight"] - (train.target == 0).sum() / max(1, (train.target == 1).sum())) < 1e-6 else "unknown"
    print(f"production model's weighting matches: {current_mode}")

    section("E. PERSISTENCE / CALIBRATION QUICK CHECK")
    brier = float(brier_score_loss(test.target, test_scores))
    persistence_alert = test_scored.groupby("vehicle_id").alert.apply(
        lambda s: (s.rolling(2).sum() >= 2).any()
    )
    persistence_labels = test_scored.groupby("vehicle_id").target.max()
    aligned = persistence_alert.reindex(persistence_labels.index).fillna(False)
    persistence_recall = float(recall_score(persistence_labels, aligned)) if persistence_labels.sum() else None
    raw_vehicle_alert = test_scored.groupby("vehicle_id").alert.max().reindex(persistence_labels.index).fillna(False)
    raw_recall = float(recall_score(persistence_labels, raw_vehicle_alert)) if persistence_labels.sum() else None
    calibration = {
        "brier_score": brier,
        "raw_single_checkpoint_vehicle_recall": raw_recall,
        "two_consecutive_checkpoint_vehicle_recall": persistence_recall,
        "recommendation": (
            "reject persistence" if (persistence_recall is not None and raw_recall is not None and persistence_recall < raw_recall - 0.02)
            else "persistence does not materially hurt recall; still using raw single-checkpoint alerting for simplicity"
        ),
    }
    print(json.dumps(calibration, indent=2))

    section("F. SAVE")
    out = {
        "per_checkpoint_metrics": checkpoint_report,
        "early_detection": early_detection,
        "cohort_ablation": cohort_ablation,
        "class_weight_comparison": weight_report,
        "production_weighting": current_mode,
        "calibration_check": calibration,
        "note": "Production Quality model and Dataset A are unchanged; this is additional validation reporting only.",
    }
    with (OUT_DIR / "quality_metrics.json").open("w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Saved {OUT_DIR / 'quality_metrics.json'}")


if __name__ == "__main__":
    main()
