"""Continue the protected V5 CatBoost model on one factory's causal public-bus data."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

from ..src.feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES, TARGET_COLUMN


def _json_safe(value: Any):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _prepare_X(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in DEFECT_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"Training dataset missing defect features: {missing}")
    X = df[DEFECT_FEATURES].copy()
    for c in CATEGORICAL_FEATURES:
        X[c] = X[c].fillna("MISSING").astype(str)
    for c in DEFECT_FEATURES:
        if c not in CATEGORICAL_FEATURES:
            X[c] = pd.to_numeric(X[c], errors="coerce")
    return X


def _validate_labels(df: pd.DataFrame, name: str) -> np.ndarray:
    if TARGET_COLUMN not in df.columns:
        raise ValueError(f"{name} dataset missing {TARGET_COLUMN}")
    if df[TARGET_COLUMN].isna().any():
        raise ValueError(f"{name} dataset contains censored labels")
    y = df[TARGET_COLUMN].astype(int).to_numpy()
    values = set(map(int, np.unique(y)))
    if values != {0, 1}:
        raise ValueError(
            f"{name} dataset must contain both PASS(0) and FAIL(1) units/rows; found {sorted(values)}"
        )
    return y


def _unit_threshold(validation: pd.DataFrame, score: np.ndarray, fwr_cap: float) -> dict[str, float]:
    work = validation[["run_id", "unit_id", "prediction_station_index", "final_station_index", TARGET_COLUMN]].copy()
    work["score"] = np.asarray(score, dtype=float)
    pre = work[work["prediction_station_index"] < work["final_station_index"]].copy()
    if pre.empty:
        raise ValueError("Validation set has no pre-final defect prediction rows")
    labels = pre.groupby(["run_id", "unit_id"], sort=False)[TARGET_COLUMN].max().astype(int)
    unit_scores = pre.groupby(["run_id", "unit_id"], sort=False)["score"].max()
    unit = labels.rename("y").to_frame().join(unit_scores.rename("score"), how="inner")
    if set(unit["y"].unique()) != {0, 1}:
        raise ValueError("Validation units must contain both PASS and FAIL for threshold selection")
    candidates = np.unique(unit["score"].to_numpy(dtype=float))
    candidates = np.r_[np.nextafter(float(np.max(candidates)), math.inf), candidates[::-1]]
    best = None
    n_pos = int((unit.y == 1).sum())
    n_neg = int((unit.y == 0).sum())
    for threshold in candidates:
        alert = unit["score"].to_numpy(dtype=float) >= float(threshold)
        y = unit["y"].to_numpy(dtype=int)
        tp = int(np.sum(alert & (y == 1)))
        fp = int(np.sum(alert & (y == 0)))
        recall = tp / n_pos if n_pos else 0.0
        fwr = fp / n_neg if n_neg else 0.0
        precision = tp / max(1, tp + fp)
        if fwr <= float(fwr_cap) + 1e-12:
            candidate = (recall, precision, -fwr, -float(threshold))
            if best is None or candidate > best[0]:
                best = (candidate, float(threshold), recall, fwr, precision, tp, fp)
    if best is None:
        raise RuntimeError("Could not choose a validation threshold under the false-warning cap")
    _, threshold, recall, fwr, precision, tp, fp = best
    return {
        "threshold": threshold,
        "unit_recall": float(recall),
        "unit_false_warning_rate": float(fwr),
        "unit_precision": float(precision),
        "unit_tp": int(tp),
        "unit_fp": int(fp),
        "validation_positive_units": n_pos,
        "validation_negative_units": n_neg,
    }


def train_factory_catboost(
    dataset_dir: str | Path,
    output_dir: str | Path,
    *,
    base_model_artifact: str | Path,
    base_config: str | Path,
    seed: int = 42,
    continuation_iterations: int = 100,
    false_warning_cap: float | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    train = pd.read_pickle(dataset / "train.pkl")
    validation = pd.read_pickle(dataset / "validation.pkl")
    y_train = _validate_labels(train, "train")
    y_val = _validate_labels(validation, "validation")
    X_train = _prepare_X(train)
    X_val = _prepare_X(validation)

    base_artifact = joblib.load(Path(base_model_artifact).expanduser().resolve())
    config = json.loads(Path(base_config).expanduser().resolve().read_text(encoding="utf-8"))
    if base_artifact.get("version") != "v5" or config.get("version") != "v5":
        raise ValueError("Factory continuation requires the protected finalized V5 base model")
    bundle = base_artifact.get("bundle", {})
    if bundle.get("kind") != "ensemble" or len(bundle.get("models", [])) != 1:
        raise ValueError("Factory continuation requires the finalized one-model V5 ensemble")
    base_model = bundle["models"][0]

    params = dict(config.get("catboost_params", {}))
    params.update({
        "iterations": int(continuation_iterations),
        "random_seed": int(seed),
        "verbose": False,
        "allow_writing_files": False,
    })
    # CatBoost accepts index positions for categorical columns and appends the new
    # trees to init_model without mutating the protected base model object on disk.
    cat_idx = [DEFECT_FEATURES.index(c) for c in CATEGORICAL_FEATURES]
    positive_weight = float(
        (config.get("selected_candidate_config") or {}).get("hard_positive_weight") or 1.0
    )
    sample_weight = np.where(y_train == 1, positive_weight, 1.0)
    model = CatBoostClassifier(**params)
    model.fit(
        X_train,
        y_train,
        cat_features=cat_idx,
        sample_weight=sample_weight,
        init_model=base_model,
    )

    raw_val = np.asarray(model.predict_proba(X_val)[:, 1], dtype=float)
    if not np.isfinite(raw_val).all() or ((raw_val < 0) | (raw_val > 1)).any():
        raise RuntimeError("Factory CatBoost emitted invalid validation probabilities")

    cap = float(config.get("false_warning_cap", 0.05) if false_warning_cap is None else false_warning_cap)
    threshold = _unit_threshold(validation, raw_val, cap)
    metrics = {
        "validation_rows": int(len(validation)),
        "validation_positive_rows": int(np.sum(y_val == 1)),
        "validation_pr_auc": float(average_precision_score(y_val, raw_val)),
        "validation_roc_auc": float(roc_auc_score(y_val, raw_val)),
        "validation_log_loss": float(log_loss(y_val, raw_val, labels=[0, 1])),
        "base_tree_count": int(getattr(base_model, "tree_count_", 0)),
        "factory_tree_count": int(getattr(model, "tree_count_", 0)),
        "continuation_iterations": int(continuation_iterations),
        "positive_row_weight": positive_weight,
        "selected_calibration": "none",
        "selected_alert_policy": "raw",
        "false_warning_cap": cap,
        **threshold,
    }

    artifact = {
        "version": "v5",
        "selected_candidate": "factory_continued_from_protected_v5",
        "feature_order": list(DEFECT_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "bundle": {"kind": "ensemble", "models": [model]},
    }
    joblib.dump(artifact, output / "defect_v5_models.joblib")
    joblib.dump(None, output / "defect_v5_calibrator.joblib")

    factory_config = {
        "version": "v5",
        "feature_count": len(DEFECT_FEATURES),
        "features": list(DEFECT_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "catboost_params": params,
        "selected_candidate": "factory_continued_from_protected_v5",
        "selected_candidate_config": {
            "kind": "factory_continuation",
            "base": "protected_v5",
            "continuation_iterations": int(continuation_iterations),
            "positive_row_weight": positive_weight,
        },
        "number_of_models": 1,
        "selected_calibration": "none",
        "calibration_applies_to_probability_reporting": False,
        "alert_score_space": "raw_probability",
        "selected_alert_policy": "raw",
        "selected_alert_score_column": "score",
        "selected_alert_threshold": float(threshold["threshold"]),
        "false_warning_cap": cap,
        "random_seed": int(seed),
        "training_source": "deployment_public_bus_replay",
        "inspection_role": "label_only",
    }
    (output / "defect_v5_config.json").write_text(
        json.dumps(_json_safe(factory_config), indent=2) + "\n", encoding="utf-8"
    )
    (output / "metrics.json").write_text(
        json.dumps(_json_safe(metrics), indent=2) + "\n", encoding="utf-8"
    )
    return metrics
