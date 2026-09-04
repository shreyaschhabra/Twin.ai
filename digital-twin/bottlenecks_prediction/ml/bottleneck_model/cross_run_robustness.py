"""Run 5-fold run-level cross-validation for the causal bottleneck XGBoost model.

Every simulation run stays wholly inside train, validation, or test for a fold.
The decision threshold is selected only on that fold's validation runs.
Each labeled row appears in an outer test fold exactly once.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold
from xgboost import XGBClassifier

try:
    from .train_bottleneck_xgboost import (
        BOTTLENECK_FEATURES,
        TARGET,
        harmonize_types,
        load_dataset,
        metrics,
        per_run_metrics,
        pick_threshold,
        validate_training_contract,
    )
except ImportError:  # Direct script execution
    from train_bottleneck_xgboost import (
        BOTTLENECK_FEATURES,
        TARGET,
        harmonize_types,
        load_dataset,
        metrics,
        per_run_metrics,
        pick_threshold,
        validate_training_contract,
    )


def scenario_name(run_id: str) -> str:
    parts = str(run_id).split("_", 2)
    return parts[2] if len(parts) >= 3 else str(run_id)


def make_model(seed: int) -> XGBClassifier:
    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        tree_method="hist",
        enable_categorical=True,
        n_estimators=1200,
        max_depth=5,
        learning_rate=0.05,
        min_child_weight=5,
        subsample=0.90,
        colsample_bytree=0.90,
        reg_lambda=2.0,
        random_state=seed,
        n_jobs=-1,
        early_stopping_rounds=80,
    )


def aggregate(metric_rows: list[dict], names: list[str]) -> dict:
    out = {}
    for name in names:
        values = np.array([float(row[name]) for row in metric_rows], dtype=float)
        out[name] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            "min": float(values.min()),
            "max": float(values.max()),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("bottleneck_cross_run_artifacts"))
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--threshold-objective", choices=["f1", "f2"], default="f2")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    df = load_dataset(args.dataset)
    validate_training_contract(df)
    data = df[df[TARGET].notna()].copy().reset_index(drop=True)
    data[TARGET] = data[TARGET].astype("int8")

    if data["run_id"].nunique() < args.folds + 2:
        raise ValueError("Not enough independent runs for requested outer folds plus validation.")

    args.output.mkdir(parents=True, exist_ok=True)

    outer = StratifiedGroupKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
    fold_results = []
    run_results = []
    oof_parts = []

    X_dummy = np.zeros((len(data), 1), dtype=np.int8)
    groups = data["run_id"].astype(str).to_numpy()
    y_all = data[TARGET].to_numpy(dtype=np.int8)

    for fold, (pool_idx, test_idx) in enumerate(outer.split(X_dummy, y_all, groups), 1):
        pool = data.iloc[pool_idx].copy()
        test = data.iloc[test_idx].copy()

        # Inner run-level split: threshold selection and early stopping never touch outer test runs.
        inner_splits = min(4, max(2, pool["run_id"].nunique() // 3))
        inner = StratifiedGroupKFold(
            n_splits=inner_splits,
            shuffle=True,
            random_state=args.seed + fold,
        )
        pool_groups = pool["run_id"].astype(str).to_numpy()
        pool_y = pool[TARGET].to_numpy(dtype=np.int8)
        inner_train_idx, val_idx = next(
            inner.split(np.zeros((len(pool), 1), dtype=np.int8), pool_y, pool_groups)
        )
        train = pool.iloc[inner_train_idx].copy()
        val = pool.iloc[val_idx].copy()

        train_runs = sorted(train["run_id"].astype(str).unique().tolist())
        val_runs = sorted(val["run_id"].astype(str).unique().tolist())
        test_runs = sorted(test["run_id"].astype(str).unique().tolist())

        if set(train_runs) & set(val_runs) or set(train_runs) & set(test_runs) or set(val_runs) & set(test_runs):
            raise RuntimeError("Run leakage detected between train/validation/test.")

        harmonize_types(train, val, test)
        X_train, y_train = train[BOTTLENECK_FEATURES], train[TARGET]
        X_val, y_val = val[BOTTLENECK_FEATURES], val[TARGET]
        X_test, y_test = test[BOTTLENECK_FEATURES], test[TARGET]

        model = make_model(args.seed + fold)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        val_prob = model.predict_proba(X_val)[:, 1]
        test_prob = model.predict_proba(X_test)[:, 1]
        threshold, val_score = pick_threshold(
            y_val.to_numpy(), val_prob, args.threshold_objective
        )
        test_metric = metrics(y_test.to_numpy(), test_prob, threshold)
        val_metric = metrics(y_val.to_numpy(), val_prob, threshold)

        fold_result = {
            "fold": fold,
            "train_runs": train_runs,
            "validation_runs": val_runs,
            "test_runs": test_runs,
            "test_scenarios": sorted({scenario_name(r) for r in test_runs}),
            "rows": {
                "train": int(len(train)),
                "validation": int(len(val)),
                "test": int(len(test)),
            },
            "positive_rates": {
                "train": float(y_train.mean()),
                "validation": float(y_val.mean()),
                "test": float(y_test.mean()),
            },
            "best_iteration": int(model.best_iteration),
            "selected_threshold": float(threshold),
            "validation_threshold_score": float(val_score),
            "validation_metrics": val_metric,
            "test_metrics": test_metric,
        }
        fold_results.append(fold_result)

        fold_run_metrics = per_run_metrics(test, test_prob, threshold)
        for row in fold_run_metrics:
            row["fold"] = fold
            row["scenario"] = scenario_name(row["run_id"])
            run_results.append(row)

        oof = test[[
            "run_id", "station_id_buffer_id", "prediction_time",
            "prediction_event_sequence", TARGET,
        ]].copy()
        oof["fold"] = fold
        oof["selected_threshold"] = threshold
        oof["predicted_probability"] = test_prob
        oof["predicted_bottleneck"] = (test_prob >= threshold).astype(np.int8)
        oof_parts.append(oof)

        print(
            f"Fold {fold}/{args.folds}: test_runs={test_runs} "
            f"PR-AUC={test_metric['pr_auc']:.4f} recall={test_metric['recall']:.4f} "
            f"precision={test_metric['precision']:.4f} F2={test_metric['f2']:.4f}"
        )

    fold_metric_rows = [row["test_metrics"] for row in fold_results]
    metric_names = ["pr_auc", "roc_auc", "brier", "balanced_accuracy", "precision", "recall", "f1", "f2"]
    fold_summary = aggregate(fold_metric_rows, metric_names)
    run_summary = aggregate(run_results, metric_names)

    results = {
        "dataset": str(args.dataset),
        "method": "nested run-level 5-fold cross-validation",
        "outer_rule": "complete run_id groups; every labeled row is outer-test exactly once",
        "inner_rule": "complete run_id groups for validation; threshold and early stopping use validation only",
        "threshold_objective": args.threshold_objective,
        "labeled_rows": int(len(data)),
        "run_count": int(data["run_id"].nunique()),
        "feature_count": len(BOTTLENECK_FEATURES),
        "folds": fold_results,
        "fold_test_metric_summary": fold_summary,
        "per_run_metric_summary": run_summary,
    }

    (args.output / "cross_run_metrics.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    pd.DataFrame(run_results).sort_values(["fold", "run_id"]).to_csv(
        args.output / "per_run_metrics.csv", index=False
    )
    pd.concat(oof_parts, ignore_index=True).to_parquet(
        args.output / "out_of_fold_predictions.parquet", index=False
    )

    print("\nCross-run fold summary:")
    print(json.dumps(fold_summary, indent=2))
    print(f"Saved artifacts to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
