"""Materialize defect training rows by replaying the deployment public bus.

This is the training-time mirror of ``run_current_defects.py``.  Feature X is
constructed solely from runtime-observable STATION/SENSOR/MANUAL/EVIDENCE
records.  ``inspection_results.csv`` is opened only after feature packets are
materialized and is used only to attach the future final-inspection label Y.

For DARK runs, a training run never calibrates its own particle filter:
- each training run uses the other training runs as historical calibration;
- each validation run uses training runs only.
This preserves current-run causality and train/validation isolation.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..runtime.dark_zone_adapter import DefectDarkZoneAdapter
from ..runtime.defect_pipeline import DigitalTwinDefectPipeline
from ..runtime.public_bus import (
    REQUIRED_BUS_COLUMNS,
    checkpoint_progress_map,
    runtime_row_to_record,
)
from ..src.feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES, TARGET_COLUMN

REQUIRED_RUN_FILES = (
    "stations.csv",
    "units.csv",
    "station_events.csv",
    "runtime_events.csv",
    "sensor_readings.csv",
    "manual_checks.csv",
    "inspection_results.csv",
    "dz.csv",
    "station_checkpoints.csv",
    "run_metadata.json",
)

META_COLUMNS = [
    "split",
    "run_id",
    "unit_id",
    "prediction_station",
    "prediction_time",
    "prediction_event_sequence",
    "label_completeness_status",
    "final_station_index",
    "route",
    "prediction_trigger",
    "state_confidence",
    "data_source",
]


def discover_completed_runs(root: str | Path) -> list[Path]:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"Factory training runs directory not found: {base}")
    runs: list[Path] = []
    for child in sorted(p for p in base.iterdir() if p.is_dir()):
        missing = [name for name in REQUIRED_RUN_FILES if not (child / name).is_file()]
        if not missing:
            runs.append(child.resolve())
    if not runs:
        raise FileNotFoundError(
            f"No completed simulator-v2.1 defect-training runs found under {base}"
        )
    return runs


def split_runs(
    runs: Iterable[Path], *, validation_fraction: float = 0.25, seed: int = 42
) -> tuple[list[Path], list[Path]]:
    values = sorted(Path(p).resolve() for p in runs)
    if len(values) < 2:
        raise ValueError("Factory defect training requires at least two completed runs")
    fraction = float(validation_fraction)
    if not (0.0 < fraction < 1.0):
        raise ValueError("validation_fraction must be strictly between 0 and 1")
    rng = np.random.default_rng(int(seed))
    order = rng.permutation(len(values))
    n_val = max(1, int(round(len(values) * fraction)))
    n_val = min(n_val, len(values) - 1)
    val_idx = set(map(int, order[:n_val]))
    train = [p for i, p in enumerate(values) if i not in val_idx]
    validation = [p for i, p in enumerate(values) if i in val_idx]
    return train, validation


def _final_station(stations_csv: Path) -> tuple[str, int]:
    stations = pd.read_csv(stations_csv).copy()
    if "archetype" not in stations.columns or "station_id" not in stations.columns:
        raise ValueError(f"{stations_csv}: missing station_id/archetype")
    stations["station_id"] = stations["station_id"].astype(str)
    inspection = stations[
        stations["archetype"].astype(str).str.strip().str.upper().eq("INSPECTION")
    ].copy()
    if inspection.empty:
        raise ValueError(f"{stations_csv}: no INSPECTION station")
    order = {sid: i for i, sid in enumerate(stations["station_id"].tolist())}
    inspection["_index"] = inspection["station_id"].map(order)
    row = inspection.sort_values("_index").iloc[-1]
    return str(row["station_id"]), int(row["_index"])


def _qa_index(path: Path, final_station: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    qa = pd.read_csv(path).copy()
    required = {"timestamp_ms", "station_id", "unit_id", "result"}
    missing = required - set(qa.columns)
    if missing:
        raise ValueError(f"{path}: missing inspection columns {sorted(missing)}")
    qa["timestamp_ms"] = pd.to_numeric(qa["timestamp_ms"], errors="coerce")
    qa["station_id"] = qa["station_id"].astype(str)
    qa["unit_id"] = qa["unit_id"].astype(str)
    qa["result"] = qa["result"].astype(str).str.strip().str.upper()
    qa = qa[
        qa["station_id"].eq(str(final_station))
        & qa["result"].isin(["PASS", "FAIL"])
        & qa["timestamp_ms"].notna()
    ]
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for uid, group in qa.groupby("unit_id", sort=False):
        group = group.sort_values("timestamp_ms", kind="stable")
        times = group["timestamp_ms"].to_numpy(dtype=np.int64)
        fails = group["result"].eq("FAIL").to_numpy(dtype=bool)
        future_fail = np.maximum.accumulate(fails[::-1])[::-1]
        out[str(uid)] = times, future_fail
    return out


def _label_packet(
    packet, qa: dict[str, tuple[np.ndarray, np.ndarray]]
) -> tuple[float, str]:
    item = qa.get(str(packet.unit_id))
    if item is None:
        return np.nan, "censored"
    times, future_fail = item
    j = int(np.searchsorted(times, int(packet.prediction_time_ms), side="right"))
    if j >= len(times):
        return np.nan, "censored"
    return float(bool(future_fail[j])), "complete"


def replay_run_features(
    run_dir: str | Path,
    *,
    split: str,
    history_runs: Iterable[str | Path],
    dark_zone_dir: str | Path,
    corridor_particles: int = 3000,
    random_seed: int | None = None,
    transition_confidence: float = 0.55,
    sensor_assignment_confidence: float = 0.55,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    run = Path(run_dir).expanduser().resolve()
    missing = [name for name in REQUIRED_RUN_FILES if not (run / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{run.name}: missing training-run files: {', '.join(missing)}")

    final_station, final_station_index = _final_station(run / "stations.csv")
    history = [Path(p).expanduser().resolve() for p in history_runs]
    if run in history:
        raise ValueError(f"{run.name}: current run cannot appear in its own DARK calibration history")

    dark_adapter = DefectDarkZoneAdapter(
        stations_csv=run / "stations.csv",
        dz_csv=run / "dz.csv",
        units_csv=run / "units.csv",
        history_runs=history,
        runtime_dir=run.parent / ".defect_training_runtime" / run.name,
        dark_zone_dir=dark_zone_dir,
        run_id=run.name,
        corridor_particles=int(corridor_particles),
        random_seed=random_seed,
        transition_confidence=float(transition_confidence),
        sensor_assignment_confidence=float(sensor_assignment_confidence),
    )
    pipeline = DigitalTwinDefectPipeline(
        stations_csv=run / "stations.csv",
        units_csv=run / "units.csv",
        run_id=run.name,
        dark_adapter=dark_adapter,
    )
    progress = checkpoint_progress_map(run / "station_checkpoints.csv")

    packets = []
    bus_records = 0
    expected_sequence = 1
    with (run / "runtime_events.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or [])
        missing_bus = REQUIRED_BUS_COLUMNS - header
        if missing_bus:
            raise ValueError(
                f"{run.name}/runtime_events.csv missing: {', '.join(sorted(missing_bus))}"
            )
        for row in reader:
            seq = int(row["sequence"])
            if seq != expected_sequence:
                raise ValueError(
                    f"{run.name}: runtime bus sequence gap/reorder: expected {expected_sequence}, got {seq}"
                )
            expected_sequence += 1
            record = runtime_row_to_record(row, progress)
            bus_records += 1
            if record is not None:
                packets.extend(pipeline.process_record_packets(record))

    qa = _qa_index(run / "inspection_results.csv", final_station)
    rows: list[dict[str, Any]] = []
    for packet in packets:
        y, completeness = _label_packet(packet, qa)
        row = {
            "split": str(split),
            "run_id": run.name,
            "unit_id": packet.unit_id,
            "prediction_station": packet.station_id,
            "prediction_time": int(packet.prediction_time_ms),
            "prediction_event_sequence": packet.event_sequence,
            "label_completeness_status": completeness,
            "final_station_index": int(final_station_index),
            "route": packet.route,
            "prediction_trigger": packet.prediction_trigger,
            "state_confidence": float(packet.state_confidence),
            "data_source": packet.data_source,
            **packet.features_30,
            TARGET_COLUMN: y,
        }
        rows.append(row)

    columns = META_COLUMNS + list(DEFECT_FEATURES) + [TARGET_COLUMN]
    frame = pd.DataFrame(rows, columns=columns)
    complete = frame[TARGET_COLUMN].notna() if not frame.empty else pd.Series([], dtype=bool)
    labelled = frame.loc[complete].copy()
    report = {
        "run_id": run.name,
        "split": str(split),
        "bus_records": int(bus_records),
        "prediction_packets": int(len(frame)),
        "labelled_rows": int(len(labelled)),
        "censored_rows": int(len(frame) - len(labelled)),
        "positive_rows": int((labelled[TARGET_COLUMN] == 1).sum()) if not labelled.empty else 0,
        "routes": frame["route"].value_counts().to_dict() if not frame.empty else {},
        "feature_count": len(DEFECT_FEATURES),
        "final_inspection_station": final_station,
        "calibration_history_runs": list(dark_adapter.calibration_manifest.get("history_runs", [])),
        "current_run_excluded_from_calibration": bool(
            dark_adapter.calibration_manifest.get("current_run_excluded", True)
        ),
        "dark_adapter": dark_adapter.diagnostics(),
        "feature_builder": pipeline.features.diagnostics(),
    }
    return labelled.reset_index(drop=True), report


def materialize_factory_dataset(
    runs_root: str | Path,
    output_dir: str | Path,
    *,
    dark_zone_dir: str | Path,
    validation_fraction: float = 0.25,
    seed: int = 42,
    corridor_particles: int = 3000,
    transition_confidence: float = 0.55,
    sensor_assignment_confidence: float = 0.55,
) -> dict[str, Any]:
    runs = discover_completed_runs(runs_root)
    train_runs, validation_runs = split_runs(
        runs, validation_fraction=validation_fraction, seed=seed
    )

    # DARK feature reconstruction for a training run uses other TRAIN runs only.
    # If a factory has DARK zones, at least two training runs are necessary so
    # no run ever calibrates its own PF.
    first_dz = pd.read_csv(train_runs[0] / "dz.csv")
    has_dark = not first_dz.empty
    if has_dark and len(train_runs) < 2:
        raise ValueError(
            "DARK factory training requires at least two training runs after the validation split "
            "so each run can be reconstructed from other prior/history runs only"
        )

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    frames = {"train": [], "validation": []}
    reports: list[dict[str, Any]] = []

    for run in train_runs:
        history = [other for other in train_runs if other != run]
        frame, report = replay_run_features(
            run,
            split="train",
            history_runs=history,
            dark_zone_dir=dark_zone_dir,
            corridor_particles=corridor_particles,
            random_seed=seed,
            transition_confidence=transition_confidence,
            sensor_assignment_confidence=sensor_assignment_confidence,
        )
        frames["train"].append(frame)
        reports.append(report)

    for run in validation_runs:
        frame, report = replay_run_features(
            run,
            split="validation",
            history_runs=train_runs,
            dark_zone_dir=dark_zone_dir,
            corridor_particles=corridor_particles,
            random_seed=seed,
            transition_confidence=transition_confidence,
            sensor_assignment_confidence=sensor_assignment_confidence,
        )
        frames["validation"].append(frame)
        reports.append(report)

    result: dict[str, Any] = {
        "train_runs": [p.name for p in train_runs],
        "validation_runs": [p.name for p in validation_runs],
        "validation_fraction": float(validation_fraction),
        "seed": int(seed),
        "corridor_particles": int(corridor_particles),
        "feature_count": len(DEFECT_FEATURES),
        "features": list(DEFECT_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "target": TARGET_COLUMN,
        "feature_source": "deployment_public_bus_replay",
        "inspection_used_as": "label_only",
        "same_run_dark_calibration": False,
        "reports": reports,
    }

    for split in ("train", "validation"):
        full = pd.concat(frames[split], ignore_index=True) if frames[split] else pd.DataFrame()
        if full.empty:
            raise RuntimeError(f"{split}: public-bus materialization produced no labelled defect rows")
        if full[TARGET_COLUMN].isna().any():
            raise RuntimeError(f"{split}: censored labels survived materialization")
        missing = [c for c in DEFECT_FEATURES if c not in full.columns]
        if missing:
            raise RuntimeError(f"{split}: missing frozen defect features: {missing}")
        full.to_pickle(output / f"{split}.pkl")
        result[f"{split}_rows"] = int(len(full))
        result[f"{split}_positive_rows"] = int((full[TARGET_COLUMN] == 1).sum())
        result[f"{split}_run_count"] = int(full["run_id"].nunique())

    (output / "generation_report.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return result
