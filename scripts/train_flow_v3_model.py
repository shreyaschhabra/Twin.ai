"""Flow-v3 service-capability model (Sections 17-20, 22, 32): Ridge
baseline, LightGBM final, interpretable feature reduction, and pred_contrib
explainability -- trained on the frozen TEST-untouched-until-the-end
Flow-v3 corpus.

Usage:
    python scripts/train_flow_v3_model.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler

from backend.flow_v3.feature_selection import select_features
from backend.flow_v3.observations import CATEGORICAL_FEATURES

DATA_DIR = ROOT / "data" / "processed" / "flow_v3"
ARTIFACT_DIR = ROOT / "artifacts" / "flow_v3"
TARGET = "future_service_rate_vph"
NON_FEATURE_COLUMNS = {
    "run_id", "partition", "mechanism", "severity", "profile", "target_station_id",
    "station_id", "observation_time",
    "future_service_rate_vph", "future_completions_count", "baseline_service_rate_vph",
    "future_service_ratio_to_baseline", "congestion_regime_active_at_t",
    "next_regime_onset_time", "lead_seconds_to_next_regime",
}


def section(title: str) -> None:
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def _candidate_features(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in NON_FEATURE_COLUMNS]


def _regression_metrics(y_true, y_pred) -> dict:
    mae = float(mean_absolute_error(y_true, y_pred))
    return {
        "mae_vph": mae,
        "normalized_mae": mae / float(np.mean(y_true)),
        "r2": float(r2_score(y_true, y_pred)),
        "n": int(len(y_true)),
    }


def _ridge_matrix(df: pd.DataFrame, numeric_features: list[str], categorical_features: list[str],
                   categories: dict[str, list[str]], medians: pd.Series) -> np.ndarray:
    numeric = df[numeric_features].fillna(medians).to_numpy(dtype=float)
    blocks = [numeric]
    for feature in categorical_features:
        levels = categories[feature]
        one_hot = np.zeros((len(df), len(levels)))
        for i, level in enumerate(levels):
            one_hot[:, i] = (df[feature] == level).astype(float)
        blocks.append(one_hot)
    return np.hstack(blocks)


def main():
    section("0. LOAD DATA")
    train = pd.read_parquet(DATA_DIR / "train.parquet")
    val = pd.read_parquet(DATA_DIR / "validation.parquet")
    test = pd.read_parquet(DATA_DIR / "test.parquet")
    print(f"train={len(train)} rows / {train.run_id.nunique()} runs, "
          f"validation={len(val)} / {val.run_id.nunique()}, test={len(test)} / {test.run_id.nunique()}")
    assert set(train.run_id) & set(val.run_id) == set()
    assert set(train.run_id) & set(test.run_id) == set()
    assert set(val.run_id) & set(test.run_id) == set()

    section("1. FEATURE SELECTION (Section 19) -- TRAIN ONLY")
    candidates = _candidate_features(train)
    report = select_features(train, candidates)
    print(f"raw={report.raw_count} -> after_basic_filter={report.after_basic_filter} "
          f"-> after_correlation_filter={report.after_correlation_filter}")
    print(f"dropped constant: {report.dropped_constant}")
    print(f"dropped near-constant: {report.dropped_near_constant}")
    print(f"dropped duplicate: {report.dropped_duplicate}")
    for dropped, kept, corr in report.dropped_correlated:
        print(f"  dropped {dropped!r} (|r|={corr:.3f} with kept {kept!r})")

    features = report.kept_features
    numeric_features = [f for f in features if f not in CATEGORICAL_FEATURES]
    categorical_features = [f for f in features if f in CATEGORICAL_FEATURES]
    categories = {f: sorted(train[f].dropna().unique().tolist()) for f in categorical_features}
    print(f"final features ({len(features)}): {features}")

    section("2. BASELINE -- RIDGE")
    medians = train[numeric_features].median()
    scaler = StandardScaler().fit(_ridge_matrix(train, numeric_features, categorical_features, categories, medians))
    x_train = scaler.transform(_ridge_matrix(train, numeric_features, categorical_features, categories, medians))
    x_val = scaler.transform(_ridge_matrix(val, numeric_features, categorical_features, categories, medians))
    x_test = scaler.transform(_ridge_matrix(test, numeric_features, categorical_features, categories, medians))
    y_train, y_val, y_test = train[TARGET].to_numpy(), val[TARGET].to_numpy(), test[TARGET].to_numpy()

    best_ridge, best_ridge_val_mae, best_alpha = None, float("inf"), None
    for alpha in (0.1, 1.0, 10.0, 100.0):
        model = Ridge(alpha=alpha).fit(x_train, y_train)
        val_mae = mean_absolute_error(y_val, model.predict(x_val))
        print(f"  ridge alpha={alpha}: val MAE={val_mae:.3f}")
        if val_mae < best_ridge_val_mae:
            best_ridge, best_ridge_val_mae, best_alpha = model, val_mae, alpha
    ridge_val_metrics = _regression_metrics(y_val, best_ridge.predict(x_val))
    ridge_test_metrics = _regression_metrics(y_test, best_ridge.predict(x_test))
    print(f"Ridge (alpha={best_alpha}) VALIDATION: {ridge_val_metrics}")
    print(f"Ridge (alpha={best_alpha}) TEST: {ridge_test_metrics}")

    section("3. FINAL MODEL -- LIGHTGBM (small manual grid, VALIDATION only)")
    train_set = train.copy()
    val_set = val.copy()
    test_set = test.copy()
    for frame in (train_set, val_set, test_set):
        for feature in categorical_features:
            frame[feature] = pd.Categorical(frame[feature], categories=categories[feature])

    lgb_train = lgb.Dataset(train_set[features], label=y_train, categorical_feature=categorical_features, free_raw_data=False)
    lgb_val = lgb.Dataset(val_set[features], label=y_val, categorical_feature=categorical_features, reference=lgb_train, free_raw_data=False)

    grid = [
        {"num_leaves": 15, "learning_rate": 0.05, "min_child_samples": 30},
        {"num_leaves": 31, "learning_rate": 0.05, "min_child_samples": 20},
        {"num_leaves": 31, "learning_rate": 0.1, "min_child_samples": 20},
        {"num_leaves": 63, "learning_rate": 0.05, "min_child_samples": 15},
    ]
    best_model, best_val_mae, best_params, best_iteration = None, float("inf"), None, None
    for params in grid:
        booster = lgb.train(
            {"objective": "regression_l1", "metric": "mae", "verbosity": -1, "seed": 20260830, **params},
            lgb_train, num_boost_round=400, valid_sets=[lgb_val],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)],
        )
        val_pred = booster.predict(val_set[features], num_iteration=booster.best_iteration)
        val_mae = mean_absolute_error(y_val, val_pred)
        print(f"  lgbm {params} best_iteration={booster.best_iteration} val MAE={val_mae:.3f}")
        if val_mae < best_val_mae:
            best_model, best_val_mae, best_params, best_iteration = booster, val_mae, params, booster.best_iteration

    lgbm_val_metrics = _regression_metrics(y_val, best_model.predict(val_set[features], num_iteration=best_iteration))
    lgbm_test_metrics = _regression_metrics(y_test, best_model.predict(test_set[features], num_iteration=best_iteration))
    print(f"LightGBM (params={best_params}, iter={best_iteration}) VALIDATION: {lgbm_val_metrics}")
    print(f"LightGBM (params={best_params}, iter={best_iteration}) TEST: {lgbm_test_metrics}")

    section("4. EXPLAINABILITY -- PRED_CONTRIB RECONSTRUCTION CHECK (Section 22)")
    sample = test_set[features].iloc[:50]
    preds = best_model.predict(sample, num_iteration=best_iteration)
    contrib = best_model.predict(sample, num_iteration=best_iteration, pred_contrib=True)
    reconstructed = contrib.sum(axis=1)
    max_abs_diff = float(np.max(np.abs(reconstructed - preds)))
    print(f"max |sum(pred_contrib) - prediction| over {len(sample)} rows: {max_abs_diff:.6f}")
    assert max_abs_diff < 1e-6, "pred_contrib does not reconstruct the model prediction"

    section("5. SAVE ARTIFACTS")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    best_model.save_model(str(ARTIFACT_DIR / "flow_v3_lightgbm_model.txt"))

    with (ARTIFACT_DIR / "feature_selection_report.json").open("w") as f:
        json.dump(report.as_dict(), f, indent=2)

    contract = {
        "model_id": "flow_v3_lightgbm_service_capability_v1",
        "git_commit": git_commit(),
        "target": TARGET,
        "target_definition": "3600 / mean(actual future STATION_PROCESSING_COMPLETED durations in (t, t+300s]); "
                              "rows with zero future completions are excluded, never coded as 0.",
        "feature_order": features,
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
        "categorical_levels": categories,
        "no_raw_station_id": "station_id" not in features,
        "train_run_ids": sorted(train.run_id.unique().tolist()),
        "validation_run_ids": sorted(val.run_id.unique().tolist()),
        "test_run_ids": sorted(test.run_id.unique().tolist()),
        "params": {**best_params, "objective": "regression_l1", "best_iteration": best_iteration},
        "metrics": {
            "ridge_baseline": {"alpha": best_alpha, "validation": ridge_val_metrics, "test": ridge_test_metrics},
            "lightgbm_final": {"validation": lgbm_val_metrics, "test": lgbm_test_metrics},
        },
        "explainability_reconstruction_max_abs_diff": max_abs_diff,
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    with (ARTIFACT_DIR / "flow_v3_model_contract.json").open("w") as f:
        json.dump(contract, f, indent=2, default=str)
    print(f"Artifacts saved to {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
