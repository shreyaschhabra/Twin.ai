from __future__ import annotations

import json
from pathlib import Path

import pytest
import pandas as pd

from ml.bottleneck_model_runtime import BottleneckModelRuntime
from output.prediction_output import OUTPUT_SCHEMA_VERSION, format_prediction
from runtime.digital_twin_pipeline import DigitalTwinBottleneckPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_BUNDLE = (
    PROJECT_ROOT
    / "ml"
    / "bottleneck_model"
    / "bottleneck_model_artifacts"
    / "bottleneck_model_bundle.joblib"
)
DARK_ZONE_DIR = PROJECT_ROOT / "dark_zone"
SAMPLE_INPUT = PROJECT_ROOT / "ml" / "bottleneck_model" / "sample_input.json"


def _write_all_light_inputs(root: Path) -> tuple[Path, Path]:
    stations = root / "configured_stations.csv"
    units = root / "units.csv"
    pd.DataFrame(
        [
            {
                "station_id": "S02",
                "archetype": "AUTOMATED",
                "base_cycle_time_ms": 34_000,
                "cycle_time_std_ms": 3_400,
                "buffer_capacity": 12,
                "sensor_coverage": "NORMAL",
            }
        ]
    ).to_csv(stations, index=False)
    pd.DataFrame([{"unit_id": "U1", "vehicle_model": "A"}]).to_csv(units, index=False)
    return stations, units


def test_frozen_model_reproduces_known_reference_probability() -> None:
    runtime = BottleneckModelRuntime(MODEL_BUNDLE)
    row = json.loads(SAMPLE_INPUT.read_text(encoding="utf-8"))
    result = runtime.predict_features(row)

    assert result["bottleneck_probability"] == pytest.approx(
        0.08016174286603928, rel=1e-6, abs=1e-9
    )
    assert result["bottleneck_risk_percent"] == pytest.approx(
        8.016174286603928, rel=1e-6, abs=1e-7
    )
    assert result["threshold"] == pytest.approx(0.1555924266576767)
    assert result["warning"] is False
    assert result["best_iteration_explained"] == 78
    assert result["probability_additivity_error"] < 1e-6
    assert result["explained_probability"] == pytest.approx(
        result["bottleneck_probability"], abs=1e-6
    )
    assert len(result["top_drivers"]) == 5
    assert result["top_drivers"][0]["feature"] == "station_id"


def test_event_to_dashboard_output_end_to_end(tmp_path: Path) -> None:
    stations_csv, units_csv = _write_all_light_inputs(tmp_path)
    pipeline = DigitalTwinBottleneckPipeline(
        configured_stations_csv=stations_csv,
        units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR,
        model_bundle_path=MODEL_BUNDLE,
        run_id="E2E",
    )

    event = {
        "event_id": "EV001",
        "timestamp_ms": 0,
        "event_type": "UNIT_ARRIVED",
        "station_id": "S02",
        "unit_id": "U1",
        "queue_length_after": 1,
        "previous_state": "IDLE",
        "new_state": "QUEUED",
        "cycle_time_ms": None,
    }
    predictions = pipeline.process_event(event)
    assert len(predictions) == 1

    payload = format_prediction(predictions[0])
    assert payload["schema_version"] == OUTPUT_SCHEMA_VERSION
    assert payload["run_id"] == "E2E"
    assert payload["station_id"] == "S02"
    assert payload["zone"] == "LIGHT"
    assert payload["route"] == "LIGHT"
    assert payload["timestamp_ms"] == 0
    assert 0.0 <= payload["bottleneck_probability"] <= 1.0
    assert payload["bottleneck_risk_percent"] == pytest.approx(
        payload["bottleneck_probability"] * 100.0
    )
    assert payload["decision_threshold"] == pytest.approx(pipeline.model.threshold)
    assert isinstance(payload["warning"], bool)
    assert payload["explanation"]["top_drivers"]
    assert payload["explanation"]["probability_additivity_error"] < 1e-6


def test_main_replay_command_writes_dashboard_jsonl(tmp_path: Path) -> None:
    from main import main as app_main

    stations_csv, units_csv = _write_all_light_inputs(tmp_path)
    events_csv = tmp_path / "station_events.csv"
    output_jsonl = tmp_path / "predictions.jsonl"
    pd.DataFrame(
        [
            {
                "event_id": "EV001",
                "timestamp_ms": 0,
                "event_type": "UNIT_ARRIVED",
                "station_id": "S02",
                "unit_id": "U1",
                "queue_length_after": 1,
                "previous_state": "IDLE",
                "new_state": "QUEUED",
                "cycle_time_ms": None,
            },
            {
                "event_id": "EV002",
                "timestamp_ms": 10_000,
                "event_type": "PROCESSING_STARTED",
                "station_id": "S02",
                "unit_id": "U1",
                "queue_length_after": 0,
                "previous_state": "QUEUED",
                "new_state": "PROCESSING",
                "cycle_time_ms": None,
            },
            {
                "event_id": "EV003",
                "timestamp_ms": 44_000,
                "event_type": "PROCESSING_COMPLETED",
                "station_id": "S02",
                "unit_id": "U1",
                "queue_length_after": 0,
                "previous_state": "PROCESSING",
                "new_state": "IDLE",
                "cycle_time_ms": 34_000,
            },
        ]
    ).to_csv(events_csv, index=False)

    rc = app_main(
        [
            "replay",
            "--configured-stations",
            str(stations_csv),
            "--units",
            str(units_csv),
            "--events",
            str(events_csv),
            "--output-jsonl",
            str(output_jsonl),
            "--run-id",
            "CLI_TEST",
        ]
    )
    assert rc == 0
    lines = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3
    assert all(line["schema_version"] == OUTPUT_SCHEMA_VERSION for line in lines)
    assert all(line["run_id"] == "CLI_TEST" for line in lines)
    assert all(line["route"] == "LIGHT" for line in lines)


def test_bottleneck_pipeline_default_dark_seed_is_stable(tmp_path: Path) -> None:
    stations_csv, units_csv = _write_all_light_inputs(tmp_path)
    a = DigitalTwinBottleneckPipeline(
        configured_stations_csv=stations_csv, units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR, model_bundle_path=MODEL_BUNDLE, run_id="SEED_RUN"
    )
    b = DigitalTwinBottleneckPipeline(
        configured_stations_csv=stations_csv, units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR, model_bundle_path=MODEL_BUNDLE, run_id="SEED_RUN"
    )
    c = DigitalTwinBottleneckPipeline(
        configured_stations_csv=stations_csv, units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR, model_bundle_path=MODEL_BUNDLE, run_id="OTHER_RUN"
    )
    assert a.controller.random_seed == b.controller.random_seed
    assert a.controller.random_seed != c.controller.random_seed
