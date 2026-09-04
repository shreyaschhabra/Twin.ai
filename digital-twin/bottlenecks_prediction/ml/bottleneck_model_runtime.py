"""Route-agnostic runtime inference for the frozen 28-feature bottleneck XGBoost model.

This module sits AFTER runtime_controller.py.  It does not know how a feature row
was produced (LIGHT, isolated DARK, or DARK corridor) and it never recomputes
features.  It only:

1. loads the frozen bottleneck_model_bundle.joblib once;
2. enforces the exact 28-feature training contract;
3. restores categorical dtypes exactly as used during training;
4. calls predict_proba();
5. computes exact XGBoost TreeSHAP contributions for runtime explainability;
6. applies the saved F2-selected decision threshold; and
7. returns a JSON-safe prediction while preserving routing/quality metadata.

The existing Dark Zone dark_zone_model_adapter.py is intentionally NOT used by
this production path.  Keep that file for Dark-only offline validation/debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from datetime import date, datetime
import math
import sys

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

# Allow this module to be imported/executed directly during diagnostics.
if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from light_zone.light_zone_runtime import BOTTLENECK_FEATURES

try:
    from runtime.runtime_controller import FeaturePacket
except Exception:  # Allows this file to be inspected independently.
    FeaturePacket = Any  # type: ignore[misc,assignment]


_REQUIRED_BUNDLE_KEYS = {
    "features",
    "categorical_features",
    "category_levels",
    "threshold",
}


def _json_safe(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars and non-finite floats for APIs."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return None if (math.isnan(x) or math.isinf(x)) else x
    if not isinstance(value, str):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
    return value


@dataclass
class BottleneckPrediction:
    """One dashboard/API-ready result produced from one FeaturePacket."""

    run_id: str
    route: str
    trigger: str
    station_id: str
    prediction_time_ms: int
    bottleneck_probability: float
    bottleneck_risk_percent: float
    warning: bool
    threshold: float
    threshold_percent: float
    state_confidence: Optional[float]
    top_drivers: Optional[list[dict[str, Any]]] = None
    base_margin: Optional[float] = None
    explained_probability: Optional[float] = None
    probability_additivity_error: Optional[float] = None
    best_iteration_explained: Optional[int] = None
    vehicle_id: Optional[str] = None
    event_id: Optional[str] = None
    event_sequence: Optional[int] = None
    unknown_categories: Optional[dict[str, list[str]]] = None
    dashboard_state: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "run_id": self.run_id,
                "route": self.route,
                "trigger": self.trigger,
                "station_id": self.station_id,
                "prediction_time_ms": self.prediction_time_ms,
                "vehicle_id": self.vehicle_id,
                "event_id": self.event_id,
                "event_sequence": self.event_sequence,
                "bottleneck_probability": self.bottleneck_probability,
                "bottleneck_risk_percent": self.bottleneck_risk_percent,
                "warning": self.warning,
                "threshold": self.threshold,
                "threshold_percent": self.threshold_percent,
                "state_confidence": self.state_confidence,
                "top_drivers": self.top_drivers or [],
                "base_margin": self.base_margin,
                "explained_probability": self.explained_probability,
                "probability_additivity_error": self.probability_additivity_error,
                "best_iteration_explained": self.best_iteration_explained,
                "unknown_categories": self.unknown_categories or {},
                "dashboard_state": self.dashboard_state,
            }
        )


class BottleneckModelRuntime:
    """Load the frozen model once and score Light/Dark 28-feature packets."""

    def __init__(self, model_bundle_path: str | Path):
        self.model_bundle_path = Path(model_bundle_path).expanduser().resolve()
        if not self.model_bundle_path.is_file():
            raise FileNotFoundError(f"Model bundle not found: {self.model_bundle_path}")

        bundle = joblib.load(self.model_bundle_path)
        missing = sorted(_REQUIRED_BUNDLE_KEYS - set(bundle))
        if missing:
            raise ValueError(f"Model bundle missing required keys: {missing}")

        native_name = str(bundle.get("xgboost_model", "bottleneck_xgboost.json"))
        native_path = Path(native_name)
        if not native_path.is_absolute():
            native_path = self.model_bundle_path.parent / native_path
        self.native_model_path: Optional[Path] = None
        if native_path.is_file():
            # Native XGBoost serialization is stable across Python/joblib versions
            # and avoids unpickling an estimator produced by an older XGBoost.
            self.model = xgb.XGBClassifier()
            self.model.load_model(native_path)
            self.native_model_path = native_path.resolve()
        elif "model" in bundle:
            # Backward-compatible fallback for old third-party artifacts. New
            # project training never writes the estimator into joblib.
            import warnings
            warnings.warn(
                "Native bottleneck_xgboost.json is missing; falling back to the legacy "
                "pickled XGBoost estimator. Re-export this artifact before deployment.",
                RuntimeWarning,
            )
            self.model = bundle["model"]
        else:
            raise FileNotFoundError(
                f"Native XGBoost model not found: {native_path}; bundle contains no legacy model"
            )
        self.features = list(bundle["features"])
        self.categorical_features = list(bundle["categorical_features"])
        self.category_levels = {
            str(k): list(v) for k, v in bundle["category_levels"].items()
        }
        self.threshold = float(bundle["threshold"])
        self.threshold_objective = bundle.get("threshold_objective", "unknown")

        # This is the key integration gate: model, Light and Dark must all agree.
        if self.features != list(BOTTLENECK_FEATURES):
            raise ValueError(
                "Saved XGBoost feature contract does not match runtime 28-feature contract.\n"
                f"model={self.features}\nruntime={list(BOTTLENECK_FEATURES)}"
            )
        if len(self.features) != 28 or len(set(self.features)) != 28:
            raise ValueError("Frozen bottleneck model must contain 28 unique features")

        for col in self.categorical_features:
            if col not in self.features:
                raise ValueError(f"Categorical feature {col!r} is not in model features")
            if col not in self.category_levels:
                raise ValueError(f"No saved category levels for {col!r}")

    # ------------------------------------------------------------------
    # Strict model-input preparation
    # ------------------------------------------------------------------
    def prepare_features(
        self,
        rows: Mapping[str, Any] | Iterable[Mapping[str, Any]] | pd.DataFrame,
    ) -> pd.DataFrame:
        if isinstance(rows, pd.DataFrame):
            frame = rows.copy()
        elif isinstance(rows, Mapping):
            frame = pd.DataFrame([dict(rows)])
        else:
            frame = pd.DataFrame([dict(r) for r in rows])

        if frame.empty:
            raise ValueError("No rows supplied for XGBoost prediction")

        missing = [f for f in self.features if f not in frame.columns]
        if missing:
            raise ValueError(f"Prediction input missing frozen feature(s): {missing}")

        # Extras are intentionally ignored; XGBoost sees exactly the training X.
        X = frame[self.features].copy()

        for col in self.categorical_features:
            X[col] = pd.Categorical(
                X[col].astype("string"),
                categories=self.category_levels[col],
            )

        for col in self.features:
            if col not in self.categorical_features:
                X[col] = pd.to_numeric(X[col], errors="coerce").astype("float32")

        return X

    def inspect_features(self, row: Mapping[str, Any]) -> dict[str, Any]:
        supplied = dict(row)
        missing = [f for f in self.features if f not in supplied]
        unknown_categories: dict[str, list[str]] = {}

        for col in self.categorical_features:
            if col not in supplied or supplied[col] is None:
                continue
            value = str(supplied[col])
            known = set(map(str, self.category_levels[col]))
            if value not in known:
                unknown_categories[col] = [value]

        return {
            "schema_valid": not missing,
            "missing_features": missing,
            "unknown_categories": unknown_categories,
        }

    # ------------------------------------------------------------------
    # Exact TreeSHAP explanation
    # ------------------------------------------------------------------
    def _tree_shap(
        self,
        X: pd.DataFrame,
        original_rows: list[Mapping[str, Any]],
        *,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Return exact XGBoost pred_contribs explanations for prepared rows.

        XGBoost's ``pred_contribs`` is TreeSHAP for tree models.  The final
        contribution is the bias/base margin; the other 28 contributions align
        exactly with the frozen feature order.  We explain the same tree range
        used by the sklearn wrapper after early stopping.
        """
        if len(X) != len(original_rows):
            raise ValueError("X/original_rows length mismatch for SHAP explanation")

        dmatrix = xgb.DMatrix(X, enable_categorical=True)
        kwargs: dict[str, Any] = {"pred_contribs": True}
        best_iteration = getattr(self.model, "best_iteration", None)
        if best_iteration is not None:
            kwargs["iteration_range"] = (0, int(best_iteration) + 1)

        contributions = np.asarray(
            self.model.get_booster().predict(dmatrix, **kwargs),
            dtype=float,
        )
        if contributions.ndim == 1:
            contributions = contributions.reshape(1, -1)
        if contributions.shape[1] != len(self.features) + 1:
            raise RuntimeError(
                "Unexpected TreeSHAP shape: "
                f"{contributions.shape}; expected {len(self.features) + 1} columns"
            )

        explanations: list[dict[str, Any]] = []
        for row_index, contrib in enumerate(contributions):
            feature_contrib = contrib[:-1]
            base_margin = float(contrib[-1])
            total_margin = float(np.sum(contrib))
            # Numerically stable logistic transform.
            if total_margin >= 0:
                explained_probability = 1.0 / (1.0 + math.exp(-total_margin))
            else:
                exp_m = math.exp(total_margin)
                explained_probability = exp_m / (1.0 + exp_m)

            order = np.argsort(np.abs(feature_contrib))[::-1][: max(0, int(top_n))]
            original = dict(original_rows[row_index])
            top_drivers = []
            for feature_index in order:
                shap_value = float(feature_contrib[int(feature_index)])
                feature_name = self.features[int(feature_index)]
                top_drivers.append(
                    {
                        "feature": feature_name,
                        "value": _json_safe(original.get(feature_name)),
                        "shap_log_odds": shap_value,
                        "direction": (
                            "increases_risk" if shap_value > 0
                            else "decreases_risk" if shap_value < 0
                            else "neutral"
                        ),
                    }
                )

            explanations.append(
                {
                    "top_drivers": top_drivers,
                    "base_margin": base_margin,
                    "explained_probability": float(explained_probability),
                    "best_iteration_explained": (
                        int(best_iteration) if best_iteration is not None else None
                    ),
                }
            )
        return explanations

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def predict_feature_rows(
        self,
        rows: Mapping[str, Any] | Iterable[Mapping[str, Any]] | pd.DataFrame,
    ) -> pd.DataFrame:
        X = self.prepare_features(rows)
        probability = np.asarray(self.model.predict_proba(X)[:, 1], dtype=float)
        warning = probability >= self.threshold

        result = pd.DataFrame(
            {
                "bottleneck_probability": probability,
                "bottleneck_risk_percent": probability * 100.0,
                "warning": warning.astype(bool),
                "threshold": self.threshold,
                "threshold_percent": self.threshold * 100.0,
            }
        )
        result["state_confidence"] = pd.to_numeric(
            X["state_confidence"], errors="coerce"
        ).to_numpy(dtype=float)
        return result

    def predict_features(self, row: Mapping[str, Any]) -> dict[str, Any]:
        diagnostic = self.inspect_features(row)
        if not diagnostic["schema_valid"]:
            raise ValueError(
                f"Invalid model feature row; missing: {diagnostic['missing_features']}"
            )

        X = self.prepare_features(row)
        probability = float(self.model.predict_proba(X)[0, 1])
        state_value = pd.to_numeric(
            X["state_confidence"], errors="coerce"
        ).to_numpy(dtype=float)[0]
        explanation = self._tree_shap(X, [row], top_n=5)[0]
        additivity_error = abs(
            float(explanation["explained_probability"]) - probability
        )

        return _json_safe(
            {
                "bottleneck_probability": probability,
                "bottleneck_risk_percent": probability * 100.0,
                "warning": bool(probability >= self.threshold),
                "threshold": self.threshold,
                "threshold_percent": self.threshold * 100.0,
                "state_confidence": float(state_value) if np.isfinite(state_value) else None,
                "unknown_categories": diagnostic["unknown_categories"],
                "top_drivers": explanation["top_drivers"],
                "base_margin": explanation["base_margin"],
                "explained_probability": explanation["explained_probability"],
                "probability_additivity_error": additivity_error,
                "best_iteration_explained": explanation["best_iteration_explained"],
            }
        )

    def predict_packet(self, packet: FeaturePacket) -> BottleneckPrediction:
        """Score one packet through the same batch-capable inference path."""
        return self.predict_packets([packet])[0]

    def predict_packets(self, packets: Iterable[FeaturePacket]) -> list[BottleneckPrediction]:
        """Score packets with one DataFrame, one XGBoost call, and one SHAP call.

        This removes the old per-prediction pandas/dtype/DMatrix setup cost while
        preserving packet order and exactly the same model/threshold semantics.
        """
        items = list(packets)
        if not items:
            return []

        rows = [packet.features_28 for packet in items]
        diagnostics = [self.inspect_features(row) for row in rows]
        invalid = [
            (i, d["missing_features"])
            for i, d in enumerate(diagnostics)
            if not d["schema_valid"]
        ]
        if invalid:
            raise ValueError(f"Invalid model feature row(s); missing: {invalid}")

        X = self.prepare_features(rows)
        probabilities = np.asarray(self.model.predict_proba(X)[:, 1], dtype=float)
        state_values = pd.to_numeric(
            X["state_confidence"], errors="coerce"
        ).to_numpy(dtype=float)
        explanations = self._tree_shap(X, rows, top_n=5)

        results: list[BottleneckPrediction] = []
        for i, packet in enumerate(items):
            probability = float(probabilities[i])
            explanation = explanations[i]
            results.append(
                BottleneckPrediction(
                    run_id=str(packet.run_id),
                    route=str(packet.route),
                    trigger=str(packet.trigger),
                    station_id=str(packet.station_id),
                    prediction_time_ms=int(packet.prediction_time_ms),
                    vehicle_id=(str(packet.vehicle_id) if packet.vehicle_id is not None else None),
                    event_id=(str(packet.event_id) if packet.event_id is not None else None),
                    event_sequence=(int(packet.event_sequence) if packet.event_sequence is not None else None),
                    bottleneck_probability=probability,
                    bottleneck_risk_percent=probability * 100.0,
                    warning=bool(probability >= self.threshold),
                    threshold=self.threshold,
                    threshold_percent=self.threshold * 100.0,
                    state_confidence=(float(state_values[i]) if np.isfinite(state_values[i]) else None),
                    top_drivers=list(explanation["top_drivers"]),
                    base_margin=float(explanation["base_margin"]),
                    explained_probability=float(explanation["explained_probability"]),
                    probability_additivity_error=abs(float(explanation["explained_probability"]) - probability),
                    best_iteration_explained=explanation["best_iteration_explained"],
                    unknown_categories=dict(diagnostics[i]["unknown_categories"]),
                    dashboard_state=packet.dashboard_state,
                )
            )
        return results

    def model_summary(self) -> dict[str, Any]:
        return {
            "model_bundle": str(self.model_bundle_path),
            "native_xgboost_model": str(self.native_model_path) if self.native_model_path else None,
            "feature_count": len(self.features),
            "features": list(self.features),
            "categorical_features": list(self.categorical_features),
            "threshold": self.threshold,
            "threshold_percent": self.threshold * 100.0,
            "threshold_objective": self.threshold_objective,
        }
