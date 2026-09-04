"""Final dashboard/API output contract for Digital Twin bottleneck predictions.

This module sits at the END of the runtime pipeline:

    factory event
        -> runtime_controller.py
        -> Light/Dark 28-feature packet
        -> bottleneck_model_runtime.py
        -> BottleneckPrediction
        -> THIS MODULE
        -> dashboard/API/log file

It deliberately does not import the Light Zone, Dark Zone, runtime controller, or
XGBoost model.  It accepts either:

* a BottleneckPrediction-like object exposing ``as_dict()``; or
* a mapping/dict containing the prediction fields.

Keeping this layer independent makes the dashboard contract stable even if the
internal project folders are reorganized later. Runtime TreeSHAP details are
exposed under one nested ``explanation`` object so the flat prediction fields
remain backwards-compatible.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # Optional; used only to make numpy/pandas values JSON-safe when present.
    import numpy as np
except Exception:  # pragma: no cover - runtime does not require numpy here.
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - runtime does not require pandas here.
    pd = None  # type: ignore[assignment]


OUTPUT_SCHEMA_VERSION = "bottleneck-prediction-v1"

# Stable, dashboard-facing fields.  Internal 28-feature rows are intentionally
# NOT exposed here.
DASHBOARD_FIELDS = [
    "schema_version",
    "run_id",
    "timestamp_ms",
    "station_id",
    "vehicle_id",
    "zone",
    "route",
    "prediction_trigger",
    "bottleneck_probability",
    "bottleneck_risk_percent",
    "warning",
    "decision_threshold",
    "decision_threshold_percent",
    "state_confidence",
    "event_id",
    "event_sequence",
]


def _json_safe(value: Any) -> Any:
    """Convert common numpy/pandas/Python objects to strict JSON-safe values."""
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if pd is not None:
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        try:
            if value is not None and not isinstance(value, (str, bytes, bool)) and pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

    if np is not None:
        if isinstance(value, np.ndarray):
            return [_json_safe(v) for v in value.tolist()]
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            value = float(value)

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _prediction_mapping(prediction: Any) -> dict[str, Any]:
    """Normalize BottleneckPrediction-like objects and mappings into one dict."""
    if isinstance(prediction, Mapping):
        raw = dict(prediction)
    elif hasattr(prediction, "as_dict") and callable(prediction.as_dict):
        raw = dict(prediction.as_dict())
    else:
        raise TypeError(
            "prediction must be a Mapping/dict or expose a callable as_dict() method"
        )
    return _json_safe(raw)


def _zone_from_route(route: str) -> str:
    route_upper = str(route).strip().upper()
    if route_upper == "LIGHT":
        return "LIGHT"
    if route_upper.startswith("DARK"):
        return "DARK"
    # Preserve unexpected future route names instead of silently lying.
    return "UNKNOWN"


def format_prediction(
    prediction: Any,
    *,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Convert one internal prediction into the frozen dashboard contract.

    Parameters
    ----------
    prediction:
        Current ``BottleneckPrediction`` object or an equivalent dict.
    include_diagnostics:
        When True, append ``unknown_categories`` and ``dashboard_state`` under a
        nested ``diagnostics`` object.  The normal dashboard payload leaves these
        internal/debug details out.
    """
    raw = _prediction_mapping(prediction)

    required = {
        "route",
        "station_id",
        "prediction_time_ms",
        "bottleneck_probability",
        "bottleneck_risk_percent",
        "warning",
        "threshold",
        "threshold_percent",
    }
    missing = sorted(k for k in required if k not in raw)
    if missing:
        raise ValueError(f"Prediction is missing required output field(s): {missing}")

    probability = raw.get("bottleneck_probability")
    risk_percent = raw.get("bottleneck_risk_percent")
    threshold = raw.get("threshold")
    threshold_percent = raw.get("threshold_percent")

    payload: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "run_id": raw.get("run_id", "LIVE"),
        "timestamp_ms": int(raw["prediction_time_ms"]),
        "station_id": str(raw["station_id"]),
        "vehicle_id": raw.get("vehicle_id"),
        "zone": _zone_from_route(raw["route"]),
        "route": str(raw["route"]),
        "prediction_trigger": raw.get("trigger"),
        "bottleneck_probability": (
            float(probability) if probability is not None else None
        ),
        "bottleneck_risk_percent": (
            float(risk_percent) if risk_percent is not None else None
        ),
        "warning": bool(raw["warning"]),
        "decision_threshold": float(threshold) if threshold is not None else None,
        "decision_threshold_percent": (
            float(threshold_percent) if threshold_percent is not None else None
        ),
        "state_confidence": (
            float(raw["state_confidence"])
            if raw.get("state_confidence") is not None
            else None
        ),
        "event_id": raw.get("event_id"),
        "event_sequence": (
            int(raw["event_sequence"])
            if raw.get("event_sequence") is not None
            else None
        ),
        "explanation": {
            "top_drivers": raw.get("top_drivers") or [],
            "base_margin": raw.get("base_margin"),
            "explained_probability": raw.get("explained_probability"),
            "probability_additivity_error": raw.get("probability_additivity_error"),
            "best_iteration_explained": raw.get("best_iteration_explained"),
        },
    }

    if include_diagnostics:
        payload["diagnostics"] = {
            "unknown_categories": raw.get("unknown_categories") or {},
            "dashboard_state": raw.get("dashboard_state"),
        }

    return _json_safe(payload)


def format_predictions(
    predictions: Iterable[Any],
    *,
    include_diagnostics: bool = False,
) -> list[dict[str, Any]]:
    """Format multiple prediction objects using the same stable contract."""
    return [
        format_prediction(p, include_diagnostics=include_diagnostics)
        for p in predictions
    ]


def append_jsonl(
    output_path: str | Path,
    predictions: Any | Iterable[Any],
    *,
    include_diagnostics: bool = False,
) -> int:
    """Append one or more dashboard payloads to a JSONL runtime log.

    JSONL is the preferred persistent output because Dark Zone diagnostics can be
    nested without flattening or losing information.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(predictions, Mapping) or hasattr(predictions, "as_dict"):
        items = [predictions]
    else:
        items = list(predictions)

    formatted = format_predictions(items, include_diagnostics=include_diagnostics)
    with path.open("a", encoding="utf-8") as handle:
        for payload in formatted:
            handle.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
    return len(formatted)


def write_json(
    output_path: str | Path,
    predictions: Iterable[Any],
    *,
    include_diagnostics: bool = False,
    indent: int = 2,
) -> int:
    """Write a complete JSON array, useful for demos or batch replay results."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    formatted = format_predictions(predictions, include_diagnostics=include_diagnostics)
    path.write_text(
        json.dumps(formatted, ensure_ascii=False, allow_nan=False, indent=indent),
        encoding="utf-8",
    )
    return len(formatted)


def write_csv(
    output_path: str | Path,
    predictions: Iterable[Any],
) -> int:
    """Write the flat dashboard contract to CSV.

    Diagnostics are intentionally excluded from CSV. Use JSON/JSONL when Dark
    Zone diagnostic state is needed.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    formatted = format_predictions(predictions, include_diagnostics=False)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DASHBOARD_FIELDS)
        writer.writeheader()
        writer.writerows(formatted)
    return len(formatted)
