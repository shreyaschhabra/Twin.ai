"""Shared parser for the simulator's ordered public runtime bus.

Both live defect inference and factory-training materialization must consume
exactly this contract.  Ground-truth inspection outcomes are explicitly
forbidden on the public inference/training-X bus.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_BUS_COLUMNS = {
    "sequence", "timestamp_ms", "record_type", "station_id", "unit_id",
    "checkpoint_id", "sensor_type", "sensor_value", "check_type", "check_result",
}


def _clean(value: str | None):
    if value is None or value == "":
        return None
    return value


def _float_or_none(value: str | None):
    value = _clean(value)
    return None if value is None else float(value)


def runtime_row_to_record(
    row: dict[str, str], progress_map: dict[tuple[str, str], float] | None = None
) -> dict | None:
    progress_map = progress_map or {}
    kind = str(row.get("record_type", "")).strip().upper()
    if kind == "INSPECTION":
        raise RuntimeError(
            "Ground-truth INSPECTION record appeared on runtime_events.csv. "
            "Inspection outcomes must never enter defect inference or training features."
        )

    timestamp = int(row["timestamp_ms"])
    station = str(row["station_id"]).strip()
    sequence = int(row["sequence"])

    if kind == "EVIDENCE":
        event_type = str(row.get("event_type", "")).strip().upper()
        checkpoint_id = str(row.get("checkpoint_id", "")).strip()
        key = (station, checkpoint_id)
        if key not in progress_map:
            raise ValueError(f"No checkpoint progress definition for {key}")
        return {
            "stream": "evidence",
            "timestamp_ms": timestamp,
            "station_id": station,
            "unit_id": _clean(row.get("unit_id")),
            "event_type": event_type,
            "event_id": _clean(row.get("event_id")),
            "checkpoint_id": checkpoint_id,
            "checkpoint_progress": float(progress_map[key]),
            "event_sequence": sequence,
        }

    if kind == "STATION":
        return {
            "stream": "station_event",
            "timestamp_ms": timestamp,
            "station_id": station,
            "unit_id": _clean(row.get("unit_id")),
            "event_type": str(row.get("event_type", "")).strip().upper(),
            "event_id": _clean(row.get("event_id")),
            "event_sequence": sequence,
            "queue_length_after": _float_or_none(row.get("queue_length_after")),
            "previous_state": _clean(row.get("previous_state")),
            "new_state": _clean(row.get("new_state")),
            "cycle_time_ms": _float_or_none(row.get("cycle_time_ms")),
            "dark_zone_id": _clean(row.get("dark_zone_id")),
        }

    if kind == "SENSOR":
        sensor_type = str(row.get("sensor_type", "")).strip().upper()
        value = _float_or_none(row.get("sensor_value"))
        if not sensor_type or value is None:
            raise ValueError("Malformed SENSOR record on runtime_events.csv")
        return {
            "stream": "sensor_reading",
            "timestamp_ms": timestamp,
            "station_id": station,
            "sensor_type": sensor_type,
            "value": value,
            "unit": _clean(row.get("sensor_unit")),
        }

    if kind == "MANUAL":
        unit_id = _clean(row.get("unit_id"))
        result = str(row.get("check_result", "")).strip().upper()
        if unit_id is None or result not in {"PASS", "FAIL"}:
            raise ValueError("Malformed MANUAL record on runtime_events.csv")
        return {
            "stream": "manual_check",
            "timestamp_ms": timestamp,
            "station_id": station,
            "unit_id": unit_id,
            "check_type": str(row.get("check_type", "")).strip(),
            "result": result,
        }

    raise ValueError(f"Unknown runtime_events.csv record_type: {kind!r}")


def checkpoint_progress_map(path: str | Path) -> dict[tuple[str, str], float]:
    frame = pd.read_csv(path)
    required = {"station_id", "checkpoint_id", "nominal_progress_fraction"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("station_checkpoints.csv missing: " + ", ".join(sorted(missing)))
    return {
        (str(r.station_id), str(r.checkpoint_id)): float(r.nominal_progress_fraction)
        for r in frame.itertuples(index=False)
    }
