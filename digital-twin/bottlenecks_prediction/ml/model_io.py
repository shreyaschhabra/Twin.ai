"""Stable loading for bottleneck model metadata + native XGBoost JSON.

New artifacts keep the sklearn/XGBoost estimator out of joblib.  Joblib stores
only the preprocessing/threshold contract and names the sibling native model.
Legacy bundles containing a pickled estimator remain readable as a fallback.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import warnings

import joblib
import xgboost as xgb


def load_bottleneck_model_bundle(
    model_bundle_path: str | Path,
) -> tuple[dict[str, Any], xgb.XGBClassifier, Path | None]:
    path = Path(model_bundle_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Model bundle not found: {path}")

    bundle = joblib.load(path)
    native_name = str(bundle.get("xgboost_model", "bottleneck_xgboost.json"))
    native = Path(native_name)
    if not native.is_absolute():
        native = path.parent / native

    if native.is_file():
        model = xgb.XGBClassifier()
        model.load_model(native)
        return bundle, model, native.resolve()

    legacy = bundle.get("model")
    if legacy is not None:
        warnings.warn(
            "Native bottleneck_xgboost.json is missing; using a legacy pickled "
            "XGBoost estimator. Re-export the artifact before deployment.",
            RuntimeWarning,
        )
        return bundle, legacy, None

    raise FileNotFoundError(
        f"Native XGBoost model not found: {native}; bundle contains no legacy estimator"
    )
