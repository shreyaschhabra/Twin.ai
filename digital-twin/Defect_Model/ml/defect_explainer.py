"""Native CatBoost SHAP explanations for the frozen V5 defect model.

This is a post-prediction explanation layer only.
It does not retrain, recalibrate, alter features, or change the alert threshold.

SHAP values are returned in CatBoost raw-score / log-odds space.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import math

import numpy as np
import pandas as pd
from catboost import Pool


FEATURE_LABELS = {
    "torque_delta_recent_vs_history": "Recent vs historical torque shift",
    "manual_fail_count_cum": "Previous manual failures",
    "prediction_station_index": "Current station position",
    "torque_mean_history": "Historical mean torque",
    "line_fraction": "Production-line progress",
    "last_manual_fail": "Most recent manual check failed",
    "manual_check_count_cum": "Previous manual checks",
    "torque_mean_recent": "Recent mean torque",
    "queue_history_mean": "Historical mean queue length",
    "current_mean_recent": "Recent mean current",
    "current_missing_recent": "Recent current reading missing",
    "vibration_delta_recent_vs_history": "Recent vs historical vibration shift",
    "current_mean_history": "Historical mean current",
    "torque_max_recent": "Recent maximum torque",
    "temperature_mean_history": "Historical mean temperature",
    "torque_max_history": "Historical maximum torque",
    "supplier_batch": "Supplier batch",
    "current_max_history": "Historical maximum current",
    "cycle_history_max": "Historical maximum cycle time",
    "temperature_max_recent": "Recent maximum temperature",
    "vibration_mean_history": "Historical mean vibration",
    "temperature_max_history": "Historical maximum temperature",
    "stations_since_last_manual_fail": "Stations since previous manual failure",
    "vehicle_model": "Vehicle model",
    "vibration_max_history": "Historical maximum vibration",
    "vibration_max_recent": "Recent maximum vibration",
    "temperature_mean_recent": "Recent mean temperature",
    "torque_std_history": "Historical torque variability",
    "queue_history_std": "Historical queue variability",
    "cycle_history_std": "Historical cycle-time variability",
}


def _safe_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if value is not None and not isinstance(value, (str, bytes)) and pd.isna(value):
            return None
    except Exception:
        pass
    return value


@dataclass
class ShapExplanation:
    method: str
    base_value_raw: float
    raw_score: float
    reconstructed_raw_score: float
    reconstructed_probability: float
    probability_reconstruction_error: float
    top_risk_drivers: list[dict[str, Any]]
    top_protective_drivers: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "shap_value_space": "raw_log_odds",
            "base_value_raw": self.base_value_raw,
            "raw_score": self.raw_score,
            "reconstructed_raw_score": self.reconstructed_raw_score,
            "reconstructed_probability": self.reconstructed_probability,
            "probability_reconstruction_error": self.probability_reconstruction_error,
            "top_risk_drivers": self.top_risk_drivers,
            "top_protective_drivers": self.top_protective_drivers,
        }


class DefectShapExplainer:
    """Explain the exact single CatBoost model selected by finalized V5."""

    def __init__(self, *, model: Any, feature_names: list[str], categorical_features: list[str]):
        self.model = model
        self.feature_names = list(feature_names)
        self.categorical_features = list(categorical_features)
        self.cat_indices = [
            self.feature_names.index(name) for name in self.categorical_features
        ]

    def explain_prepared_row(
        self,
        X_one: pd.DataFrame,
        original_values: Mapping[str, Any],
        *,
        top_k: int = 3,
        expected_probability: float | None = None,
    ) -> ShapExplanation:
        if len(X_one) != 1:
            raise ValueError("Runtime SHAP explanation expects exactly one feature row")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")

        pool = Pool(X_one, cat_features=self.cat_indices)

        contrib = np.asarray(
            self.model.get_feature_importance(pool, type="ShapValues"),
            dtype=float,
        )
        if contrib.shape != (1, len(self.feature_names) + 1):
            raise RuntimeError(
                f"Unexpected SHAP matrix shape: {contrib.shape}; "
                f"expected (1, {len(self.feature_names) + 1})"
            )

        shap_values = contrib[0, :-1]
        base = float(contrib[0, -1])
        reconstructed_raw = float(base + shap_values.sum())

        raw_score = float(
            np.asarray(
                self.model.predict(pool, prediction_type="RawFormulaVal"),
                dtype=float,
            ).reshape(-1)[0]
        )
        reconstructed_probability = float(
            1.0 / (1.0 + np.exp(-reconstructed_raw))
        )

        if expected_probability is None:
            expected_probability = float(
                np.asarray(self.model.predict_proba(X_one)[:, 1], dtype=float)[0]
            )

        reconstruction_error = float(
            abs(reconstructed_probability - float(expected_probability))
        )

        risk = []
        protective = []
        for feature, shap_value in zip(self.feature_names, shap_values):
            item = {
                "feature": feature,
                "label": FEATURE_LABELS.get(feature, feature),
                "feature_value": _safe_value(original_values.get(feature)),
                "shap_value_raw": float(shap_value),
                "absolute_shap_value": float(abs(shap_value)),
                "effect": "raises_risk" if shap_value > 0 else "lowers_risk",
            }
            if shap_value > 0:
                risk.append(item)
            elif shap_value < 0:
                protective.append(item)

        risk.sort(key=lambda x: x["shap_value_raw"], reverse=True)
        protective.sort(key=lambda x: x["shap_value_raw"])

        return ShapExplanation(
            method="catboost_native_shap",
            base_value_raw=base,
            raw_score=raw_score,
            reconstructed_raw_score=reconstructed_raw,
            reconstructed_probability=reconstructed_probability,
            probability_reconstruction_error=reconstruction_error,
            top_risk_drivers=risk[:top_k],
            top_protective_drivers=protective[:top_k],
        )
