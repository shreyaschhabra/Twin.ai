"""Immutable factory-model registry for the defect prediction subsystem.

This mirrors ``bottlenecks_prediction.factory_models`` at the orchestration
level while keeping defect and bottleneck model selections independent.

A defect factory artifact contains only learned/contract state:
- finalized CatBoost model bundle
- finalized defect config / feature contract / threshold policy
- optional calibrator
- immutable factory.json snapshot
- immutable station-topology contract used by the model

It never contains runtime sensor/manual/station history, predictions, or the
current run being evaluated.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_ARTIFACT_ROOT = ROOT / "factory_models"
BASE_MODEL_DIR = ROOT / "saved_models"
BASE_MODEL_ID = "base"
SELECTION_FILE = "selected_model.json"
ARTIFACT_FILE = "artifact.json"
TOPOLOGY_FILE = "stations_contract.csv"
STATIC_FILE = "factory_station_contract.csv"
DZ_CONTRACT_FILE = "dz_contract.csv"
CHECKPOINT_CONTRACT_FILE = "station_checkpoints_contract.csv"


def _safe_model_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip()).strip("-_").lower()
    if not cleaned:
        raise ValueError("Factory/model id must contain a letter or number")
    if cleaned == BASE_MODEL_ID:
        raise ValueError(f"{BASE_MODEL_ID!r} is reserved for the protected initial defect model")
    return cleaned


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_root(root: str | Path = DEFAULT_ARTIFACT_ROOT) -> Path:
    path = Path(root).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _base_paths() -> dict[str, Path]:
    paths = {
        "model": BASE_MODEL_DIR / "defect_v5_models.joblib",
        "config": BASE_MODEL_DIR / "defect_v5_config.json",
        "calibrator": BASE_MODEL_DIR / "defect_v5_calibrator.joblib",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Protected initial defect model is incomplete under "
            f"{BASE_MODEL_DIR}: {', '.join(missing)}"
        )
    return {name: path.resolve() for name, path in paths.items()}


def _artifact_directory(model_id: str, root: str | Path = DEFAULT_ARTIFACT_ROOT) -> Path:
    return artifact_root(root) / _safe_model_id(model_id)


def selected_model_id(root: str | Path = DEFAULT_ARTIFACT_ROOT) -> str:
    selection = artifact_root(root) / SELECTION_FILE
    if not selection.is_file():
        return BASE_MODEL_ID
    value = str(_read_json(selection).get("model_id", BASE_MODEL_ID))
    if value == BASE_MODEL_ID:
        return BASE_MODEL_ID
    return _safe_model_id(value)


def describe_model(model_id: str, root: str | Path = DEFAULT_ARTIFACT_ROOT) -> dict[str, Any]:
    if str(model_id).strip().lower() == BASE_MODEL_ID:
        paths = _base_paths()
        return {
            "schema_version": "1.0",
            "subsystem": "defects",
            "model_id": BASE_MODEL_ID,
            "kind": "initial_base",
            "protected": True,
            "paths": {name: str(path) for name, path in paths.items()},
        }
    model_id = _safe_model_id(model_id)
    manifest = _artifact_directory(model_id, root) / ARTIFACT_FILE
    if not manifest.is_file():
        raise FileNotFoundError(f"Defect factory model artifact not found: {model_id}")
    data = _read_json(manifest)
    declared = str(data.get("model_id", ""))
    if declared != model_id:
        raise ValueError(
            f"Defect factory artifact directory/model_id mismatch: directory={model_id!r}, "
            f"manifest={declared!r}"
        )
    return data


def model_paths(model_id: str | None = None, root: str | Path = DEFAULT_ARTIFACT_ROOT) -> dict[str, Path]:
    resolved = model_id or selected_model_id(root)
    if resolved == BASE_MODEL_ID:
        return _base_paths()
    manifest = describe_model(resolved, root)
    directory = _artifact_directory(resolved, root)
    paths = {name: (directory / rel).resolve() for name, rel in manifest["paths"].items()}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Defect factory artifact {resolved!r} is incomplete: {', '.join(missing)}"
        )
    return paths


def list_models(root: str | Path = DEFAULT_ARTIFACT_ROOT) -> list[dict[str, Any]]:
    store = artifact_root(root)
    selected = selected_model_id(store)
    base = _base_paths()
    records: list[dict[str, Any]] = [{
        "id": BASE_MODEL_ID,
        "subsystem": "defects",
        "kind": "initial_base",
        "protected": True,
        "selected": selected == BASE_MODEL_ID,
        "model": str(base["model"]),
        "trained_at_utc": None,
    }]
    for directory in sorted(p for p in store.iterdir() if p.is_dir() and not p.name.startswith(".")):
        manifest = directory / ARTIFACT_FILE
        if not manifest.is_file():
            continue
        data = _read_json(manifest)
        declared = str(data.get("model_id", ""))
        if declared != directory.name:
            raise ValueError(
                f"Defect factory artifact directory/model_id mismatch: directory={directory.name!r}, "
                f"manifest={declared!r}"
            )
        records.append({
            "id": data["model_id"],
            "subsystem": "defects",
            "kind": data.get("kind", "factory_trained"),
            "protected": False,
            "selected": selected == data["model_id"],
            "model": str(directory / data["paths"]["model"]),
            "trained_at_utc": data.get("trained_at_utc"),
            "factory_id": data.get("factory", {}).get("id"),
            "run_count": data.get("training", {}).get("run_count"),
        })
    return records


def select_model(model_id: str, root: str | Path = DEFAULT_ARTIFACT_ROOT) -> dict[str, Any]:
    raw = str(model_id).strip().lower()
    resolved = BASE_MODEL_ID if raw == BASE_MODEL_ID else _safe_model_id(model_id)
    model_paths(resolved, root)  # verify before changing the pointer
    _write_json(artifact_root(root) / SELECTION_FILE, {
        "schema_version": "1.0",
        "subsystem": "defects",
        "model_id": resolved,
        "selected_at_utc": datetime.now(UTC).isoformat(),
    })
    return describe_model(resolved, root)


def delete_model(model_id: str, root: str | Path = DEFAULT_ARTIFACT_ROOT) -> None:
    if str(model_id).strip().lower() == BASE_MODEL_ID:
        raise PermissionError("The protected initial/base defect model cannot be deleted")
    resolved = _safe_model_id(model_id)
    directory = _artifact_directory(resolved, root)
    if not directory.is_dir():
        raise FileNotFoundError(f"Defect factory model artifact not found: {resolved}")
    if selected_model_id(root) == resolved:
        raise ValueError("Cannot delete the selected defect model; select another model first")
    shutil.rmtree(directory)


def _topology_frame(stations_csv: str | Path) -> pd.DataFrame:
    path = Path(stations_csv).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"stations.csv not found: {path}")
    stations = pd.read_csv(path)
    required = {"station_id", "archetype"}
    missing = required - set(stations.columns)
    if missing:
        raise ValueError("stations.csv missing topology column(s): " + ", ".join(sorted(missing)))
    out = stations[["station_id", "archetype"]].copy()
    out["station_id"] = out["station_id"].astype(str).str.strip()
    out["archetype"] = out["archetype"].astype(str).str.strip().str.upper()
    if out["station_id"].duplicated().any():
        raise ValueError("stations.csv contains duplicate station_id values")
    if not out["archetype"].eq("INSPECTION").any():
        raise ValueError("Defect runtime requires at least one INSPECTION station")
    out["station_index"] = range(len(out))
    return out



def _bool_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "true" if str(value).strip().lower() in {"1", "true", "yes", "y"} else "false"


def _factory_station_contract(factory_json: str | Path) -> pd.DataFrame:
    factory = _read_json(Path(factory_json).expanduser().resolve())
    rows = []
    for station in factory.get("stations", []):
        sid0 = int(station["id"])
        mean = float(station.get("meanCycleTimeMs", 0.0))
        cv = float(station.get("cycleTimeCV", 0.0))
        rows.append({
            "station_id": f"S{sid0 + 1:02d}",
            "archetype": str(station.get("archetype", "")).strip().upper(),
            "base_cycle_time_ms": mean,
            "cycle_time_std_ms": mean * cv,
            "buffer_capacity": int(station.get("bufferCapacity", 0)),
        })
    if not rows:
        raise ValueError("factory.json contains no stations")
    return pd.DataFrame(rows)


def _runtime_station_contract(stations_csv: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(stations_csv).copy()
    required = {
        "station_id", "archetype", "base_cycle_time_ms", "cycle_time_std_ms", "buffer_capacity"
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("stations.csv missing factory contract column(s): " + ", ".join(sorted(missing)))
    out = frame[["station_id", "archetype", "base_cycle_time_ms", "cycle_time_std_ms", "buffer_capacity"]].copy()
    out["station_id"] = out["station_id"].astype(str).str.strip()
    out["archetype"] = out["archetype"].astype(str).str.strip().str.upper()
    for col in ("base_cycle_time_ms", "cycle_time_std_ms", "buffer_capacity"):
        out[col] = pd.to_numeric(out[col], errors="raise")
    return out


def _factory_dz_contract(factory_json: str | Path) -> pd.DataFrame:
    factory = _read_json(Path(factory_json).expanduser().resolve())
    rows = []
    for zone in factory.get("darkZones", []):
        obs = zone.get("observability", {}) or {}
        rows.append({
            "dark_zone_id": str(zone.get("id", "")).strip(),
            "start_station_id": f"S{int(zone['startStationId']) + 1:02d}",
            "end_station_id": f"S{int(zone['endStationId']) + 1:02d}",
            "sensor_telemetry": _bool_text(obs.get("sensorTelemetry", False)),
            "manual_checks": _bool_text(obs.get("manualChecks", False)),
            "checkpoints": _bool_text(obs.get("checkpoints", False)),
        })
    return pd.DataFrame(rows, columns=[
        "dark_zone_id", "start_station_id", "end_station_id",
        "sensor_telemetry", "manual_checks", "checkpoints",
    ]).sort_values(["start_station_id", "end_station_id", "dark_zone_id"], kind="stable").reset_index(drop=True)


def _runtime_dz_contract(dz_csv: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(dz_csv).copy()
    required = {
        "dark_zone_id", "start_station_id", "end_station_id",
        "sensor_telemetry", "manual_checks", "checkpoints",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("dz.csv missing contract column(s): " + ", ".join(sorted(missing)))
    out = frame[list(required)].copy()
    ordered = ["dark_zone_id", "start_station_id", "end_station_id", "sensor_telemetry", "manual_checks", "checkpoints"]
    out = out[ordered]
    for col in ("dark_zone_id", "start_station_id", "end_station_id"):
        out[col] = out[col].astype(str).str.strip()
    for col in ("sensor_telemetry", "manual_checks", "checkpoints"):
        out[col] = out[col].map(_bool_text)
    return out.sort_values(["start_station_id", "end_station_id", "dark_zone_id"], kind="stable").reset_index(drop=True)


def _factory_checkpoint_contract(factory_json: str | Path) -> pd.DataFrame:
    factory = _read_json(Path(factory_json).expanduser().resolve())
    rows = []
    for cp in factory.get("checkpoints", []):
        rows.append({
            "station_id": f"S{int(cp['stationId']) + 1:02d}",
            "checkpoint_id": str(cp.get("id", "")).strip(),
            "checkpoint_type": str(cp.get("type", "")).strip().upper(),
            "nominal_progress_fraction": float(cp.get("progress", 0.5)),
            "read_reliability": float(cp.get("reliability", 1.0)),
            "false_positive_rate": float(cp.get("falsePositiveRate", 0.0)),
            "identifies_unit": _bool_text(cp.get("identifiesUnit", True)),
        })
    cols = ["station_id", "checkpoint_id", "checkpoint_type", "nominal_progress_fraction", "read_reliability", "false_positive_rate", "identifies_unit"]
    return pd.DataFrame(rows, columns=cols).sort_values(["station_id", "checkpoint_id"], kind="stable").reset_index(drop=True)


def _runtime_checkpoint_contract(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path).copy()
    cols = ["station_id", "checkpoint_id", "checkpoint_type", "nominal_progress_fraction", "read_reliability", "false_positive_rate", "identifies_unit"]
    missing = set(cols) - set(frame.columns)
    if missing:
        raise ValueError(
            "station_checkpoints.csv is incompatible with factory defect artifacts; missing: "
            + ", ".join(sorted(missing))
            + ". Regenerate the run with the streamlined simulator."
        )
    out = frame[cols].copy()
    for col in ("station_id", "checkpoint_id", "checkpoint_type"):
        out[col] = out[col].astype(str).str.strip()
    out["checkpoint_type"] = out["checkpoint_type"].str.upper()
    for col in ("nominal_progress_fraction", "read_reliability", "false_positive_rate"):
        out[col] = pd.to_numeric(out[col], errors="raise")
    out["identifies_unit"] = out["identifies_unit"].map(_bool_text)
    return out.sort_values(["station_id", "checkpoint_id"], kind="stable").reset_index(drop=True)


def _frames_equal(expected: pd.DataFrame, actual: pd.DataFrame, *, numeric: set[str] | None = None) -> bool:
    if list(expected.columns) != list(actual.columns) or len(expected) != len(actual):
        return False
    numeric = numeric or set()
    for col in expected.columns:
        if col in numeric:
            left = pd.to_numeric(expected[col], errors="coerce").to_numpy(dtype=float)
            right = pd.to_numeric(actual[col], errors="coerce").to_numpy(dtype=float)
            if not bool(__import__("numpy").allclose(left, right, rtol=1e-9, atol=1e-6, equal_nan=True)):
                return False
        elif expected[col].astype(str).tolist() != actual[col].astype(str).tolist():
            return False
    return True


def validate_factory_run_contract(factory_json: str | Path, run_dir: str | Path) -> None:
    run = Path(run_dir).expanduser().resolve()
    expected_st = _factory_station_contract(factory_json)
    actual_st = _runtime_station_contract(run / "stations.csv")
    if not _frames_equal(expected_st, actual_st, numeric={"base_cycle_time_ms", "cycle_time_std_ms", "buffer_capacity"}):
        raise ValueError(f"{run.name}: station configuration does not match the target factory.json")
    expected_dz, actual_dz = _factory_dz_contract(factory_json), _runtime_dz_contract(run / "dz.csv")
    if not _frames_equal(expected_dz, actual_dz):
        raise ValueError(f"{run.name}: DARK-zone/observability contract does not match the target factory.json")
    expected_cp = _factory_checkpoint_contract(factory_json)
    actual_cp = _runtime_checkpoint_contract(run / "station_checkpoints.csv")
    if not _frames_equal(expected_cp, actual_cp, numeric={"nominal_progress_fraction", "read_reliability", "false_positive_rate"}):
        raise ValueError(f"{run.name}: checkpoint contract does not match the target factory.json")


def validate_runtime_factory_contract(paths: dict[str, Path], run_dir: str | Path) -> None:
    run = Path(run_dir).expanduser().resolve()
    validate_runtime_topology_match(paths["stations_contract"], run / "stations.csv")
    if "factory_station_contract" in paths:
        expected = pd.read_csv(paths["factory_station_contract"])
        actual = _runtime_station_contract(run / "stations.csv")
        if not _frames_equal(expected, actual, numeric={"base_cycle_time_ms", "cycle_time_std_ms", "buffer_capacity"}):
            raise ValueError("Runtime station configuration does not match the selected defect factory model")
    if "dz_contract" in paths:
        # Re-normalize both the immutable artifact and the runtime CSV. Pandas may
        # infer literal true/false columns as bool when the artifact is reloaded;
        # comparing that directly with canonical lower-case strings would reject
        # an otherwise identical factory contract.
        expected = _runtime_dz_contract(paths["dz_contract"])
        actual = _runtime_dz_contract(run / "dz.csv")
        if not _frames_equal(expected, actual):
            raise ValueError("Runtime DARK-zone observability does not match the selected defect factory model")
    if "checkpoint_contract" in paths:
        expected = _runtime_checkpoint_contract(paths["checkpoint_contract"])
        actual = _runtime_checkpoint_contract(run / "station_checkpoints.csv")
        if not _frames_equal(expected, actual, numeric={"nominal_progress_fraction", "read_reliability", "false_positive_rate"}):
            raise ValueError("Runtime checkpoint contract does not match the selected defect factory model")

def validate_runtime_topology_match(contract_csv: str | Path, runtime_stations_csv: str | Path) -> None:
    expected = _topology_frame(contract_csv)
    actual = _topology_frame(runtime_stations_csv)
    cols = ["station_id", "archetype", "station_index"]
    if expected[cols].to_dict("records") != actual[cols].to_dict("records"):
        raise ValueError(
            "Runtime station topology does not match the selected defect factory model. "
            "Station order/IDs/archetypes (including final inspection position) must match the training artifact."
        )


def publish_factory_model(
    *,
    model_id: str,
    factory_json: str | Path,
    stations_csv: str | Path,
    model_artifact_path: str | Path,
    config_path: str | Path,
    calibrator_path: str | Path,
    historical_dwell_path: str | Path | None = None,
    corridor_residence_path: str | Path | None = None,
    root: str | Path = DEFAULT_ARTIFACT_ROOT,
    factory_id: str | None = None,
    training_summary: dict[str, Any] | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Publish one immutable defect factory artifact atomically.

    Training is intentionally separate. Part 1 provides the same artifact and
    model-selection contract as bottlenecks; the factory-training pipeline will
    call this function in the later training part.
    """
    resolved = _safe_model_id(model_id)
    store = artifact_root(root)
    target = store / resolved
    if target.exists() and not replace:
        raise FileExistsError(f"Defect factory model already exists: {resolved}")
    if target.exists() and selected_model_id(store) == resolved:
        raise ValueError("Cannot replace the currently selected defect model; select another model first")

    factory = Path(factory_json).expanduser().resolve()
    model = Path(model_artifact_path).expanduser().resolve()
    config = Path(config_path).expanduser().resolve()
    calibrator = Path(calibrator_path).expanduser().resolve()
    historical_dwell = (Path(historical_dwell_path).expanduser().resolve() if historical_dwell_path is not None else None)
    corridor_residence = (Path(corridor_residence_path).expanduser().resolve() if corridor_residence_path is not None else None)
    missing = [str(p) for p in (factory, model, config, calibrator) if not p.is_file()]
    if historical_dwell is not None and not historical_dwell.is_file():
        missing.append(str(historical_dwell))
    if corridor_residence is not None and not corridor_residence.is_file():
        missing.append(str(corridor_residence))
    if missing:
        raise FileNotFoundError("Cannot publish defect artifact; missing: " + ", ".join(missing))

    topology = _topology_frame(stations_csv)
    tmp = store / f".{resolved}.tmp-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(model, tmp / "defect_models.joblib")
        shutil.copy2(config, tmp / "defect_config.json")
        shutil.copy2(calibrator, tmp / "defect_calibrator.joblib")
        shutil.copy2(factory, tmp / "factory.json")
        topology.to_csv(tmp / TOPOLOGY_FILE, index=False)
        _factory_station_contract(factory).to_csv(tmp / STATIC_FILE, index=False)
        _factory_dz_contract(factory).to_csv(tmp / DZ_CONTRACT_FILE, index=False)
        _factory_checkpoint_contract(factory).to_csv(tmp / CHECKPOINT_CONTRACT_FILE, index=False)
        if historical_dwell is not None:
            shutil.copy2(historical_dwell, tmp / "historical_dwell.csv")
        if corridor_residence is not None:
            shutil.copy2(corridor_residence, tmp / "corridor_residence_calibration.csv")

        cfg = _read_json(tmp / "defect_config.json")
        manifest = {
            "schema_version": "1.0",
            "subsystem": "defects",
            "model_id": resolved,
            "kind": "factory_trained",
            "protected": False,
            "trained_at_utc": datetime.now(UTC).isoformat(),
            "factory": {
                "id": factory_id,
                "factory_sha256": _sha256(tmp / "factory.json"),
                "station_count": int(len(topology)),
                "final_inspection_station": str(
                    topology.loc[topology["archetype"].eq("INSPECTION"), "station_id"].iloc[-1]
                ),
            },
            "contract": {
                "feature_count": int(cfg.get("feature_count", 30)),
                "features": list(cfg.get("features", [])),
                "categorical_features": list(cfg.get("categorical_features", [])),
                "prediction_trigger": "LIGHT UNIT_ARRIVED or causal DARK inferred station entry",
                "feature_source": "deployment public bus replay",
                "inspection_role": "label_only",
                "target": "future final-inspection FAIL",
            },
            "training": dict(training_summary or {}),
            "paths": {
                "model": "defect_models.joblib",
                "config": "defect_config.json",
                "calibrator": "defect_calibrator.joblib",
                "factory_json": "factory.json",
                "stations_contract": TOPOLOGY_FILE,
                "factory_station_contract": STATIC_FILE,
                "dz_contract": DZ_CONTRACT_FILE,
                "checkpoint_contract": CHECKPOINT_CONTRACT_FILE,
                **({"historical_dwell": "historical_dwell.csv"} if historical_dwell is not None else {}),
                **({"corridor_residence": "corridor_residence_calibration.csv"} if corridor_residence is not None else {}),
            },
            "hashes": {
                "model": _sha256(tmp / "defect_models.joblib"),
                "config": _sha256(tmp / "defect_config.json"),
                "calibrator": _sha256(tmp / "defect_calibrator.joblib"),
                "stations_contract": _sha256(tmp / TOPOLOGY_FILE),
                "factory_station_contract": _sha256(tmp / STATIC_FILE),
                "dz_contract": _sha256(tmp / DZ_CONTRACT_FILE),
                "checkpoint_contract": _sha256(tmp / CHECKPOINT_CONTRACT_FILE),
                **({"historical_dwell": _sha256(tmp / "historical_dwell.csv")} if historical_dwell is not None else {}),
                **({"corridor_residence": _sha256(tmp / "corridor_residence_calibration.csv")} if corridor_residence is not None else {}),
            },
        }
        _write_json(tmp / ARTIFACT_FILE, manifest)
        if target.exists():
            shutil.rmtree(target)
        tmp.rename(target)
        return _read_json(target / ARTIFACT_FILE)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise



