"""Calibrate probabilities for the already-trained bottleneck XGBoost model.

Important rules:
- The XGBoost model is NOT retrained.
- Calibration is fit only from the model's existing validation runs.
- Test runs are never used to fit the calibrator or select the alert threshold.
- Raw, Platt (logistic), and isotonic calibration are compared.
- Calibration-method selection uses run-wise out-of-fold predictions within validation.
- The selected calibrator is then refit on all validation rows.
- The operational F2 threshold is re-selected on calibrated validation probabilities.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    fbeta_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


try:
    from ..model_io import load_bottleneck_model_bundle
except ImportError:  # Direct script execution
    import sys
    package_root = Path(__file__).resolve().parents[2]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from ml.model_io import load_bottleneck_model_bundle

TARGET = "y_bottleneck"
EPS = 1e-7


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

    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported dataset format: {path}")


def prepare_frame(frame: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    frame = frame.copy()
    features = bundle["features"]
    categorical = bundle["categorical_features"]
    levels = bundle["category_levels"]

    for col in categorical:
        frame[col] = pd.Categorical(
            frame[col].astype(str),
            categories=levels[col],
        )

    for col in features:
        if col not in categorical:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float32")

    frame[TARGET] = frame[TARGET].astype("int8")
    return frame


def clipped_logit(prob: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(prob, dtype=float), EPS, 1.0 - EPS)
    return np.log(p / (1.0 - p))


def fit_platt(prob: np.ndarray, y: np.ndarray):
    # Platt scaling: sigmoid(a * raw_logit + b).
    x = clipped_logit(prob).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    model.fit(x, y)
    return model


def apply_platt(model, prob: np.ndarray) -> np.ndarray:
    return model.predict_proba(clipped_logit(prob).reshape(-1, 1))[:, 1]


def fit_isotonic(prob: np.ndarray, y: np.ndarray):
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(prob, y)
    return model


def apply_isotonic(model, prob: np.ndarray) -> np.ndarray:
    return np.asarray(model.predict(prob), dtype=float)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 15) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    ece = 0.0

    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        if i == bins - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        ece += (n / total) * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(ece)


def probability_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)
    return {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece_15": expected_calibration_error(y, p, bins=15),
        "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
    }


def choose_threshold(y_true: np.ndarray, y_prob: np.ndarray, objective: str = "f2"):
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


def classification_metrics(y_true: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    pred = (p >= threshold).astype(np.int8)
    tn, fp, fn, tp = confusion_matrix(y_true, pred).ravel()
    return {
        "threshold": float(threshold),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "f2": float(fbeta_score(y_true, pred, beta=2, zero_division=0)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def reliability_table(y: np.ndarray, p: np.ndarray, method: str, bins: int = 15) -> pd.DataFrame:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []

    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        if i == bins - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append(
            {
                "method": method,
                "bin": i + 1,
                "lower": lo,
                "upper": hi,
                "rows": n,
                "mean_predicted_probability": float(p[mask].mean()),
                "observed_positive_rate": float(y[mask].mean()),
                "absolute_gap": abs(float(p[mask].mean()) - float(y[mask].mean())),
            }
        )
    return pd.DataFrame(rows)


def fit_method(method: str, p: np.ndarray, y: np.ndarray):
    if method == "raw":
        return None
    if method == "platt":
        return fit_platt(p, y)
    if method == "isotonic":
        return fit_isotonic(p, y)
    raise ValueError(method)


def apply_method(method: str, calibrator, p: np.ndarray) -> np.ndarray:
    if method == "raw":
        return np.asarray(p, dtype=float)
    if method == "platt":
        return apply_platt(calibrator, p)
    if method == "isotonic":
        return apply_isotonic(calibrator, p)
    raise ValueError(method)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("bottleneck_model_artifacts"))
    parser.add_argument("--output", type=Path, default=Path("bottleneck_calibration_artifacts"))
    parser.add_argument("--threshold-objective", choices=["f1", "f2"], default="f2")
    parser.add_argument("--bins", type=int, default=15)
    args = parser.parse_args()

    model_bundle_path = args.model_dir / "bottleneck_model_bundle.joblib"
    metrics_path = args.model_dir / "metrics.json"
    if not model_bundle_path.exists():
        raise FileNotFoundError(model_bundle_path)
    if not metrics_path.exists():
        raise FileNotFoundError(metrics_path)

    bundle, model, _ = load_bottleneck_model_bundle(model_bundle_path)
    training_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    val_runs = list(training_metrics["validation_runs"])
    test_runs = list(training_metrics["test_runs"])

    df = load_dataset(args.dataset)
    df = df[df[TARGET].notna()].copy()

    val = df[df["run_id"].isin(val_runs)].copy()
    test = df[df["run_id"].isin(test_runs)].copy()
    if val.empty or test.empty:
        raise ValueError("Validation or test rows could not be reconstructed from metrics.json.")

    val = prepare_frame(val, bundle)
    test = prepare_frame(test, bundle)

    features = bundle["features"]

    y_val = val[TARGET].to_numpy(dtype=np.int8)
    y_test = test[TARGET].to_numpy(dtype=np.int8)
    raw_val = model.predict_proba(val[features])[:, 1]
    raw_test = model.predict_proba(test[features])[:, 1]

    # ------------------------------------------------------------------
    # Compare calibration methods using run-wise OOF calibration inside
    # the existing validation set. Each validation run is calibrated by
    # a calibrator fitted only on the other validation runs.
    # ------------------------------------------------------------------
    methods = ["raw", "platt", "isotonic"]
    oof_predictions = {m: np.full(len(val), np.nan, dtype=float) for m in methods}
    val_run_array = val["run_id"].astype(str).to_numpy()

    oof_predictions["raw"] = raw_val.copy()

    for held_out_run in sorted(set(val_run_array)):
        hold = val_run_array == held_out_run
        fit = ~hold

        for method in ("platt", "isotonic"):
            calibrator = fit_method(method, raw_val[fit], y_val[fit])
            oof_predictions[method][hold] = apply_method(
                method, calibrator, raw_val[hold]
            )

    oof_metrics = {
        method: probability_metrics(y_val, oof_predictions[method])
        for method in methods
    }

    # Primary selection criterion: run-wise OOF validation Brier score.
    # Ties are broken by log-loss then ECE.
    selected_method = min(
        methods,
        key=lambda m: (
            oof_metrics[m]["brier"],
            oof_metrics[m]["log_loss"],
            oof_metrics[m]["ece_15"],
        ),
    )

    # Refit selected calibrator on ALL validation rows.
    final_calibrator = fit_method(selected_method, raw_val, y_val)
    calibrated_val = apply_method(selected_method, final_calibrator, raw_val)
    calibrated_test = apply_method(selected_method, final_calibrator, raw_test)

    # Calibration changes probability scale, so choose a fresh operating
    # threshold using calibrated validation probabilities only.
    threshold, threshold_score = choose_threshold(
        y_val, calibrated_val, args.threshold_objective
    )

    raw_test_prob_metrics = probability_metrics(y_test, raw_test)
    calibrated_test_prob_metrics = probability_metrics(y_test, calibrated_test)

    raw_threshold = float(bundle["threshold"])
    raw_test_classification = classification_metrics(y_test, raw_test, raw_threshold)
    calibrated_test_classification = classification_metrics(
        y_test, calibrated_test, threshold
    )

    args.output.mkdir(parents=True, exist_ok=True)

    # Save deployable calibration bundle separately from the frozen XGBoost model.
    joblib.dump(
        {
            "method": selected_method,
            "calibrator": final_calibrator,
            "threshold": threshold,
            "threshold_objective": args.threshold_objective,
            "source_model_dir": str(args.model_dir),
            "features": features,
            "categorical_features": bundle["categorical_features"],
            "category_levels": bundle["category_levels"],
        },
        args.output / "bottleneck_calibration_bundle.joblib",
    )

    result = {
        "dataset": str(args.dataset),
        "model_dir": str(args.model_dir),
        "xgboost_retrained": False,
        "validation_runs_used_for_calibration": val_runs,
        "test_runs_evaluation_only": test_runs,
        "validation_rows": int(len(val)),
        "test_rows": int(len(test)),
        "method_selection": "run-wise out-of-fold calibration within validation runs",
        "selection_metric": "minimum OOF validation Brier score; log-loss and ECE as tie-breakers",
        "oof_validation_calibration_metrics": oof_metrics,
        "selected_method": selected_method,
        "original_threshold": raw_threshold,
        "calibrated_threshold": float(threshold),
        "threshold_objective": args.threshold_objective,
        "validation_threshold_score": float(threshold_score),
        "test_uncalibrated_probability_metrics": raw_test_prob_metrics,
        "test_calibrated_probability_metrics": calibrated_test_prob_metrics,
        "test_uncalibrated_classification_at_original_threshold": raw_test_classification,
        "test_calibrated_classification_at_calibrated_threshold": calibrated_test_classification,
    }

    (args.output / "calibration_metrics.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )

    preds = test[
        ["run_id", "station_id_buffer_id", "prediction_time",
         "prediction_event_sequence", TARGET]
    ].copy()
    preds["raw_probability"] = raw_test
    preds["calibrated_probability"] = calibrated_test
    preds["raw_prediction"] = (raw_test >= raw_threshold).astype(np.int8)
    preds["calibrated_prediction"] = (calibrated_test >= threshold).astype(np.int8)
    preds.to_parquet(args.output / "calibrated_test_predictions.parquet", index=False)

    reliability = pd.concat(
        [
            reliability_table(y_test, raw_test, "raw", bins=args.bins),
            reliability_table(y_test, calibrated_test, selected_method, bins=args.bins),
        ],
        ignore_index=True,
    )
    reliability.to_csv(args.output / "reliability_bins_test.csv", index=False)

    # Optional reliability diagram.
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 6))
        ax.plot([0, 1], [0, 1], linestyle="--", label="Perfect calibration")

        for method_name, group in reliability.groupby("method", sort=False):
            ax.plot(
                group["mean_predicted_probability"],
                group["observed_positive_rate"],
                marker="o",
                label=method_name,
            )

        ax.set_xlabel("Predicted bottleneck probability")
        ax.set_ylabel("Observed bottleneck rate")
        ax.set_title("Bottleneck probability calibration — held-out test runs")
        ax.legend()
        fig.tight_layout()
        fig.savefig(args.output / "reliability_diagram_test.png", dpi=180)
        plt.close(fig)
    except Exception as exc:
        result["reliability_plot_warning"] = str(exc)
        (args.output / "calibration_metrics.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps({
        "selected_method": selected_method,
        "oof_validation": oof_metrics,
        "test_raw": raw_test_prob_metrics,
        "test_calibrated": calibrated_test_prob_metrics,
        "original_threshold": raw_threshold,
        "calibrated_threshold": threshold,
        "test_classification_calibrated": calibrated_test_classification,
    }, indent=2))
    print(f"Saved calibration artifacts to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
