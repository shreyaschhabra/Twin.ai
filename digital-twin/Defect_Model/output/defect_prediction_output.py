"""Stable dashboard/API contract for V5 defect predictions + SHAP."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

OUTPUT_SCHEMA_VERSION = "defect-prediction-v2"


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_safe(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if value is not None and not isinstance(value, (str, bytes, bool)) and pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _mapping(prediction: Any) -> dict[str, Any]:
    if isinstance(prediction, Mapping):
        return _safe(dict(prediction))
    if hasattr(prediction, "as_dict") and callable(prediction.as_dict):
        return _safe(dict(prediction.as_dict()))
    raise TypeError("prediction must be a mapping or expose as_dict()")


def format_prediction(prediction: Any) -> dict[str, Any]:
    raw = _mapping(prediction)
    required = {
        "run_id",
        "unit_id",
        "station_id",
        "station_index",
        "prediction_time_ms",
        "final_station_id",
        "raw_defect_probability",
        "defect_probability",
        "defect_risk_percent",
        "alert_policy",
        "decision_threshold",
        "threshold_crossed",
        "warning",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"Prediction missing required output field(s): {missing}")

    return _safe(
        {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "run_id": raw["run_id"],
            "timestamp_ms": int(raw["prediction_time_ms"]),
            "unit_id": str(raw["unit_id"]),
            "station_id": str(raw["station_id"]),
            "station_index": int(raw["station_index"]),
            "final_inspection_station": str(raw["final_station_id"]),
            "defect_probability": float(raw["defect_probability"]),
            "defect_risk_percent": float(raw["defect_risk_percent"]),
            "raw_defect_probability": float(raw["raw_defect_probability"]),
            "warning": bool(raw["warning"]),
            "threshold_crossed": bool(raw["threshold_crossed"]),
            "alert_policy": str(raw["alert_policy"]),
            "alert_policy_score": raw.get("alert_policy_score"),
            "decision_threshold": float(raw["decision_threshold"]),
            "event_id": raw.get("event_id"),
            "event_sequence": raw.get("event_sequence"),
            "route": str(raw.get("route", "LIGHT")),
            "prediction_trigger": str(raw.get("prediction_trigger", "UNIT_ARRIVED")),
            "state_confidence": float(raw.get("state_confidence", 1.0)),
            "data_source": str(raw.get("data_source", "direct_station_event")),
            "estimated_transition_time_ms": raw.get("estimated_transition_time_ms"),
            "transition_confirmation_lag_ms": int(raw.get("transition_confirmation_lag_ms", 0) or 0),
            "explanation_available": bool(raw.get("explanation_available", False)),
            "explanation_method": raw.get("explanation_method"),
            "shap_value_space": raw.get("shap_value_space"),
            "shap_base_value_raw": raw.get("shap_base_value_raw"),
            "shap_reconstructed_probability": raw.get(
                "shap_reconstructed_probability"
            ),
            "shap_probability_reconstruction_error": raw.get(
                "shap_probability_reconstruction_error"
            ),
            "top_risk_drivers": raw.get("top_risk_drivers", []),
            "top_protective_drivers": raw.get("top_protective_drivers", []),
        }
    )


def append_jsonl(output_path: str | Path, predictions: Iterable[Any]) -> int:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [format_prediction(p) for p in predictions]
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return len(rows)