def train_factory_model(
    *,
    model_id: str,
    factory_json: str | Path,
    runs_root: str | Path,
    root: str | Path = DEFAULT_ARTIFACT_ROOT,
    factory_id: str | None = None,
    validation_fraction: float = 0.25,
    seed: int = 42,
    corridor_particles: int = 3000,
    continuation_iterations: int = 100,
    replace: bool = False,
    progress=None,
) -> Path:
    """Train and publish one immutable factory-specific V5 defect artifact.

    X is materialized by replaying the exact deployment public-bus feature path.
    Inspection outcomes are label-only.  DARK calibration never uses the current
    run and validation reconstruction uses training runs only.
    """
    from .training.public_dataset import discover_completed_runs, materialize_factory_dataset
    from .training.train_factory_catboost import train_factory_catboost

    resolved = _safe_model_id(model_id)
    store = artifact_root(root)
    target = store / resolved
    if target.exists() and not replace:
        raise FileExistsError(f"Defect factory model already exists: {resolved}")
    if target.exists() and selected_model_id(store) == resolved:
        raise ValueError("Cannot replace the currently selected defect model")

    factory = Path(factory_json).expanduser().resolve()
    if not factory.is_file():
        raise FileNotFoundError(f"Factory JSON not found: {factory}")
    runs = discover_completed_runs(runs_root)
    for run in runs:
        validate_factory_run_contract(factory, run)

    staging = store / f".{resolved}.training-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        if progress:
            progress(f"Defect training {resolved}: replaying {len(runs)} completed public simulator run(s)...")
        derived = staging / "derived"
        report = materialize_factory_dataset(
            runs_root,
            derived,
            dark_zone_dir=ROOT.parent / "bottlenecks_prediction" / "dark_zone",
            validation_fraction=validation_fraction,
            seed=seed,
            corridor_particles=corridor_particles,
        )
        # Deployment DARK calibration is bundled with the selected factory artifact
        # and is built from TRAIN runs only. Validation runs never influence this
        # state, matching the bottleneck factory-artifact boundary.
        from bottlenecks_prediction.factory_models import (
            build_dark_calibration_files as build_shared_dark_calibration,
            configure_factory as configure_shared_factory,
        )
        configured = staging / "configured_stations.csv"
        configure_shared_factory(factory, runs[0] / "stations.csv", configured)
        dark_ids: set[str] = set()
        for row in _factory_dz_contract(factory).to_dict(orient="records"):
            lo = int(str(row["start_station_id"])[1:])
            hi = int(str(row["end_station_id"])[1:])
            dark_ids.update(f"S{i:02d}" for i in range(min(lo, hi), max(lo, hi) + 1))
        training_runs_by_name = {r.name: r for r in runs}
        artifact_train_runs = [training_runs_by_name[name] for name in report["train_runs"]]
        dwell = residence = None
        calibration_meta: dict[str, Any] = {
            "history_run_ids": report["train_runs"],
            "validation_runs_excluded": True,
            "current_run_excluded": True,
        }
        if dark_ids:
            if progress:
                progress("Defect training: building immutable DARK calibration from TRAIN runs only...")
            dwell, residence, shared_meta = build_shared_dark_calibration(
                artifact_train_runs, configured, staging / "calibration",
                dark_station_ids=dark_ids,
            )
            if dwell is None:
                raise RuntimeError("Factory training runs did not produce DARK calibration")
            calibration_meta.update(shared_meta)

        if progress:
            progress("Defect training: continuing the protected V5 CatBoost model...")
        model_out = staging / "model"
        base = _base_paths()
        metrics = train_factory_catboost(
            derived,
            model_out,
            base_model_artifact=base["model"],
            base_config=base["config"],
            seed=seed,
            continuation_iterations=continuation_iterations,
        )
        training_summary = {
            "run_count": len(runs),
            "run_ids": [r.name for r in runs],
            "train_run_ids": report["train_runs"],
            "validation_run_ids": report["validation_runs"],
            "train_rows": report["train_rows"],
            "validation_rows": report["validation_rows"],
            "feature_source": "deployment_public_bus_replay",
            "inspection_role": "label_only",
            "same_run_dark_calibration": False,
            "validation_uses_training_calibration_only": True,
            "seed": seed,
            "validation_fraction": validation_fraction,
            "corridor_particles": corridor_particles,
            "metrics": metrics,
            "dark_calibration": calibration_meta,
            "base_model_sha256": _sha256(base["model"]),
            "base_config_sha256": _sha256(base["config"]),
        }
        manifest = publish_factory_model(
            model_id=resolved,
            factory_json=factory,
            stations_csv=runs[0] / "stations.csv",
            model_artifact_path=model_out / "defect_v5_models.joblib",
            config_path=model_out / "defect_v5_config.json",
            calibrator_path=model_out / "defect_v5_calibrator.joblib",
            historical_dwell_path=dwell,
            corridor_residence_path=residence,
            root=store,
            factory_id=factory_id,
            training_summary=training_summary,
            replace=replace,
        )
        if progress:
            progress(f"Defect factory training complete: {target}")
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)
