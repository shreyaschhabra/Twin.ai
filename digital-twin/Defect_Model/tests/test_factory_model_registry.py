from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from Defect_Model.factory_models import (
    BASE_MODEL_ID,
    BASE_MODEL_DIR,
    list_models,
    model_paths,
    publish_factory_model,
    select_model,
    selected_model_id,
    validate_runtime_topology_match,
)


def _stations(path: Path, *, mismatch: bool = False) -> Path:
    frame = pd.DataFrame([
        {"station_id": "S01", "archetype": "AUTOMATED"},
        {"station_id": "S02", "archetype": "AUTOMATED" if mismatch else "MANUAL"},
        {"station_id": "S03", "archetype": "INSPECTION"},
    ])
    frame.to_csv(path, index=False)
    return path


def test_base_model_is_protected_and_default(tmp_path: Path):
    assert selected_model_id(tmp_path) == BASE_MODEL_ID
    paths = model_paths(BASE_MODEL_ID, tmp_path)
    assert paths["model"].is_file()
    rows = list_models(tmp_path)
    assert rows[0]["id"] == BASE_MODEL_ID
    assert rows[0]["protected"] is True
    assert rows[0]["selected"] is True


def test_publish_select_and_validate_factory_artifact(tmp_path: Path):
    factory = tmp_path / "factory.json"
    factory.write_text(json.dumps({"stations": [{"id": 0}], "darkZones": [], "checkpoints": []}), encoding="utf-8")
    stations = _stations(tmp_path / "stations.csv")
    artifact_root = tmp_path / "artifacts"

    manifest = publish_factory_model(
        model_id="Factory-A",
        factory_json=factory,
        stations_csv=stations,
        model_artifact_path=BASE_MODEL_DIR / "defect_v5_models.joblib",
        config_path=BASE_MODEL_DIR / "defect_v5_config.json",
        calibrator_path=BASE_MODEL_DIR / "defect_v5_calibrator.joblib",
        root=artifact_root,
        factory_id="plant-a",
        training_summary={"run_count": 12},
    )
    assert manifest["model_id"] == "factory-a"
    assert manifest["factory"]["final_inspection_station"] == "S03"

    select_model("factory-a", artifact_root)
    assert selected_model_id(artifact_root) == "factory-a"
    paths = model_paths(None, artifact_root)
    assert paths["model"].is_file()
    assert paths["stations_contract"].is_file()
    validate_runtime_topology_match(paths["stations_contract"], stations)


def test_factory_artifact_rejects_runtime_topology_drift(tmp_path: Path):
    expected = _stations(tmp_path / "expected.csv")
    actual = _stations(tmp_path / "actual.csv", mismatch=True)
    with pytest.raises(ValueError, match="does not match"):
        validate_runtime_topology_match(expected, actual)


def test_registry_rejects_renamed_or_mismatched_artifact(tmp_path: Path):
    factory = tmp_path / "factory.json"
    factory.write_text(json.dumps({"stations": [{"id": 0}], "darkZones": [], "checkpoints": []}), encoding="utf-8")
    stations = _stations(tmp_path / "stations.csv")
    artifact_root = tmp_path / "artifacts"
    publish_factory_model(
        model_id="factory-a",
        factory_json=factory,
        stations_csv=stations,
        model_artifact_path=BASE_MODEL_DIR / "defect_v5_models.joblib",
        config_path=BASE_MODEL_DIR / "defect_v5_config.json",
        calibrator_path=BASE_MODEL_DIR / "defect_v5_calibrator.joblib",
        root=artifact_root,
    )
    manifest_path = artifact_root / "factory-a" / "artifact.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model_id"] = "factory-b"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="directory/model_id mismatch"):
        model_paths("factory-a", artifact_root)
    with pytest.raises(ValueError, match="directory/model_id mismatch"):
        list_models(artifact_root)
