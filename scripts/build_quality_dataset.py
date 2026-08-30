"""
Builds the Quality vehicle-history snapshot dataset (Sections 13-18) from
Dataset A (data/generated/historical_100/, the naturalistic corpus with
the audited QC generator -- NOT Dataset C, whose Flow enrichment shifted
the QC defect rate upward from 4.436% to 5.744%).

Saves data/processed/quality_v1/{train,validation,test}.parquet +
feature_manifest.json + dataset_manifest.json.

Usage:
    python scripts/build_quality_dataset.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.split import locked_100_shift_split
from backend.quality.features import ALL_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES, build_quality_features
from backend.quality.labels import attach_final_qc_labels
from backend.quality.snapshots import CHECKPOINT_STATIONS, build_vehicle_snapshots
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
SOURCE_BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "quality_v1"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    t0 = time.time()
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")

    events = pd.read_parquet(SOURCE_BASE / "observable" / "events.parquet")
    print(f"Source corpus: {SOURCE_BASE.name} (Dataset A, naturalistic) -- {len(events):,} events, "
          f"{events.shift_id.nunique()} shifts")

    section("1. VEHICLE SNAPSHOTS")
    snapshots = build_vehicle_snapshots(events)
    print(f"Snapshots: {len(snapshots):,} rows ({snapshots.vehicle_id.nunique():,} vehicles x "
          f"{len(CHECKPOINT_STATIONS)} checkpoints)")

    section("2. FEATURES (point-in-time per vehicle)")
    t_feat = time.time()
    featured = build_quality_features(snapshots, events, config, sensor_models)
    print(f"Feature build time: {time.time()-t_feat:.1f}s")

    section("3. LABELS (final QC outcome, S45 only)")
    labeled = attach_final_qc_labels(featured, events)
    print(f"Label distribution: {dict(labeled.target.value_counts())}")
    print(f"Overall defect rate (vehicle-level, {labeled.vehicle_id.nunique()} vehicles): "
          f"{labeled.groupby('vehicle_id').target.first().mean()*100:.3f}%")

    section("4. CHRONOLOGICAL SHIFT SPLIT (same convention as Flow)")
    split = locked_100_shift_split()
    train = labeled[labeled.shift_id.isin(split.train_shifts)].copy()
    val = labeled[labeled.shift_id.isin(split.validation_shifts)].copy()
    test = labeled[labeled.shift_id.isin(split.test_shifts)].copy()
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, df in [("train", train), ("val", val), ("test", test)]:
        print(f"  {name}: vehicles={df.vehicle_id.nunique()} defect_rate={df.groupby('vehicle_id').target.first().mean()*100:.3f}%")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train.to_parquet(OUT_DIR / "train.parquet", index=False)
    val.to_parquet(OUT_DIR / "validation.parquet", index=False)
    test.to_parquet(OUT_DIR / "test.parquet", index=False)

    feature_manifest = [{"name": f, "type": "categorical" if f in CATEGORICAL_FEATURES else "numeric"} for f in ALL_FEATURES]
    with (OUT_DIR / "feature_manifest.json").open("w") as f:
        json.dump(feature_manifest, f, indent=2)

    dataset_manifest = {
        "source_dataset": "data/generated/historical_100 (Dataset A, naturalistic, audited QC generator)",
        "checkpoint_stations": CHECKPOINT_STATIONS,
        "split": {"train_shifts": "SHIFT001-070", "validation_shifts": "SHIFT071-085", "test_shifts": "SHIFT086-100"},
        "row_counts": {"train": len(train), "validation": len(val), "test": len(test)},
        "vehicle_counts": {"train": int(train.vehicle_id.nunique()), "validation": int(val.vehicle_id.nunique()),
                            "test": int(test.vehicle_id.nunique())},
        "n_features": len(ALL_FEATURES), "numeric_features": NUMERIC_FEATURES, "categorical_features": CATEGORICAL_FEATURES,
        "generation_seconds": time.time() - t0,
    }
    with (OUT_DIR / "dataset_manifest.json").open("w") as f:
        json.dump(dataset_manifest, f, indent=2)

    print(f"\nSaved to {OUT_DIR}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
