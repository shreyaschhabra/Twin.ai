"""
Production-style inference wrapper for the trained causal bottleneck XGBoost model.

What this module does
---------------------
1. Loads bottleneck_model_bundle.joblib once.
2. Enforces the exact frozen feature schema saved during training.
3. Preserves XGBoost categorical dtypes for station_id and station_archetype.
4. Accepts legitimate NaNs in numerical causal features.
5. Returns raw XGBoost bottleneck probability and the validation-selected threshold decision.
6. Can optionally return exact local TreeSHAP drivers using the same best_iteration
   used by predict_proba() after early stopping.

It does NOT:
- recompute causal features;
- use run_id, prediction_time, future labels, or target metadata as model inputs;
- perform probability recalibration (raw XGBoost was selected as best calibrated);
- decide how Light Zone / Dark Zone features are produced upstream.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

try:
    from ..model_io import load_bottleneck_model_bundle
except ImportError:  # Direct script execution
    import sys
    package_root = Path(__file__).resolve().parents[2]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from ml.model_io import load_bottleneck_model_bundle


class BottleneckPredictor:
    """Load once, predict many times."""

    def __init__(self, model_bundle_path: str | Path):
        self.model_bundle_path = Path(model_bundle_path)
        if not self.model_bundle_path.is_file():
            raise FileNotFoundError(
                f"Model bundle not found: {self.model_bundle_path}"
            )

        bundle, self.model, self.native_model_path = load_bottleneck_model_bundle(
            self.model_bundle_path
        )

        required_bundle_keys = {
            "features",
            "categorical_features",
            "category_levels",
            "threshold",
        }
        missing_bundle_keys = required_bundle_keys - set(bundle)
        if missing_bundle_keys:
            raise ValueError(
                "Model bundle is missing required keys: "
                + ", ".join(sorted(missing_bundle_keys))
            )

        self.features = list(bundle["features"])
        self.categorical_features = list(bundle["categorical_features"])
        self.category_levels = {
            key: list(value) for key, value in bundle["category_levels"].items()
        }
        self.threshold = float(bundle["threshold"])
        self.threshold_objective = bundle.get("threshold_objective", "unknown")

        if len(self.features) != 28:
            raise ValueError(
                f"Expected frozen 28-feature model, bundle contains {len(self.features)}."
            )

        if len(set(self.features)) != len(self.features):
            raise ValueError("Duplicate feature names found in model bundle.")

        for col in self.categorical_features:
            if col not in self.features:
                raise ValueError(
                    f"Categorical feature {col!r} is not in frozen feature list."
                )
            if col not in self.category_levels:
                raise ValueError(
                    f"Missing category levels for categorical feature {col!r}."
                )

    # ------------------------------------------------------------------
    # Input validation / preparation
    # ------------------------------------------------------------------
    def _frame_from_input(
        self,
        rows: dict[str, Any] | Iterable[dict[str, Any]] | pd.DataFrame,
    ) -> pd.DataFrame:
        if isinstance(rows, pd.DataFrame):
            frame = rows.copy()
        elif isinstance(rows, dict):
            frame = pd.DataFrame([rows])
        else:
            frame = pd.DataFrame(list(rows))

        if frame.empty:
            raise ValueError("No rows supplied for prediction.")

        missing = [feature for feature in self.features if feature not in frame.columns]
        if missing:
            raise ValueError(
                "Prediction input is missing frozen feature(s): "
                + ", ".join(missing)
            )

        # Extra columns such as station_id_buffer_id, prediction_time,
        # state metadata, run_id, etc. are allowed in the caller's row but
        # are intentionally excluded from X.
        frame = frame[self.features].copy()

        # Reconstruct exact training category dtype. Unknown categories become NaN.
        for col in self.categorical_features:
            values = frame[col].astype("string")
            frame[col] = pd.Categorical(
                values,
                categories=self.category_levels[col],
            )

        # Numeric NaNs are legitimate for causal features such as eta_std.
        for col in self.features:
            if col not in self.categorical_features:
                frame[col] = pd.to_numeric(
                    frame[col], errors="coerce"
                ).astype("float32")

        return frame

    def inspect_input(
        self,
        rows: dict[str, Any] | Iterable[dict[str, Any]] | pd.DataFrame,
    ) -> dict[str, Any]:
        """Return non-fatal input diagnostics before prediction."""
        if isinstance(rows, pd.DataFrame):
            original = rows.copy()
        elif isinstance(rows, dict):
            original = pd.DataFrame([rows])
        else:
            original = pd.DataFrame(list(rows))

        missing_features = [
            feature for feature in self.features if feature not in original.columns
        ]

        unknown_categories: dict[str, list[str]] = {}
        for col in self.categorical_features:
            if col not in original.columns:
                continue
            supplied = set(original[col].dropna().astype(str).unique())
            known = set(map(str, self.category_levels[col]))
            unknown = sorted(supplied - known)
            if unknown:
                unknown_categories[col] = unknown

        numeric_missing_counts: dict[str, int] = {}
        for col in self.features:
            if col in self.categorical_features or col not in original.columns:
                continue
            converted = pd.to_numeric(original[col], errors="coerce")
            count = int(converted.isna().sum())
            if count:
                numeric_missing_counts[col] = count

        return {
            "rows": int(len(original)),
            "missing_features": missing_features,
            "unknown_categories": unknown_categories,
            "numeric_missing_counts": numeric_missing_counts,
            "schema_valid": not missing_features,
        }

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def predict_frame(
        self,
        rows: dict[str, Any] | Iterable[dict[str, Any]] | pd.DataFrame,
    ) -> pd.DataFrame:
        X = self._frame_from_input(rows)
        probability = self.model.predict_proba(X)[:, 1].astype(float)
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

        # state_confidence is both an ML feature and a useful upstream quality signal.
        if "state_confidence" in X.columns:
            result["state_confidence"] = pd.to_numeric(
                X["state_confidence"], errors="coerce"
            ).to_numpy(dtype=float)

        return result

    def predict_one(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self.predict_frame(row).iloc[0].to_dict()
        # Convert numpy scalar types into plain Python values for JSON/API use.
        return {
            key: (
                bool(value)
                if isinstance(value, (np.bool_, bool))
                else float(value)
                if isinstance(value, (np.floating, float))
                else int(value)
                if isinstance(value, (np.integer, int))
                else value
            )
            for key, value in result.items()
        }

    # ------------------------------------------------------------------
    # Optional local exact TreeSHAP explanation
    # ------------------------------------------------------------------
    def explain_one(
        self,
        row: dict[str, Any],
        top_k: int = 6,
    ) -> dict[str, Any]:
        X = self._frame_from_input(row)
        probability = float(self.model.predict_proba(X)[:, 1][0])

        booster = self.model.get_booster()
        dmatrix = xgb.DMatrix(X, enable_categorical=True)

        best_iteration = getattr(self.model, "best_iteration", None)
        iteration_range = (
            (0, int(best_iteration) + 1)
            if best_iteration is not None
            else (0, 0)
        )

        if best_iteration is not None:
            contributions = booster.predict(
                dmatrix,
                pred_contribs=True,
                iteration_range=iteration_range,
            )[0]
        else:
            contributions = booster.predict(
                dmatrix,
                pred_contribs=True,
            )[0]

        shap_values = contributions[:-1]
        base_margin = float(contributions[-1])
        final_margin = float(base_margin + shap_values.sum())
        shap_probability = float(1.0 / (1.0 + math.exp(-final_margin)))

        order = np.argsort(np.abs(shap_values))[::-1][: max(1, int(top_k))]
        drivers = []

        for idx in order:
            raw_value = X.iloc[0, idx]
            if pd.isna(raw_value):
                display_value: Any = None
            elif self.features[idx] in self.categorical_features:
                display_value = str(raw_value)
            else:
                display_value = float(raw_value)

            shap_value = float(shap_values[idx])
            drivers.append(
                {
                    "feature": self.features[idx],
                    "value": display_value,
                    "shap_log_odds": shap_value,
                    "direction": (
                        "raises_risk" if shap_value > 0
                        else "lowers_risk" if shap_value < 0
                        else "neutral"
                    ),
                }
            )

        return {
            **self.predict_one(row),
            "base_margin": base_margin,
            "explained_probability": shap_probability,
            "probability_additivity_error": abs(
                probability - shap_probability
            ),
            "best_iteration_explained": (
                int(best_iteration) if best_iteration is not None else None
            ),
            "top_drivers": drivers,
        }


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_json_safe(v) for v in value]

    # CHECK BOOL BEFORE INT
    if isinstance(value, (np.bool_, bool)):
        return bool(value)

    if isinstance(value, (np.floating, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)

    if isinstance(value, (np.integer, int)):
        return int(value)

    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run inference with the frozen bottleneck XGBoost model."
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("bottleneck_model_artifacts/bottleneck_model_bundle.joblib"),
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="JSON object containing one 28-feature row.",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Return exact local TreeSHAP top drivers.",
    )
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args()

    if args.input_json is None:
        parser.error("--input-json is required for CLI prediction.")

    row = json.loads(args.input_json.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise ValueError("--input-json must contain one JSON object.")

    predictor = BottleneckPredictor(args.model)

    diagnostics = predictor.inspect_input(row)
    if not diagnostics["schema_valid"]:
        raise ValueError(
            "Invalid input schema: "
            + json.dumps(diagnostics, indent=2)
        )

    output = (
        predictor.explain_one(row, top_k=args.top_k)
        if args.explain
        else predictor.predict_one(row)
    )

    output["input_diagnostics"] = diagnostics
    print(json.dumps(_json_safe(output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
