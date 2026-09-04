from __future__ import annotations

"""Strict adapter from reconstructed Dark-Zone features to the saved XGBoost bundle.

This module never retrains, refits categories, or changes the Dark Zone engine.
It consumes the exact preprocessing contract saved by train_bottleneck_xgboost.py.
"""

from pathlib import Path
from typing import Optional
import json

import joblib
import numpy as np
import pandas as pd

from dark_zone_feature_reconstructor import FEATURES_28

try:
    from ml.model_io import load_bottleneck_model_bundle
except ImportError:
    import sys
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from ml.model_io import load_bottleneck_model_bundle


def prepare_model_features(frame: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    features = list(bundle["features"])
    categorical = list(bundle["categorical_features"])
    category_levels = bundle["category_levels"]

    if features != FEATURES_28:
        raise ValueError(
            "Saved model feature contract does not match the Dark-Zone 28-feature bridge.\n"
            f"model={features}\nbridge={FEATURES_28}"
        )
    missing = [c for c in features if c not in frame.columns]
    if missing:
        raise ValueError(f"Dark-Zone feature file is missing model columns: {missing}")

    X = frame[features].copy()
    for col in categorical:
        if col not in category_levels:
            raise ValueError(f"Saved model bundle has no category_levels entry for {col}")
        levels = list(category_levels[col])
        # Exact training/inference behavior: unseen categories become missing.
        X[col] = pd.Categorical(X[col].astype(str), categories=levels)
    for col in features:
        if col not in categorical:
            X[col] = pd.to_numeric(X[col], errors="coerce").astype("float32")
    return X


def predict_dark_zone_features(
    feature_frame: pd.DataFrame,
    model_bundle_path: str | Path,
) -> tuple[pd.DataFrame, dict]:
    bundle, model, _ = load_bottleneck_model_bundle(model_bundle_path)
    required = {"features", "categorical_features", "category_levels", "threshold"}
    missing_bundle = sorted(required - set(bundle))
    if missing_bundle:
        raise ValueError(f"Model bundle missing keys: {missing_bundle}")

    X = prepare_model_features(feature_frame, bundle)
    probability = np.asarray(model.predict_proba(X)[:, 1], dtype=float)
    threshold = float(bundle["threshold"])

    id_candidates = [
        "run_id", "station_id_buffer_id", "vehicle_id", "prediction_time",
    ]
    out = feature_frame[[c for c in id_candidates if c in feature_frame.columns]].copy()
    if "station_id_buffer_id" not in out.columns and "station_id" in feature_frame.columns:
        out["station_id_buffer_id"] = feature_frame["station_id"].astype(str)
    out["predicted_bottleneck_probability"] = probability
    out["decision_threshold"] = threshold
    out["predicted_bottleneck"] = (probability >= threshold).astype(np.int8)

    unknown_categories = {}
    for col in bundle["categorical_features"]:
        levels = set(map(str, bundle["category_levels"][col]))
        raw = feature_frame[col].astype(str)
        unknown_categories[col] = sorted(set(raw[~raw.isin(levels)].tolist()))

    audit = {
        "rows": int(len(out)),
        "feature_count": len(bundle["features"]),
        "features_match_bridge_exactly": list(bundle["features"]) == FEATURES_28,
        "categorical_features": list(bundle["categorical_features"]),
        "unknown_categories_mapped_to_missing": unknown_categories,
        "threshold": threshold,
        "threshold_objective": bundle.get("threshold_objective"),
        "probability_min": float(np.nanmin(probability)) if len(probability) else None,
        "probability_max": float(np.nanmax(probability)) if len(probability) else None,
        "positive_predictions": int((probability >= threshold).sum()),
    }
    return out, audit


def run_model_on_csv(
    feature_csv: str | Path,
    model_bundle_path: str | Path,
    output_csv: str | Path,
    audit_json: Optional[str | Path] = None,
) -> tuple[pd.DataFrame, dict]:
    frame = pd.read_csv(feature_csv)
    pred, audit = predict_dark_zone_features(frame, model_bundle_path)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    pred.to_csv(output_csv, index=False)
    if audit_json:
        Path(audit_json).write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return pred, audit
