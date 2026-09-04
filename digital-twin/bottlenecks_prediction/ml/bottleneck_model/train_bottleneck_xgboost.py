"""Train the causal bottleneck-prediction model from bottleneck_causal_features.parquet.

Target semantics from the pre-ML builder:
    y_bottleneck = 1 if the station queue reaches configured capacity within the
    next 30 minutes, provided the row is not already full and the future horizon
    is complete.

Key rules enforced here:
- Train only on labeled / eligible rows.
- Use only the frozen 28 bottleneck X features.
- Split by complete simulation run_id, never random event rows.
- Choose the operational decision threshold on validation data only.
- Keep test runs untouched until final evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    fbeta_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier


BOTTLENECK_FEATURES = [
    "capacity_headroom", "station_id", "base_cycle_time_ms", "station_archetype",
    "configured_cycle_std_ms", "station_index", "buffer_capacity", "line_fraction",
    "queue_max_10m", "queue_mean_10m", "current_occupancy", "queue_std_10m",
    "capacity_utilization", "arrival_rate_per_min_prev10m", "service_rate_per_min_prev10m",
    "service_rate_per_min_10m", "arrival_rate_per_min_10m", "utilization_headroom",
    "cycle_max_10m", "flow_pressure_10m", "queue_delta_10m", "cycle_mean_10m",
    "queue_slope_10m", "net_flow_rate_10m", "cycle_std_10m",
    "state_confidence", "progress_std", "eta_std",
]

CATEGORICAL_FEATURES = ["station_id", "station_archetype"]
TARGET = "y_bottleneck"

# Scenario-balanced split for the 19 runs in the supplied training archive.
# These are complete run holdouts, not row-wise samples.
DEFAULT_TEST_RUNS = {
    "train_184_gradual",
    "train_187_accelerating",
    "train_190_step",
    "train_193_intermittent",
    "train_195_severe",
}
DEFAULT_VAL_RUNS = {
    "train_183_gradual",
    "train_186_accelerating",
    "train_189_step",
    "train_192_intermittent",
}


def load_dataset(path: Path) -> pd.DataFrame:
    if path.is_dir():
        parquet = path / "bottleneck_causal_features.parquet"
        csv = path / "bottleneck_causal_features.csv"
        if parquet.exists():
            path = parquet
        elif csv.exists():
            path = csv
        else:
            raise FileNotFoundError(
                f"Could not find bottleneck_causal_features.parquet or .csv inside {path}"
            )

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported dataset format: {path}")


def validate_training_contract(df: pd.DataFrame) -> None:
    required = set(BOTTLENECK_FEATURES) | {
        "run_id", TARGET, "target_eligibility_status", "currently_at_capacity"
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    frozen_projection = [c for c in df.columns if c in BOTTLENECK_FEATURES]
    if frozen_projection != BOTTLENECK_FEATURES:
        raise ValueError(
            "Frozen bottleneck feature columns are missing or reordered. "
            "Rebuild the causal dataset before training."
        )

    labeled = df[TARGET].notna()
    bad_labeled = labeled & df["target_eligibility_status"].ne("eligible")
    if bad_labeled.any():
        raise ValueError(
            f"Found {int(bad_labeled.sum())} labeled rows that are not target-eligible."
        )

    already_full_labeled = labeled & df["currently_at_capacity"].astype(bool)
    if already_full_labeled.any():
        raise ValueError(
            f"Found {int(already_full_labeled.sum())} already-full rows with labels."
        )


def choose_run_split(df: pd.DataFrame, seed: int = 42):
    runs = sorted(df["run_id"].dropna().astype(str).unique())
    run_set = set(runs)

    if DEFAULT_TEST_RUNS.issubset(run_set) and DEFAULT_VAL_RUNS.issubset(run_set):
        test_runs = sorted(DEFAULT_TEST_RUNS)
        val_runs = sorted(DEFAULT_VAL_RUNS)
        train_runs = sorted(run_set - DEFAULT_TEST_RUNS - DEFAULT_VAL_RUNS)
        split_kind = "scenario-balanced fixed run split"
    else:
        # Generic fallback for future datasets: deterministic split at run level.
        rng = np.random.default_rng(seed)
        shuffled = np.array(runs, dtype=object)
        rng.shuffle(shuffled)
        n = len(shuffled)
        if n < 5:
            raise ValueError("Need at least 5 independent runs for train/validation/test splitting.")
        n_test = max(1, round(0.20 * n))
        n_val = max(1, round(0.20 * n))
        test_runs = sorted(shuffled[:n_test].tolist())
        val_runs = sorted(shuffled[n_test:n_test + n_val].tolist())
        train_runs = sorted(shuffled[n_test + n_val:].tolist())
        split_kind = "deterministic run-level fallback split"

    return train_runs, val_runs, test_runs, split_kind


def harmonize_types(
    train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame,
    fixed_category_levels: dict[str, list[str]] | None = None,
):
    category_levels = {}
    for col in CATEGORICAL_FEATURES:
        observed = sorted(train[col].dropna().astype(str).unique().tolist())
        levels = list(fixed_category_levels[col]) if fixed_category_levels else observed
        unknown = sorted(set(observed) - set(levels))
        if unknown:
            raise ValueError(
                f"Factory continuation training contains {col} categories absent from the "
                f"protected base model: {unknown}. A new base model is required."
            )
        category_levels[col] = levels
        for frame in (train, val, test):
            # Unseen categories in validation/test become missing; XGBoost handles missing values.
            frame[col] = pd.Categorical(frame[col].astype(str), categories=levels)

    for frame in (train, val, test):
        for col in BOTTLENECK_FEATURES:
            if col not in CATEGORICAL_FEATURES:
                frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float32")
        frame[TARGET] = frame[TARGET].astype("int8")

    return category_levels


def pick_threshold(y_true: np.ndarray, y_prob: np.ndarray, objective: str):
    precision, recall, thresholds = precision_recall_curve(y_true, y_prob)
    precision = precision[:-1]
    recall = recall[:-1]

    if objective == "f1":
        score = 2 * precision * recall / (precision + recall + 1e-15)
    elif objective == "f2":
        score = 5 * precision * recall / (4 * precision + recall + 1e-15)
    else:
        raise ValueError(objective)

    idx = int(np.nanargmax(score))
    return float(thresholds[idx]), float(score[idx])


def metrics(y_true, y_prob, threshold: float):
    y_pred = (y_prob >= threshold).astype(np.int8)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    return {
        "threshold": float(threshold),
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "f2": float(fbeta_score(y_true, y_pred, beta=2, zero_division=0)),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def per_run_metrics(frame: pd.DataFrame, probabilities: np.ndarray, threshold: float):
    tmp = frame[["run_id", TARGET]].copy()
    tmp["probability"] = probabilities
    rows = []
    for run_id, g in tmp.groupby("run_id", sort=True):
        y = g[TARGET].to_numpy(dtype=np.int8)
        p = g["probability"].to_numpy(dtype=float)
        row = {"run_id": str(run_id), "rows": int(len(g)), "positive_rate": float(y.mean())}
        row.update(metrics(y, p, threshold))
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to bottleneck_causal_features.parquet, CSV, or its containing directory.",
    )
    parser.add_argument("--output", type=Path, default=Path("bottleneck_model_artifacts"))
    parser.add_argument(
        "--threshold-objective",
        choices=["f1", "f2"],
        default="f2",
        help="F2 favors recall; F1 is more balanced. Threshold is selected on validation only.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--base-model",
        type=Path,
        default=None,
        help=(
            "Optional immutable XGBoost JSON model used as the initial training state. "
            "This is deliberately explicit: training never starts from a selected "
            "factory artifact."
        ),
    )
    args = parser.parse_args()

    if args.base_model is not None:
        args.base_model = args.base_model.expanduser().resolve()
        if not args.base_model.is_file():
            raise FileNotFoundError(f"Base XGBoost model not found: {args.base_model}")

    df = load_dataset(args.dataset)
    validate_training_contract(df)

    total_rows = len(df)
    # This is the only target filtering allowed. Censored/already-full rows are not negatives.
    data = df[df[TARGET].notna()].copy()
    if data.empty:
        raise ValueError("No labeled bottleneck rows found.")

    train_runs, val_runs, test_runs, split_kind = choose_run_split(data, args.seed)
    train = data[data.run_id.isin(train_runs)].copy()
    val = data[data.run_id.isin(val_runs)].copy()
    test = data[data.run_id.isin(test_runs)].copy()

    fixed_category_levels = None
    if args.base_model is not None:
        base_bundle = args.base_model.parent / "bottleneck_model_bundle.joblib"
        if not base_bundle.is_file():
            raise FileNotFoundError(
                f"Base category-contract bundle not found beside base model: {base_bundle}"
            )
        base_meta = joblib.load(base_bundle)
        fixed_category_levels = {
            str(k): list(v) for k, v in base_meta["category_levels"].items()
        }
    category_levels = harmonize_types(train, val, test, fixed_category_levels)

    X_train, y_train = train[BOTTLENECK_FEATURES], train[TARGET]
    X_val, y_val = val[BOTTLENECK_FEATURES], val[TARGET]
    X_test, y_test = test[BOTTLENECK_FEATURES], test[TARGET]

    model = XGBClassifier(
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
        random_state=args.seed,
        n_jobs=-1,
        early_stopping_rounds=80,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
        xgb_model=str(args.base_model) if args.base_model is not None else None,
    )

    val_prob = model.predict_proba(X_val)[:, 1]
    test_prob = model.predict_proba(X_test)[:, 1]
    threshold, validation_threshold_score = pick_threshold(
        y_val.to_numpy(), val_prob, args.threshold_objective
    )

    args.output.mkdir(parents=True, exist_ok=True)

    results = {
        "dataset": str(args.dataset),
        "total_materialized_rows": int(total_rows),
        "labeled_eligible_rows": int(len(data)),
        "positive_rows": int(data[TARGET].sum()),
        "positive_rate": float(data[TARGET].mean()),
        "feature_count": len(BOTTLENECK_FEATURES),
        "features": BOTTLENECK_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "category_contract_source": (
            "protected_base_model" if args.base_model is not None else "training_split"
        ),
        "split_kind": split_kind,
        "train_runs": train_runs,
        "validation_runs": val_runs,
        "test_runs": test_runs,
        "split_rows": {
            "train": int(len(train)), "validation": int(len(val)), "test": int(len(test))
        },
        "split_positive_rates": {
            "train": float(y_train.mean()),
            "validation": float(y_val.mean()),
            "test": float(y_test.mean()),
        },
        "best_iteration": int(model.best_iteration),
        "threshold_objective": args.threshold_objective,
        "base_model": str(args.base_model) if args.base_model is not None else None,
        "selected_threshold": float(threshold),
        "validation_threshold_score": float(validation_threshold_score),
        "validation_metrics_selected_threshold": metrics(y_val, val_prob, threshold),
        "test_metrics_selected_threshold": metrics(y_test, test_prob, threshold),
        "test_metrics_threshold_0_5": metrics(y_test, test_prob, 0.5),
        "per_test_run": per_run_metrics(test, test_prob, threshold),
    }

    # Save model in both XGBoost-native and Python-bundle formats.
    model.save_model(args.output / "bottleneck_xgboost.json")
    joblib.dump(
        {
            "xgboost_model": "bottleneck_xgboost.json",
            "features": BOTTLENECK_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
            "category_levels": category_levels,
            "threshold": threshold,
            "threshold_objective": args.threshold_objective,
            "base_model": str(args.base_model) if args.base_model is not None else None,
        },
        args.output / "bottleneck_model_bundle.joblib",
    )

    gain = model.get_booster().get_score(importance_type="gain")
    importance = pd.DataFrame(
        {"feature": BOTTLENECK_FEATURES, "gain": [float(gain.get(f, 0.0)) for f in BOTTLENECK_FEATURES]}
    ).sort_values("gain", ascending=False)
    importance.to_csv(args.output / "feature_importance_gain.csv", index=False)

    predictions = test[[
        "run_id", "station_id_buffer_id", "prediction_time", "prediction_event_sequence", TARGET
    ]].copy()
    predictions["predicted_probability"] = test_prob
    predictions["predicted_bottleneck"] = (test_prob >= threshold).astype(np.int8)
    predictions.to_csv(args.output / "test_predictions.csv", index=False)

    (args.output / "metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(results["test_metrics_selected_threshold"], indent=2))
    print(f"Saved model artifacts to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
