from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory_models import (
    BASE_MODEL_ID,
    ARTIFACT_FILE,
    delete_model,
    list_models,
    model_paths,
    select_model,
    selected_model_id,
)


def test_zero_dark_factory_skips_calibration(tmp_path: Path) -> None:
    """A LIGHT-only factory must not need, import, or emit DARK calibration."""
    from factory_models import _build_dark_calibration

    configured = tmp_path / "configured_stations.csv"
    configured.write_text("station_id,sensor_coverage\nS01,HIGH\n", encoding="utf-8")

    calibration = _build_dark_calibration(
        [], configured, tmp_path / "calibration", dark_station_ids=set()
    )

    assert calibration["dark_station_ids"] == []
    assert calibration["dwell"] is None
    assert calibration["corridor_residence"] is None
    assert not (tmp_path / "calibration").exists()


def _factory_artifact(root: Path, model_id: str) -> Path:
    directory = root / model_id
    (directory / "model").mkdir(parents=True)
    (directory / "calibration").mkdir()
    for relative in (
        "model/bottleneck_model_bundle.joblib",
        "model/bottleneck_xgboost.json",
        "configured_stations.csv",
        "calibration/historical_dwell.csv",
    ):
        (directory / relative).write_text("test", encoding="utf-8")
    (directory / ARTIFACT_FILE).write_text(
        json.dumps(
            {
                "model_id": model_id,
                "paths": {
                    "model_bundle": "model/bottleneck_model_bundle.joblib",
                    "xgboost_model": "model/bottleneck_xgboost.json",
                    "configured_stations": "configured_stations.csv",
                    "historical_dwell": "calibration/historical_dwell.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_registry_switches_artifacts_without_mutating_them(tmp_path: Path) -> None:
    first = _factory_artifact(tmp_path, "factory-a")
    second = _factory_artifact(tmp_path, "factory-b")
    before_first = (first / ARTIFACT_FILE).read_bytes()
    before_second = (second / ARTIFACT_FILE).read_bytes()

    assert selected_model_id(tmp_path) == BASE_MODEL_ID
    select_model("factory-a", tmp_path)
    assert selected_model_id(tmp_path) == "factory-a"
    first_paths = model_paths(None, tmp_path)
    select_model("factory-b", tmp_path)
    second_paths = model_paths(None, tmp_path)

    assert first_paths["model_bundle"] != second_paths["model_bundle"]
    assert (first / ARTIFACT_FILE).read_bytes() == before_first
    assert (second / ARTIFACT_FILE).read_bytes() == before_second
    assert {item["id"] for item in list_models(tmp_path)} >= {BASE_MODEL_ID, "factory-a", "factory-b"}


def test_registry_protects_base_and_selected_artifact(tmp_path: Path) -> None:
    _factory_artifact(tmp_path, "factory-a")
    with pytest.raises(PermissionError):
        delete_model(BASE_MODEL_ID, tmp_path)

    select_model("factory-a", tmp_path)
    with pytest.raises(ValueError, match="selected"):
        delete_model("factory-a", tmp_path)

    select_model(BASE_MODEL_ID, tmp_path)
    delete_model("factory-a", tmp_path)
    assert not (tmp_path / "factory-a").exists()


def test_base_model_is_a_runnable_runtime_choice(tmp_path: Path) -> None:
    """Selecting BASE must no longer be rejected by the repository CLI runtime."""
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from cli import _model_runtime_args

    run = tmp_path / "run_0001"
    run.mkdir()
    stations = run / "stations.csv"
    stations.write_text(
        "station_id,archetype,base_cycle_time_ms,cycle_time_std_ms,buffer_capacity,sensor_coverage\n"
        "S01,AUTOMATED,60000,6000,0,HIGH\n"
        "S02,AUTOMATED,60000,6000,4,HIGH\n",
        encoding="utf-8",
    )
    (run / "dz.csv").write_text(
        "dark_zone_id,name,start_station_id,end_station_id,sensor_telemetry,manual_checks,checkpoints\n",
        encoding="utf-8",
    )

    args = _model_runtime_args(BASE_MODEL_ID, tmp_path, run)
    assert args[0] == "--configured-stations"
    configured = Path(args[1])
    assert configured.is_file()
    assert args[2] == "--model-bundle"
    assert args[3].endswith("bottleneck_model_bundle.joblib")


def test_run_current_respects_selected_factory_model(tmp_path: Path) -> None:
    import pandas as pd
    import sys

    repo_package = Path(__file__).resolve().parents[1]
    if str(repo_package) not in sys.path:
        sys.path.insert(0, str(repo_package))
    from run_current import _resolve_runtime_contract

    artifact = tmp_path / "factory-a"
    (artifact / "model").mkdir(parents=True)
    (artifact / "calibration").mkdir()
    (artifact / "model" / "bottleneck_model_bundle.joblib").write_text("bundle", encoding="utf-8")
    (artifact / "model" / "bottleneck_xgboost.json").write_text("model", encoding="utf-8")
    (artifact / "calibration" / "historical_dwell.csv").write_text("station_id,variant,entry_ts,exit_ts\n", encoding="utf-8")

    configured = pd.DataFrame([
        {"station_id":"S01","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":0,"sensor_coverage":"NORMAL"},
        {"station_id":"S02","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NONE"},
        {"station_id":"S03","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
    ])
    configured.to_csv(artifact / "configured_stations.csv", index=False)
    (artifact / ARTIFACT_FILE).write_text(json.dumps({
        "model_id": "factory-a",
        "paths": {
            "model_bundle": "model/bottleneck_model_bundle.joblib",
            "xgboost_model": "model/bottleneck_xgboost.json",
            "configured_stations": "configured_stations.csv",
            "historical_dwell": "calibration/historical_dwell.csv",
        },
    }), encoding="utf-8")
    select_model("factory-a", tmp_path)

    run = tmp_path / "run"
    run.mkdir()
    raw = configured.copy()
    raw["sensor_coverage"] = ["HIGH", "PARTIAL", "HIGH"]
    raw.to_csv(run / "stations.csv", index=False)
    pd.DataFrame([{
        "dark_zone_id":"DZ1", "start_station_id":"S02", "end_station_id":"S02"
    }]).to_csv(run / "dz.csv", index=False)

    contract = _resolve_runtime_contract(
        {"stations.csv": run / "stations.csv", "dz.csv": run / "dz.csv"},
        model_id=None,
        artifact_root=tmp_path,
    )
    assert contract["model_id"] == "factory-a"
    assert contract["model_bundle"] == (artifact / "model" / "bottleneck_model_bundle.joblib").resolve()
    assert contract["historical_dwell"] == (artifact / "calibration" / "historical_dwell.csv").resolve()
    assert contract["dark_stations"] == ["S02"]


def test_registry_rejects_renamed_or_mismatched_artifact(tmp_path: Path) -> None:
    directory = _factory_artifact(tmp_path, "factory-a")
    manifest = json.loads((directory / ARTIFACT_FILE).read_text(encoding="utf-8"))
    manifest["model_id"] = "factory-b"
    (directory / ARTIFACT_FILE).write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="directory/model_id mismatch"):
        model_paths("factory-a", tmp_path)
    with pytest.raises(ValueError, match="directory/model_id mismatch"):
        list_models(tmp_path)
