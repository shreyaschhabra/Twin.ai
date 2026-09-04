"""Production runtime adapter for the finalized V5 CatBoost defect model.

Loads the frozen V5 model once, scores exact 30-feature packets, applies the
frozen post-ML alert rule, and can attach native CatBoost SHAP explanations.

No retraining, no recalibration, no threshold tuning.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
import json
import math
import sys

import joblib
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from ..src.feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES
    from .defect_explainer import DefectShapExplainer
    from ..runtime.defect_feature_runtime import DefectFeaturePacket
except ImportError:  # direct legacy execution with Defect_Model on sys.path
    from feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES  # noqa: E402
    from ml.defect_explainer import DefectShapExplainer  # noqa: E402
    from runtime.defect_feature_runtime import DefectFeaturePacket  # noqa: E402


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return None if not math.isfinite(x) else x
    try:
        if value is not None and not isinstance(value, (str, bytes)) and pd.isna(value):
            return None
    except Exception:
        pass
    return value


@dataclass
class DefectPrediction:
    run_id: str
    unit_id: str
    station_id: str
    station_index: int
    prediction_time_ms: int
    final_station_id: str
    final_station_index: int
    raw_defect_probability: float
    defect_probability: float
    defect_risk_percent: float
    alert_policy: str
    alert_policy_score: Optional[float]
    decision_threshold: float
    threshold_crossed: bool
    warning: bool
    event_id: Optional[str] = None
    event_sequence: Optional[int] = None
    route: str = "LIGHT"
    prediction_trigger: str = "UNIT_ARRIVED"
    state_confidence: float = 1.0
    data_source: str = "direct_station_event"
    estimated_transition_time_ms: Optional[int] = None
    transition_confirmation_lag_ms: int = 0

    # Optional post-ML explanation fields.
    explanation_available: bool = False
    explanation_method: Optional[str] = None
    shap_value_space: Optional[str] = None
    shap_base_value_raw: Optional[float] = None
    shap_reconstructed_probability: Optional[float] = None
    shap_probability_reconstruction_error: Optional[float] = None
    top_risk_drivers: list[dict[str, Any]] = field(default_factory=list)
    top_protective_drivers: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return _json_safe(self.__dict__)


class DefectModelRuntime:
    """Load the frozen V5 model once and score exact 30-feature packets."""

    def __init__(
        self,
        model_artifact_path: str | Path,
        config_path: str | Path,
        calibrator_path: str | Path,
    ):
        self.model_artifact_path = Path(model_artifact_path).expanduser().resolve()
        self.config_path = Path(config_path).expanduser().resolve()
        self.calibrator_path = Path(calibrator_path).expanduser().resolve()

        for p, label in (
            (self.model_artifact_path, "V5 model artifact"),
            (self.config_path, "V5 config"),
            (self.calibrator_path, "V5 calibrator"),
        ):
            if not p.is_file():
                raise FileNotFoundError(f"{label} not found: {p}")

        self.artifact = joblib.load(self.model_artifact_path)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.calibrator = joblib.load(self.calibrator_path)

        if self.artifact.get("version") != "v5":
            raise ValueError("Model artifact is not V5")
        if self.config.get("version") != "v5":
            raise ValueError("Model config is not V5")

        self.features = list(self.artifact.get("feature_order", []))
        self.categorical_features = list(
            self.artifact.get("categorical_features", [])
        )

        if self.features != list(DEFECT_FEATURES):
            raise ValueError(
                "Saved V5 model feature order does not match src/feature_schema.py"
            )
        if list(self.config.get("features", [])) != list(DEFECT_FEATURES):
            raise ValueError(
                "defect_v5_config.json feature order does not match feature_schema.py"
            )
        if self.categorical_features != list(CATEGORICAL_FEATURES):
            raise ValueError("Saved V5 categorical feature contract differs")
        if int(self.config.get("feature_count", -1)) != 30:
            raise ValueError("Frozen V5 config must contain exactly 30 features")

        self.bundle = self.artifact["bundle"]
        self.selected_candidate = str(self.config["selected_candidate"])
        self.selected_calibration = str(self.config["selected_calibration"])
        self.alert_policy = str(self.config["selected_alert_policy"])
        self.threshold = float(self.config["selected_alert_threshold"])

        allowed = {
            "raw",
            "ema_0.3",
            "ema_0.5",
            "ema_0.7",
            "two_consecutive",
            "two_of_three",
        }
        if self.alert_policy not in allowed:
            raise ValueError(f"Unsupported frozen alert policy: {self.alert_policy}")

        # Final V5 is one CatBoost model. Native SHAP explanation is exact for it.
        if self.bundle.get("kind") != "ensemble" or len(self.bundle.get("models", [])) != 1:
            raise ValueError(
                "Runtime SHAP layer expects the finalized V5 one-model ensemble"
            )
        self._shap_explainer = DefectShapExplainer(
            model=self.bundle["models"][0],
            feature_names=self.features,
            categorical_features=self.categorical_features,
        )

        self._score_history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=3)
        )
        self._ema_state: dict[tuple[str, str, float], float] = {}

    def reset(self) -> None:
        self._score_history.clear()
        self._ema_state.clear()

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
            raise ValueError("No feature rows supplied")

        missing = [name for name in self.features if name not in frame.columns]
        if missing:
            raise ValueError(f"Prediction input missing frozen feature(s): {missing}")

        X = frame[self.features].copy()

        for col in self.categorical_features:
            X[col] = X[col].fillna("MISSING").astype(str)

        for col in self.features:
            if col not in self.categorical_features:
                X[col] = pd.to_numeric(X[col], errors="coerce")

        return X

    @staticmethod
    def _predict_models(models: Any, X: pd.DataFrame) -> np.ndarray:
        if not isinstance(models, (list, tuple)):
            models = [models]
        preds = [
            np.asarray(model.predict_proba(X)[:, 1], dtype=float)
            for model in models
        ]
        return np.mean(np.vstack(preds), axis=0)

    def _predict_bundle(self, bundle: dict[str, Any], X: pd.DataFrame) -> np.ndarray:
        kind = str(bundle["kind"])

        if kind == "ensemble":
            return self._predict_models(bundle["models"], X)

        if kind == "stage_ensemble":
            station = pd.to_numeric(
                X["prediction_station_index"], errors="coerce"
            ).to_numpy(dtype=float)
            out = np.full(len(X), np.nan, dtype=float)
            covered = np.zeros(len(X), dtype=int)

            bounds = {
                "early": (None, 17),
                "mid": (18, 23),
                "late": (24, None),
            }
            for stage, models in bundle["models_by_stage"].items():
                lower, upper = bounds[stage]
                mask = np.ones(len(X), dtype=bool)
                if lower is not None:
                    mask &= station >= lower
                if upper is not None:
                    mask &= station <= upper
                if mask.any():
                    out[mask] = self._predict_models(
                        models, X.loc[mask].reset_index(drop=True)
                    )
                    covered[mask] += 1

            if np.isnan(out).any() or not np.all(covered == 1):
                raise RuntimeError("Stage V5 bundle did not route every row exactly once")
            return out

        if kind == "blend":
            branches = [
                self._predict_bundle(branch, X)
                for branch in bundle["branches"]
            ]
            weights = np.asarray(bundle["weights"], dtype=float)
            weights = weights / weights.sum()
            return np.average(np.vstack(branches), axis=0, weights=weights)

        raise ValueError(f"Unknown V5 model bundle kind: {kind}")

    def _apply_calibration(self, raw_probability: np.ndarray) -> np.ndarray:
        method = self.selected_calibration
        raw_probability = np.asarray(raw_probability, dtype=float)

        if method == "none":
            return raw_probability
        if method == "platt":
            return np.asarray(
                self.calibrator.predict_proba(raw_probability.reshape(-1, 1))[:, 1],
                dtype=float,
            )
        if method == "isotonic":
            return np.asarray(self.calibrator.transform(raw_probability), dtype=float)
        raise ValueError(f"Unsupported calibration method: {method}")

    def predict_feature_rows(
        self,
        rows: Mapping[str, Any] | Iterable[Mapping[str, Any]] | pd.DataFrame,
    ) -> pd.DataFrame:
        X = self.prepare_features(rows)
        raw_probability = self._predict_bundle(self.bundle, X)
        reported_probability = self._apply_calibration(raw_probability)
        return pd.DataFrame(
            {
                "raw_defect_probability": raw_probability,
                "defect_probability": reported_probability,
                "defect_risk_percent": reported_probability * 100.0,
            }
        )

    def _policy_score(self, run_id: str, unit_id: str, raw_score: float) -> float:
        key = (str(run_id), str(unit_id))
        history = self._score_history[key]

        if self.alert_policy == "raw":
            score = float(raw_score)

        elif self.alert_policy.startswith("ema_"):
            alpha = float(self.alert_policy.split("_", 1)[1])
            ema_key = (key[0], key[1], alpha)
            prev = self._ema_state.get(ema_key)
            score = (
                float(raw_score)
                if prev is None
                else float(alpha * raw_score + (1.0 - alpha) * prev)
            )
            self._ema_state[ema_key] = score

        elif self.alert_policy == "two_consecutive":
            score = (
                float(min(history[-1], raw_score))
                if len(history) >= 1
                else np.nan
            )

        elif self.alert_policy == "two_of_three":
            values = list(history)[-2:] + [float(raw_score)]
            finite = np.asarray(
                [v for v in values if np.isfinite(v)], dtype=float
            )
            score = (
                float(np.partition(finite, -2)[-2])
                if len(finite) >= 2
                else np.nan
            )

        else:
            raise ValueError(self.alert_policy)

        history.append(float(raw_score))
        return float(score) if np.isfinite(score) else np.nan

    def explain_feature_row(
        self,
        features_30: Mapping[str, Any],
        *,
        top_k: int = 3,
        expected_probability: float | None = None,
    ) -> dict[str, Any]:
        X = self.prepare_features(features_30)
        explanation = self._shap_explainer.explain_prepared_row(
            X,
            features_30,
            top_k=top_k,
            expected_probability=expected_probability,
        )
        if explanation.probability_reconstruction_error > 1e-10:
            raise RuntimeError(
                "Runtime SHAP reconstruction failed: "
                f"{explanation.probability_reconstruction_error}"
            )
        return explanation.as_dict()

    def predict_packet(
        self,
        packet: DefectFeaturePacket,
        *,
        explain: bool = False,
        shap_top_k: int = 3,
    ) -> DefectPrediction:
        result = self.predict_feature_rows(packet.features_30).iloc[0]
        raw = float(result["raw_defect_probability"])
        reported = float(result["defect_probability"])

        policy_score = self._policy_score(
            packet.run_id,
            packet.unit_id,
            raw,
        )
        threshold_crossed = bool(
            np.isfinite(policy_score) and policy_score >= self.threshold
        )

        warning = bool(
            threshold_crossed
            and packet.station_index < packet.final_station_index
        )

        prediction = DefectPrediction(
            run_id=str(packet.run_id),
            unit_id=str(packet.unit_id),
            station_id=str(packet.station_id),
            station_index=int(packet.station_index),
            prediction_time_ms=int(packet.prediction_time_ms),
            final_station_id=str(packet.final_station_id),
            final_station_index=int(packet.final_station_index),
            raw_defect_probability=raw,
            defect_probability=reported,
            defect_risk_percent=reported * 100.0,
            alert_policy=self.alert_policy,
            alert_policy_score=(
                float(policy_score) if np.isfinite(policy_score) else None
            ),
            decision_threshold=self.threshold,
            threshold_crossed=threshold_crossed,
            warning=warning,
            event_id=packet.event_id,
            event_sequence=packet.event_sequence,
            route=str(packet.route),
            prediction_trigger=str(packet.prediction_trigger),
            state_confidence=float(packet.state_confidence),
            data_source=str(packet.data_source),
            estimated_transition_time_ms=packet.estimated_transition_time_ms,
            transition_confirmation_lag_ms=int(packet.transition_confirmation_lag_ms),
        )

        if explain:
            exp = self.explain_feature_row(
                packet.features_30,
                top_k=shap_top_k,
                expected_probability=raw,
            )
            prediction.explanation_available = True
            prediction.explanation_method = exp["method"]
            prediction.shap_value_space = exp["shap_value_space"]
            prediction.shap_base_value_raw = exp["base_value_raw"]
            prediction.shap_reconstructed_probability = exp[
                "reconstructed_probability"
            ]
            prediction.shap_probability_reconstruction_error = exp[
                "probability_reconstruction_error"
            ]
            prediction.top_risk_drivers = exp["top_risk_drivers"]
            prediction.top_protective_drivers = exp["top_protective_drivers"]

        return prediction

    def model_summary(self) -> dict[str, Any]:
        return {
            "version": "v5",
            "model_artifact": str(self.model_artifact_path),
            "selected_candidate": self.selected_candidate,
            "feature_count": len(self.features),
            "features": list(self.features),
            "categorical_features": list(self.categorical_features),
            "selected_calibration": self.selected_calibration,
            "selected_alert_policy": self.alert_policy,
            "selected_alert_threshold": self.threshold,
            "alert_score_space": self.config.get("alert_score_space"),
            "runtime_shap_supported": True,
            "runtime_shap_method": "catboost_native_shap",
        }
