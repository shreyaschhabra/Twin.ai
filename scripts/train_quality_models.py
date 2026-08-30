"""
Quality baseline + final model (Sections 19-24): LogisticRegression
baseline, LightGBM final model, validation-only threshold, and the
early-defect-detection metric (Section 22) -- for eventually-defective
vehicles, how early (in stations/time before S45) does the model's risk
cross the HIGH-risk threshold.

Usage:
    python scripts/train_quality_models.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

from backend.config.loader import load_factory_config
from backend.quality.baselines import build_logistic_regression_pipeline
from backend.quality.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from backend.quality.snapshots import CHECKPOINT_STATIONS

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "quality_v1"
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "quality"
CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
SEED = 20240002


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def prep_categoricals(train, val, test, cat_features):
    for col in cat_features:
        cats = pd.Categorical(train[col]).categories
        for df in (train, val, test):
            df[col] = pd.Categorical(df[col], categories=cats)
    return train, val, test


def row_metrics(y_true, y_score, threshold):
    y_pred = (y_score >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, y_score)) if len(set(y_true)) > 1 else None,
        "roc_auc": float(roc_auc_score(y_true, y_score)) if len(set(y_true)) > 1 else None,
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "threshold": threshold,
    }


def _pr_auc_feval(preds, dataset):
    labels = dataset.get_label()
    return "pr_auc", average_precision_score(labels, preds), True


def train_lgbm(train, val, features, cat_features, params, seed=SEED):
    scale_pos_weight = (train.target == 0).sum() / max(1, (train.target == 1).sum())
    full_params = dict(objective="binary", metric="None", verbosity=-1, seed=seed, scale_pos_weight=scale_pos_weight, **params)
    train_set = lgb.Dataset(train[features], label=train.target, categorical_feature=cat_features, free_raw_data=False)
    val_set = lgb.Dataset(val[features], label=val.target, categorical_feature=cat_features, reference=train_set, free_raw_data=False)
    model = lgb.train(
        full_params, train_set, num_boost_round=500, valid_sets=[val_set], feval=_pr_auc_feval,
        callbacks=[lgb.early_stopping(40, verbose=False, first_metric_only=True), lgb.log_evaluation(0)],
    )
    return model, scale_pos_weight


def _route_positions_remaining(config) -> dict:
    """stations remaining from each checkpoint to S45, per variant (EV
    skips S35, so its route is one station shorter)."""
    out = {}
    for variant_id, variant_cfg in config.vehicle_variants.items():
        route = variant_cfg.route
        for cp in CHECKPOINT_STATIONS:
            idx = route.index(cp)
            out[(variant_id, cp)] = len(route) - idx - 1
    return out


def main():
    t0 = time.time()
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    with (OUT_DIR / "dataset_manifest.json").open() as f:
        manifest = json.load(f)
    numeric_features, categorical_features = manifest["numeric_features"], manifest["categorical_features"]
    features = numeric_features + categorical_features

    train = pd.read_parquet(OUT_DIR / "train.parquet")
    val = pd.read_parquet(OUT_DIR / "validation.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")
    train, val, test = prep_categoricals(train, val, test, categorical_features)

    section("1. BASELINE -- LOGISTIC REGRESSION")
    baseline_pipe = build_logistic_regression_pipeline(numeric_features, categorical_features)
    baseline_pipe.fit(train[features], train.target)
    baseline_metrics = {}
    for name, df in [("validation", val), ("test", test)]:
        scores = baseline_pipe.predict_proba(df[features])[:, 1]
        m = row_metrics(df.target.values, scores, 0.5)
        baseline_metrics[name] = m
        print(f"{name}: precision={m['precision']:.3f} recall={m['recall']:.3f} f1={m['f1']:.3f} PR-AUC={m['pr_auc']:.3f}")

    section("2. FINAL MODEL -- LIGHTGBM (modest tuning, PR-AUC early stopping)")
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 7, 63),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 100),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 1.0),
            "bagging_freq": 1,
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 5.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 5.0, log=True),
        }
        model, _ = train_lgbm(train, val, features, categorical_features, params)
        return average_precision_score(val.target, model.predict(val[features]))

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(objective, n_trials=15, show_progress_bar=False)
    print(f"Best trial PR-AUC={study.best_value:.4f}, params={study.best_params}")

    final_model, scale_pos_weight = train_lgbm(train, val, features, categorical_features, study.best_params)
    print(f"best_iteration={final_model.best_iteration}, scale_pos_weight={scale_pos_weight:.2f}")
    val_scores = final_model.predict(val[features])
    test_scores = final_model.predict(test[features])

    section("3. THRESHOLD SELECTION (VALIDATION ONLY)")
    grid = np.round(np.arange(0.1, 0.91, 0.05), 2)
    threshold_rows = []
    for thr in grid:
        m = row_metrics(val.target.values, val_scores, thr)
        alert_freq = float((val_scores >= thr).mean())
        f2 = (5 * m["precision"] * m["recall"] / (4 * m["precision"] + m["recall"])) if (m["precision"] + m["recall"]) > 0 else 0.0
        threshold_rows.append({"threshold": float(thr), "precision": m["precision"], "recall": m["recall"], "f2": f2, "alert_frequency": alert_freq})
        print(f"  thr={thr}: precision={m['precision']:.3f} recall={m['recall']:.3f} f2={f2:.3f} alert_freq={alert_freq:.4f}")
    frozen_threshold = max(threshold_rows, key=lambda r: r["f2"])["threshold"]
    print(f"\nFROZEN THRESHOLD = {frozen_threshold} (max F2 on VALIDATION)")

    section("4. VALIDATION / TEST METRICS AT FROZEN THRESHOLD")
    val_metrics = row_metrics(val.target.values, val_scores, frozen_threshold)
    test_metrics = row_metrics(test.target.values, test_scores, frozen_threshold)
    print("VALIDATION:", json.dumps(val_metrics, indent=2))
    print("TEST:", json.dumps(test_metrics, indent=2))

    section("5. EARLY-DEFECT-DETECTION METRIC (Section 22)")
    route_remaining = _route_positions_remaining(config)
    test_with_scores = test.copy()
    test_with_scores["risk"] = test_scores
    defective_vehicles = test_with_scores[test_with_scores.target == 1].vehicle_id.unique()
    print(f"Eventually-defective vehicles in TEST: {len(defective_vehicles)}")

    detected_early = []
    for vid in defective_vehicles:
        vrows = test_with_scores[test_with_scores.vehicle_id == vid].sort_values("production_stage")
        crossed = vrows[vrows.risk >= frozen_threshold]
        if len(crossed) == 0:
            continue
        first = crossed.iloc[0]
        last_snapshot_time = vrows.snapshot_time.max()
        stations_remaining = route_remaining.get((first.vehicle_variant, first.checkpoint_station_id))
        time_remaining = float(last_snapshot_time - first.snapshot_time)
        detected_early.append({
            "vehicle_id": vid, "detected_at_stage": int(first.production_stage),
            "stations_remaining_after_detection": stations_remaining, "time_remaining_seconds_approx": time_remaining,
        })

    pct_detected = len(detected_early) / max(1, len(defective_vehicles)) * 100
    print(f"Detected before final QC: {len(detected_early)}/{len(defective_vehicles)} ({pct_detected:.1f}%)")
    if detected_early:
        stations_vals = [d["stations_remaining_after_detection"] for d in detected_early if d["stations_remaining_after_detection"] is not None]
        time_vals = [d["time_remaining_seconds_approx"] for d in detected_early]
        median_stations = float(np.median(stations_vals)) if stations_vals else None
        median_time = float(np.median(time_vals)) if time_vals else None
        by_checkpoint = pd.Series([d["detected_at_stage"] for d in detected_early]).value_counts().sort_index().to_dict()
        print(f"Median stations early: {median_stations}")
        print(f"Median time early (approx, to pre-EOL checkpoint S44): {median_time:.1f}s")
        print(f"Distribution by detecting checkpoint (production_stage): {by_checkpoint}")
    else:
        median_stations, median_time, by_checkpoint = None, None, {}

    section("6. EVIDENCE (LightGBM native contributions)")
    rng = np.random.RandomState(SEED)
    sample_idx = rng.choice(len(val), size=min(10000, len(val)), replace=False)
    contrib = final_model.predict(val.iloc[sample_idx][features], pred_contrib=True)
    contrib_df = pd.DataFrame(contrib[:, :-1], columns=features)
    top_global = contrib_df.abs().mean().sort_values(ascending=False).head(10)
    print("Top 10 global features:")
    for feat, imp in top_global.items():
        print(f"  {feat}: {imp:.4f}")

    section("7. SAVE ARTIFACTS")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(ARTIFACT_DIR / "quality_lightgbm_model.txt"))
    joblib.dump(final_model, ARTIFACT_DIR / "quality_lightgbm_model.joblib")
    joblib.dump(baseline_pipe, ARTIFACT_DIR / "quality_logistic_baseline.joblib")

    with (ARTIFACT_DIR / "feature_list.json").open("w") as f:
        json.dump({"numeric_features": numeric_features, "categorical_features": categorical_features,
                    "categorical_levels": {c: list(pd.Categorical(train[c]).categories) for c in categorical_features}}, f, indent=2)
    with (ARTIFACT_DIR / "threshold.json").open("w") as f:
        json.dump({"frozen_threshold": frozen_threshold, "selection_criterion": "max F2 on VALIDATION", "threshold_grid": threshold_rows}, f, indent=2)

    metadata = {
        "model_type": "LightGBM (binary classification)",
        "code_commit": git_commit(),
        "source_dataset": "data/processed/quality_v1 (Dataset A naturalistic corpus)",
        "split_definition": manifest["split"],
        "hyperparameters": study.best_params,
        "scale_pos_weight": scale_pos_weight,
        "frozen_threshold": frozen_threshold,
        "baseline_metrics": baseline_metrics,
        "validation_metrics": val_metrics,
        "test_metrics": test_metrics,
        "early_detection": {
            "pct_defective_detected_before_qc": pct_detected,
            "median_stations_early": median_stations,
            "median_time_early_seconds_approx": median_time,
            "distribution_by_checkpoint_stage": by_checkpoint,
        },
        "top_global_features": top_global.to_dict(),
        "training_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "known_limitations": [
            "This is synthetic validation against a simulated final QC outcome, not customer production validation.",
            "Early-detection 'time remaining' is approximated as time to the vehicle's own S44 (pre-EOL) snapshot, not the exact S45 timestamp.",
        ],
    }
    with (ARTIFACT_DIR / "training_metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"Artifacts saved to {ARTIFACT_DIR}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
