"""Materialize only the frozen bottleneck dataset from simulator run folders.

This is the factory-training input seam.  It deliberately consumes completed
``run_*`` directories in place: no ZIP archive and no copy of raw CSV data is
created.  The general causal builder remains available for its broader
development datasets; factory bottleneck training uses this focused path so it
does not spend time building unrelated features.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .build_causal_datasets import BOTTLENECK_FEATURES, bottleneck_rows, station_num
except ImportError:  # Supports direct execution.
    from build_causal_datasets import BOTTLENECK_FEATURES, bottleneck_rows, station_num


REQUIRED_RUN_FILES = {"stations.csv", "station_events.csv", "run_metadata.json"}
SCHEMA_VERSION = "bottleneck-causal-features-v1"
HORIZON_MS = 1_800_000


def discover_runs(runs_root: str | Path) -> list[Path]:
    root = Path(runs_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Training runs directory not found: {root}")
    runs = sorted(path for path in root.glob("run_*") if path.is_dir())
    if not runs:
        raise FileNotFoundError(f"No run_* directories found under: {root}")
    return runs


def _load_run(run: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = sorted(name for name in REQUIRED_RUN_FILES if not (run / name).is_file())
    if missing:
        raise FileNotFoundError(f"{run.name} is incomplete; missing: {', '.join(missing)}")
    # Verify it is a completed simulator directory before its CSVs are trusted.
    metadata = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    if not metadata.get("schema_version"):
        raise ValueError(f"{run / 'run_metadata.json'} has no schema_version")

    stations = pd.read_csv(run / "stations.csv")
    events = pd.read_csv(run / "station_events.csv")
    required_stations = {"station_id", "buffer_capacity", "base_cycle_time_ms", "cycle_time_std_ms", "archetype"}
    required_events = {"timestamp_ms", "station_id", "event_type", "queue_length_after", "cycle_time_ms"}
    if missing_columns := sorted(required_stations - set(stations.columns)):
        raise ValueError(f"{run / 'stations.csv'} missing columns: {missing_columns}")
    if missing_columns := sorted(required_events - set(events.columns)):
        raise ValueError(f"{run / 'station_events.csv'} missing columns: {missing_columns}")

    stations = stations.copy()
    events = events.copy()
    stations["station_id"] = stations["station_id"].astype(str).str.strip()
    events["station_id"] = events["station_id"].astype(str).str.strip()
    stations["station_index"] = stations["station_id"].map(station_num) - 1
    events["timestamp_ms"] = pd.to_numeric(events["timestamp_ms"], errors="raise")
    events["event_type"] = events["event_type"].astype(str).str.strip().str.upper()
    # DARK_ZONE_ENTERED / DARK_ZONE_EXITED are public control boundaries for
    # the estimator. Runtime never sends them through the LIGHT feature builder,
    # so factory training must not treat them as ordinary station observations.
    events = events.loc[
        ~events["event_type"].isin({"DARK_ZONE_ENTERED", "DARK_ZONE_EXITED"})
    ].copy()
    events["station_index"] = events["station_id"].map(station_num) - 1
    events["event_sequence"] = np.arange(len(events), dtype=np.int64)
    return stations, events


def _validate_causal_projection(dataset: pd.DataFrame, runs: list[Path]) -> dict[str, int]:
    """Independent, low-memory guards for the released bottleneck projection.

    The broader causal validator remains the development regression suite.  This
    focused check keeps the direct factory path from silently accepting a broken
    event sequence, current occupancy, or future-label eligibility rule.
    """
    checked_rows = 0
    labeled_rows = 0
    for run in runs:
        stations, events = _load_run(run)
        rows = dataset.loc[dataset["run_id"].eq(run.name)]
        if len(rows) != len(events):
            raise RuntimeError(f"{run.name}: expected one bottleneck row per station event")
        capacities = stations.set_index("station_id")["buffer_capacity"].astype(float).to_dict()
        for station_id, station_rows in rows.groupby("station_id_buffer_id", sort=False):
            history = events.loc[events["station_id"].eq(station_id)].sort_values(
                ["timestamp_ms", "event_sequence"], kind="stable"
            )
            expected_sequences = history["event_sequence"].to_numpy()
            actual_sequences = station_rows.sort_values("prediction_event_sequence")["prediction_event_sequence"].to_numpy()
            if not np.array_equal(expected_sequences, actual_sequences):
                raise RuntimeError(f"{run.name}:{station_id}: prediction sequence does not match raw event order")
            observed = pd.to_numeric(history["queue_length_after"], errors="coerce").ffill().fillna(0.0).to_numpy()
            ordered_rows = station_rows.sort_values("prediction_event_sequence")
            if not np.allclose(ordered_rows["current_occupancy"].to_numpy(dtype=float), observed, equal_nan=True):
                raise RuntimeError(f"{run.name}:{station_id}: current occupancy is not a causal replay state")
            capacity = capacities[str(station_id)]
            for row in ordered_rows.itertuples(index=False):
                checked_rows += 1
                complete = int(history["timestamp_ms"].max()) >= int(row.prediction_time) + HORIZON_MS
                eligible = complete and not bool(row.currently_at_capacity)
                if pd.notna(row.y_bottleneck):
                    labeled_rows += 1
                    if not eligible or row.target_eligibility_status != "eligible":
                        raise RuntimeError(f"{run.name}:{station_id}: invalid future label eligibility")
                    future = history.loc[
                        (history["timestamp_ms"] > row.prediction_time)
                        & (history["timestamp_ms"] <= row.prediction_time + HORIZON_MS),
                        "queue_length_after",
                    ]
                    expected_label = int(pd.to_numeric(future, errors="coerce").max() >= capacity)
                    if int(row.y_bottleneck) != expected_label:
                        raise RuntimeError(f"{run.name}:{station_id}: future label differs from declared horizon")
    return {"rows_checked": checked_rows, "labeled_rows_checked": labeled_rows}


def _write_materialized_dataset(dataset: pd.DataFrame, output_dir: Path) -> tuple[Path, str]:
    """Prefer Parquet, but keep factory training runnable without a Parquet engine."""
    parquet = output_dir / "bottleneck_causal_features.parquet"
    try:
        dataset.to_parquet(parquet, index=False)
        return parquet, "parquet"
    except ImportError:
        csv = output_dir / "bottleneck_causal_features.csv"
        dataset.to_csv(csv, index=False)
        return csv, "csv_fallback_no_parquet_engine"


def materialize(runs_root: str | Path, output: str | Path) -> Path:
    """Write derived bottleneck features; raw run folders stay the source of truth."""
    runs = discover_runs(runs_root)
    output_path = Path(output).expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite derived dataset directory: {output_path}")
    output_path.mkdir(parents=True)

    frames: list[pd.DataFrame] = []
    manifest_runs: list[dict[str, object]] = []
    for run in runs:
        stations, events = _load_run(run)
        frame = bottleneck_rows(run.name, stations, events)
        frames.append(frame)
        manifest_runs.append({"run_id": run.name, "path": str(run), "rows": int(len(frame))})

    dataset = pd.concat(frames, ignore_index=True)
    projection = [column for column in dataset.columns if column in BOTTLENECK_FEATURES]
    if projection != BOTTLENECK_FEATURES or len(set(dataset.columns)) != len(dataset.columns):
        raise RuntimeError("Bottleneck frozen feature projection is missing, reordered, or duplicated")

    validation = _validate_causal_projection(dataset, runs)

    dataset_file, dataset_format = _write_materialized_dataset(dataset, output_path)
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "input_runs_root": str(Path(runs_root).expanduser().resolve()),
        "runs": manifest_runs,
        "run_count": len(manifest_runs),
        "bottleneck_rows": int(len(dataset)),
        "dataset_file": dataset_file.name,
        "dataset_format": dataset_format,
        "feature_count": len(BOTTLENECK_FEATURES),
        "features": BOTTLENECK_FEATURES,
        "independent_validation": validation,
        "causality": "Features use causal observable event prefixes; labels use only the defined future training horizon.",
        "dark_training_policy": (
            "DARK_ZONE_ENTERED/EXITED are estimator control boundaries, not model training rows. "
            "Simulator-hidden DARK stations receive no invented labels; continued training retains "
            "their protected base-model behavior and categorical contract."
        ),
    }
    (output_path / "dataset_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build frozen bottleneck features directly from simulator run folders.")
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(materialize(args.runs, args.output))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"bottleneck dataset build failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
