from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from Defect_Model.run_current_defects import _runtime_row_to_record, main as live_main
from Defect_Model.runtime.defect_feature_runtime import DefectRuntimeFeatureBuilder


BUS_HEADER = [
    "sequence", "timestamp_ms", "record_type", "event_id", "event_type",
    "station_id", "unit_id", "queue_length_after", "previous_state",
    "new_state", "cycle_time_ms", "dark_zone_id", "checkpoint_id",
    "sensor_type", "sensor_value", "sensor_unit", "check_type", "check_result",
]


def _write_bus(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BUS_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _stations(path: Path) -> Path:
    pd.DataFrame([
        {"station_id": "S01", "archetype": "AUTOMATED"},
        {"station_id": "S02", "archetype": "AUTOMATED"},
        {"station_id": "S03", "archetype": "INSPECTION"},
    ]).to_csv(path, index=False)
    return path


def _units(path: Path, count: int = 1) -> Path:
    rows = [
        {
            "unit_id": f"U{i:06d}",
            "created_at_ms": 0,
            "vehicle_model": "MODEL_A",
            "supplier_batch": "BATCH_01",
        }
        for i in range(1, count + 1)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_runtime_bus_parses_defect_records_and_rejects_ground_truth():
    sensor = {k: "" for k in BUS_HEADER}
    sensor.update({
        "sequence": "1", "timestamp_ms": "100", "record_type": "SENSOR",
        "event_type": "SENSOR_READING", "station_id": "S02",
        "sensor_type": "VIBRATION", "sensor_value": "1.25", "sensor_unit": "g",
    })
    record = _runtime_row_to_record(sensor)
    assert record == {
        "stream": "sensor_reading", "timestamp_ms": 100, "station_id": "S02",
        "sensor_type": "VIBRATION", "value": 1.25, "unit": "g",
    }

    manual = {k: "" for k in BUS_HEADER}
    manual.update({
        "sequence": "2", "timestamp_ms": "200", "record_type": "MANUAL",
        "event_type": "MANUAL_CHECK", "station_id": "S02", "unit_id": "U000001",
        "check_type": "VISUAL_ALIGNMENT", "check_result": "FAIL",
    })
    record = _runtime_row_to_record(manual)
    assert record["stream"] == "manual_check"
    assert record["result"] == "FAIL"

    inspection = {k: "" for k in BUS_HEADER}
    inspection.update({
        "sequence": "3", "timestamp_ms": "300", "record_type": "INSPECTION",
        "station_id": "S03", "unit_id": "U000001",
    })
    with pytest.raises(RuntimeError, match="Ground-truth INSPECTION"):
        _runtime_row_to_record(inspection)


def test_live_unit_refresh_is_append_only(tmp_path: Path):
    stations = _stations(tmp_path / "stations.csv")
    units = _units(tmp_path / "units.csv", 1)
    builder = DefectRuntimeFeatureBuilder(stations, units)
    _units(units, 2)
    assert builder.refresh_units(units) == 1
    assert "U000002" in builder._units.index

    changed = pd.read_csv(units)
    changed.loc[changed.unit_id.eq("U000001"), "vehicle_model"] = "MODEL_B"
    changed.to_csv(units, index=False)
    with pytest.raises(ValueError, match="mutated existing unit"):
        builder.refresh_units(units)


def test_live_consumer_scores_shared_bus(tmp_path: Path):
    # Use the real 32-station base contract so this is also a model smoke test.
    repo_root = Path(__file__).resolve().parents[2]
    source_run = repo_root / "bottlenecks_prediction" / "data" / "input" / "current_run"
    run = tmp_path / "run"
    run.mkdir()
    pd.read_csv(source_run / "stations.csv").to_csv(run / "stations.csv", index=False)
    unit_frame = pd.read_csv(source_run / "units.csv").head(1).copy()
    unit_frame.to_csv(run / "units.csv", index=False)
    # New simulator contract: dz.csv is authoritative even for an all-LIGHT run,
    # and station_checkpoints.csv is part of the shared public bus contract.
    pd.DataFrame(columns=[
        "dark_zone_id", "name", "start_station_id", "end_station_id",
        "sensor_telemetry", "manual_checks", "checkpoints",
    ]).to_csv(run / "dz.csv", index=False)
    pd.DataFrame(columns=[
        "station_id", "checkpoint_id", "checkpoint_type",
        "nominal_progress_fraction", "identifies_unit",
    ]).to_csv(run / "station_checkpoints.csv", index=False)
    uid = str(unit_frame.iloc[0]["unit_id"])

    rows = []
    def add(**kwargs):
        row = {k: "" for k in BUS_HEADER}
        row.update(kwargs)
        rows.append(row)
    add(sequence=1, timestamp_ms=0, record_type="STATION", event_id="EV1",
        event_type="PROCESSING_STARTED", station_id="S01", unit_id=uid,
        queue_length_after=0, previous_state="IDLE", new_state="PROCESSING", cycle_time_ms=1000)
    add(sequence=2, timestamp_ms=100, record_type="SENSOR", event_type="SENSOR_READING",
        station_id="S01", sensor_type="VIBRATION", sensor_value=1.1, sensor_unit="g")
    add(sequence=3, timestamp_ms=1000, record_type="STATION", event_id="EV2",
        event_type="PROCESSING_COMPLETED", station_id="S01", unit_id=uid,
        queue_length_after=0, previous_state="PROCESSING", new_state="IDLE", cycle_time_ms=1000)
    add(sequence=4, timestamp_ms=1001, record_type="STATION", event_id="EV3",
        event_type="UNIT_ARRIVED", station_id="S02", unit_id=uid, queue_length_after=0)
    _write_bus(run / "runtime_events.csv", rows)
    (run / "run_metadata.json").write_text(json.dumps({"run_id": "LIVE_TEST"}), encoding="utf-8")

    out = tmp_path / "predictions.jsonl"
    rc = live_main([
        "--run-dir", str(run), "--output", str(out), "--run-id", "LIVE_TEST",
        "--explain-mode", "off", "--poll-ms", "10", "--wait-seconds", "1",
    ])
    assert rc == 0
    payloads = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(payloads) == 1
    assert payloads[0]["station_id"] == "S02"
    assert 0.0 <= payloads[0]["defect_probability"] <= 1.0
