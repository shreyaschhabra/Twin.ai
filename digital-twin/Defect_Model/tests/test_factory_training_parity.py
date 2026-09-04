from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Defect_Model.factory_models import (
    BASE_MODEL_DIR,
    model_paths,
    publish_factory_model,
    validate_runtime_factory_contract,
)
from Defect_Model.training.public_dataset import DEFECT_FEATURES, TARGET_COLUMN, replay_run_features

ROOT = Path(__file__).resolve().parents[2]
BASE_STATIONS = ROOT / "bottlenecks_prediction" / "data" / "input" / "current_run" / "stations.csv"
BASE_UNITS = ROOT / "bottlenecks_prediction" / "data" / "input" / "current_run" / "units.csv"

BUS_COLUMNS = [
    "sequence", "timestamp_ms", "record_type", "event_id", "event_type",
    "station_id", "unit_id", "queue_length_after", "previous_state", "new_state",
    "cycle_time_ms", "dark_zone_id", "checkpoint_id", "sensor_type", "sensor_value",
    "sensor_unit", "check_type", "check_result",
]


def _make_light_training_run(path: Path, result: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    pd.read_csv(BASE_STATIONS).to_csv(path / "stations.csv", index=False)
    unit = pd.read_csv(BASE_UNITS).head(1).copy()
    uid = str(unit.iloc[0]["unit_id"])
    unit.to_csv(path / "units.csv", index=False)

    pd.DataFrame(columns=[
        "dark_zone_id", "name", "start_station_id", "end_station_id",
        "sensor_telemetry", "manual_checks", "checkpoints",
    ]).to_csv(path / "dz.csv", index=False)
    pd.DataFrame(columns=[
        "station_id", "checkpoint_id", "checkpoint_type", "nominal_progress_fraction",
        "read_reliability", "false_positive_rate", "identifies_unit",
    ]).to_csv(path / "station_checkpoints.csv", index=False)

    # These legacy per-stream files are required only as completed-run provenance;
    # X is reconstructed exclusively from runtime_events.csv.
    pd.DataFrame(columns=["event_id", "timestamp_ms", "event_type", "station_id", "unit_id"]).to_csv(
        path / "station_events.csv", index=False
    )
    pd.DataFrame(columns=["timestamp_ms", "station_id", "sensor_type", "value"]).to_csv(
        path / "sensor_readings.csv", index=False
    )
    pd.DataFrame(columns=["timestamp_ms", "station_id", "unit_id", "check_type", "result"]).to_csv(
        path / "manual_checks.csv", index=False
    )

    bus = pd.DataFrame([
        {
            "sequence": 1, "timestamp_ms": 1_000, "record_type": "STATION",
            "event_id": "E1", "event_type": "UNIT_ARRIVED", "station_id": "S02",
            "unit_id": uid, "queue_length_after": 1,
        },
        {
            "sequence": 2, "timestamp_ms": 2_000, "record_type": "STATION",
            "event_id": "E2", "event_type": "PROCESSING_STARTED", "station_id": "S02",
            "unit_id": uid, "queue_length_after": 0,
        },
        {
            "sequence": 3, "timestamp_ms": 20_000, "record_type": "STATION",
            "event_id": "E3", "event_type": "PROCESSING_COMPLETED", "station_id": "S02",
            "unit_id": uid, "queue_length_after": 0, "cycle_time_ms": 18_000,
        },
        {
            "sequence": 4, "timestamp_ms": 21_000, "record_type": "STATION",
            "event_id": "E4", "event_type": "UNIT_ARRIVED", "station_id": "S03",
            "unit_id": uid, "queue_length_after": 1,
        },
    ], columns=BUS_COLUMNS)
    bus.to_csv(path / "runtime_events.csv", index=False)
    pd.DataFrame([{
        "timestamp_ms": 200_000, "station_id": "S31", "unit_id": uid,
        "defect_type": "" if result == "PASS" else "TEST", "severity": "" if result == "PASS" else 2,
        "result": result,
    }]).to_csv(path / "inspection_results.csv", index=False)
    (path / "run_metadata.json").write_text(json.dumps({"status": "completed"}) + "\n", encoding="utf-8")
    return path


def test_inspection_results_change_y_only_not_public_bus_features(tmp_path: Path):
    run = _make_light_training_run(tmp_path / "run_0001", "PASS")
    first, _ = replay_run_features(
        run, split="validation", history_runs=[],
        dark_zone_dir=ROOT / "bottlenecks_prediction" / "dark_zone",
        corridor_particles=50, random_seed=77,
    )
    qa = pd.read_csv(run / "inspection_results.csv")
    qa["result"] = "FAIL"
    qa.to_csv(run / "inspection_results.csv", index=False)
    second, _ = replay_run_features(
        run, split="validation", history_runs=[],
        dark_zone_dir=ROOT / "bottlenecks_prediction" / "dark_zone",
        corridor_particles=50, random_seed=77,
    )

    assert len(first) == len(second) > 0
    for name in DEFECT_FEATURES:
        a, b = first[name], second[name]
        if name in {"supplier_batch", "vehicle_model"}:
            assert a.fillna("<NA>").astype(str).tolist() == b.fillna("<NA>").astype(str).tolist()
        else:
            assert np.allclose(
                pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce"),
                rtol=0, atol=0, equal_nan=True,
            )
    assert first[["route", "prediction_trigger", "data_source"]].equals(
        second[["route", "prediction_trigger", "data_source"]]
    )
    assert set(first[TARGET_COLUMN].tolist()) == {0.0}
    assert set(second[TARGET_COLUMN].tolist()) == {1.0}


def _factory_contract(path: Path) -> Path:
    stations = pd.read_csv(BASE_STATIONS)
    rows = []
    for i, r in stations.iterrows():
        mean = float(r["base_cycle_time_ms"])
        std = float(r["cycle_time_std_ms"])
        rows.append({
            "id": int(i), "name": str(r.get("name", r["station_id"])),
            "archetype": str(r["archetype"]), "meanCycleTimeMs": mean,
            "cycleTimeCV": 0.0 if mean == 0 else std / mean,
            "bufferCapacity": int(r["buffer_capacity"]),
        })
    factory = {
        "stations": rows,
        "darkZones": [{
            "id": "DZ_TEST", "startStationId": 11, "endStationId": 14,
            "observability": {"sensorTelemetry": True, "manualChecks": True, "checkpoints": True},
        }],
        "checkpoints": [{
            "id": "CP_TEST", "stationId": 12, "type": "POWER_DRAW", "progress": 0.5,
            "reliability": 0.9, "falsePositiveRate": 0.0, "identifiesUnit": False,
        }],
    }
    path.write_text(json.dumps(factory), encoding="utf-8")
    return path


def test_factory_runtime_contract_normalizes_booleans_and_rejects_drift(tmp_path: Path):
    factory = _factory_contract(tmp_path / "factory.json")
    run = tmp_path / "run"
    run.mkdir()
    pd.read_csv(BASE_STATIONS).to_csv(run / "stations.csv", index=False)
    pd.DataFrame([{
        "dark_zone_id": "DZ_TEST", "name": "Test", "start_station_id": "S12", "end_station_id": "S15",
        "sensor_telemetry": "true", "manual_checks": "true", "checkpoints": "true",
    }]).to_csv(run / "dz.csv", index=False)
    pd.DataFrame([{
        "station_id": "S13", "checkpoint_id": "CP_TEST", "checkpoint_type": "POWER_DRAW",
        "nominal_progress_fraction": 0.5, "read_reliability": 0.9,
        "false_positive_rate": 0.0, "identifies_unit": "false",
    }]).to_csv(run / "station_checkpoints.csv", index=False)

    root = tmp_path / "artifacts"
    publish_factory_model(
        model_id="factory-a", factory_json=factory, stations_csv=run / "stations.csv",
        model_artifact_path=BASE_MODEL_DIR / "defect_v5_models.joblib",
        config_path=BASE_MODEL_DIR / "defect_v5_config.json",
        calibrator_path=BASE_MODEL_DIR / "defect_v5_calibrator.joblib",
        root=root,
    )
    paths = model_paths("factory-a", root)
    # Artifact booleans are parsed by pandas as bool while runtime values may be
    # literal strings; canonicalization must accept them as the same contract.
    validate_runtime_factory_contract(paths, run)

    dz = pd.read_csv(run / "dz.csv")
    dz.loc[0, "manual_checks"] = False
    dz.to_csv(run / "dz.csv", index=False)
    with pytest.raises(ValueError, match="DARK-zone observability"):
        validate_runtime_factory_contract(paths, run)
