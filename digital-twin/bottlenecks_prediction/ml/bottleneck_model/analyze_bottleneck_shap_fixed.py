"""Generate global and local SHAP explanations for the trained bottleneck XGBoost model.

Uses XGBoost's native exact tree SHAP contributions (`pred_contribs=True`), so no
separate `shap` package is required. Contributions are in model-margin/log-odds space.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb

try:
    from .train_bottleneck_xgboost import TARGET, load_dataset
    from ..model_io import load_bottleneck_model_bundle
except ImportError:  # Direct script execution
    import sys
    package_root = Path(__file__).resolve().parents[2]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from train_bottleneck_xgboost import TARGET, load_dataset
    from ml.model_io import load_bottleneck_model_bundle


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def prepare_features(frame: pd.DataFrame, features, categorical_features, category_levels):
    X = frame[features].copy()
    for col in categorical_features:
        levels = category_levels[col]
        X[col] = pd.Categorical(X[col].astype(str), categories=levels)
    for col in features:
        if col not in categorical_features:
            X[col] = pd.to_numeric(X[col], errors="coerce").astype("float32")
    return X


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--model-dir", type=Path, default=Path("bottleneck_model_artifacts"))
    p.add_argument("--output", type=Path, default=Path("bottleneck_shap_artifacts"))
    p.add_argument("--sample-size", type=int, default=20000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--local-per-class", type=int, default=5)
    args = p.parse_args()

    bundle, model, _ = load_bottleneck_model_bundle(
        args.model_dir / "bottleneck_model_bundle.joblib"
    )
    features = list(bundle["features"])
    categorical = list(bundle["categorical_features"])
    category_levels = bundle["category_levels"]
    threshold = float(bundle["threshold"])

    df = load_dataset(args.dataset)
    data = df[df[TARGET].notna()].copy()

    metrics_path = args.model_dir / "metrics.json"
    if metrics_path.exists():
        metrics_json = json.loads(metrics_path.read_text(encoding="utf-8"))
        test_runs = metrics_json.get("test_runs", [])
        explain = data[data["run_id"].isin(test_runs)].copy() if test_runs else data.copy()
        scope = "held-out test runs from final model"
    else:
        explain = data.copy()
        test_runs = []
        scope = "all labeled rows (metrics.json not found)"

    if explain.empty:
        raise ValueError("No rows available for SHAP analysis.")

    sample_n = min(args.sample_size, len(explain))
    sample = explain.sample(n=sample_n, random_state=args.seed).copy().reset_index(drop=True)
    X = prepare_features(sample, features, categorical, category_levels)

    booster = model.get_booster()
    dmat = xgb.DMatrix(X, enable_categorical=True)

    # IMPORTANT: XGBClassifier.predict_proba() automatically uses only trees through
    # best_iteration after early stopping. The raw Booster, however, uses every stored
    # tree unless iteration_range is supplied. SHAP must explain the exact same tree
    # ensemble that is used for deployment predictions.
    best_iteration = getattr(model, "best_iteration", None)
    iteration_range = (0, int(best_iteration) + 1) if best_iteration is not None else (0, 0)

    contrib = booster.predict(
        dmat, pred_contribs=True, iteration_range=iteration_range
    )
    if contrib.shape[1] != len(features) + 1:
        raise RuntimeError(f"Unexpected SHAP contribution shape {contrib.shape}")

    shap_values = contrib[:, :-1]
    base_values = contrib[:, -1]
    reconstructed_margin = base_values + shap_values.sum(axis=1)

    # Use the same Booster + iteration range for the reference prediction so the
    # additivity audit is exact. For binary logistic, sigmoid(margin) = probability.
    model_margin = booster.predict(
        dmat, output_margin=True, iteration_range=iteration_range
    )
    model_probability = booster.predict(
        dmat, iteration_range=iteration_range
    )
    reconstructed_probability = sigmoid(reconstructed_margin)

    max_margin_additivity_error = float(
        np.max(np.abs(reconstructed_margin - model_margin))
    )
    max_probability_additivity_error = float(
        np.max(np.abs(reconstructed_probability - model_probability))
    )

    args.output.mkdir(parents=True, exist_ok=True)

    global_importance = pd.DataFrame({
        "feature": features,
        "mean_abs_shap": np.mean(np.abs(shap_values), axis=0),
        "mean_shap": np.mean(shap_values, axis=0),
    }).sort_values("mean_abs_shap", ascending=False)
    global_importance.to_csv(args.output / "shap_global_importance.csv", index=False)

    # Save sampled SHAP values in a compact wide parquet for later plots/diagnostics.
    shap_frame = sample[[
        "run_id", "station_id_buffer_id", "prediction_time",
        "prediction_event_sequence", TARGET,
    ]].copy()
    shap_frame["predicted_probability"] = model_probability
    shap_frame["predicted_bottleneck"] = (model_probability >= threshold).astype(np.int8)
    shap_frame["shap_base_margin"] = base_values
    for j, feature in enumerate(features):
        shap_frame[f"shap__{feature}"] = shap_values[:, j]
    shap_frame.to_parquet(args.output / "shap_sample_values.parquet", index=False)

    # Global mean-|SHAP| bar chart.
    top = global_importance.head(20).iloc[::-1]
    plt.figure(figsize=(10, 8))
    plt.barh(top["feature"], top["mean_abs_shap"])
    plt.xlabel("Mean |SHAP value| (log-odds contribution)")
    plt.ylabel("Feature")
    plt.title("Bottleneck model — global SHAP importance")
    plt.tight_layout()
    plt.savefig(args.output / "shap_global_importance.png", dpi=180)
    plt.close()

    # Local explanations: pick representative TP / FP / FN / TN cases.
    y = sample[TARGET].astype(int).to_numpy()
    pred = (model_probability >= threshold).astype(int)
    class_masks = {
        "TP": (y == 1) & (pred == 1),
        "FP": (y == 0) & (pred == 1),
        "FN": (y == 1) & (pred == 0),
        "TN": (y == 0) & (pred == 0),
    }
    local_rows = []
    for label, mask in class_masks.items():
        idx = np.where(mask)[0]
        if len(idx) == 0:
            continue
        # For predicted positives choose highest-risk; for negatives choose closest to threshold.
        if label in {"TP", "FP"}:
            chosen = idx[np.argsort(model_probability[idx])[-args.local_per_class:]][::-1]
        else:
            chosen = idx[np.argsort(np.abs(model_probability[idx] - threshold))[:args.local_per_class]]
        for i in chosen:
            order = np.argsort(np.abs(shap_values[i]))[::-1][:8]
            for rank, j in enumerate(order, 1):
                local_rows.append({
                    "case_type": label,
                    "run_id": sample.loc[i, "run_id"],
                    "station_id_buffer_id": sample.loc[i, "station_id_buffer_id"],
                    "prediction_time": int(sample.loc[i, "prediction_time"]),
                    "y_bottleneck": int(y[i]),
                    "predicted_probability": float(model_probability[i]),
                    "threshold": threshold,
                    "rank": rank,
                    "feature": features[j],
                    "feature_value": str(sample.loc[i, features[j]]),
                    "shap_value": float(shap_values[i, j]),
                    "direction": "raises risk" if shap_values[i, j] > 0 else "lowers risk",
                })
    pd.DataFrame(local_rows).to_csv(args.output / "shap_local_top_drivers.csv", index=False)

    summary = {
        "dataset": str(args.dataset),
        "model_dir": str(args.model_dir),
        "scope": scope,
        "test_runs": test_runs,
        "sample_rows": int(sample_n),
        "threshold": threshold,
        "shap_method": "XGBoost exact TreeSHAP via pred_contribs=True",
        "shap_units": "model margin / log-odds contribution",
        "best_iteration_explained": int(best_iteration) if best_iteration is not None else None,
        "trees_used_for_explanation": int(best_iteration) + 1 if best_iteration is not None else "all",
        "max_margin_additivity_error": max_margin_additivity_error,
        "max_probability_additivity_error": max_probability_additivity_error,
        "top_10_global_features": global_importance.head(10).to_dict(orient="records"),
    }
    (args.output / "shap_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Saved SHAP artifacts to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
