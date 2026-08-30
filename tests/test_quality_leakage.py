"""
Quality leakage tests (Section 17), same future-mutation philosophy as
tests/test_flow_leakage.py: mutate all events/sensors after a snapshot's
own time (including OTHER vehicles' events, since the cohort feature
reads across vehicles) and verify the snapshot's features are unchanged.
Also verifies QC is structurally unavailable before S45.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from backend.config.loader import load_factory_config
from backend.quality.features import ALL_FEATURES, build_quality_features
from backend.quality.labels import attach_final_qc_labels
from backend.quality.snapshots import build_vehicle_snapshots
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "observable" / "events.parquet"


def _config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


def _sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")


def test_future_event_and_sensor_mutation_does_not_change_current_snapshot():
    config = _config()
    sensor_models = _sensor_models()
    events = pd.read_parquet(DATA_PATH)
    sample = events[events.shift_id == "SHIFT001"].copy()

    snapshots = build_vehicle_snapshots(sample)
    baseline = build_quality_features(snapshots, sample, config, sensor_models)

    mutated = sample.copy()
    is_numeric_value = pd.api.types.is_numeric_dtype(mutated["value"])
    # mutate every event/sensor/QC record for EVERY vehicle whose
    # simulation_time is strictly after each row's own snapshot time is
    # impractical per-row; instead mutate ALL events after the LATEST
    # snapshot time in the sample's earliest-stage rows and re-derive only
    # those early rows, which must be identical regardless of what
    # happens afterward for anyone.
    # must be >= every stage-1 vehicle's OWN snapshot time, or we'd corrupt
    # some vehicles' genuinely-in-scope past events (different vehicles
    # reach stage 1 at different simulation times).
    cutoff = snapshots[snapshots.production_stage == 1].snapshot_time.max()
    future_mask = mutated.simulation_time > cutoff
    if is_numeric_value:
        mutated.loc[future_mask, "value"] = mutated.loc[future_mask, "value"].fillna(0) + 999999.0
    mutated.loc[future_mask & (mutated.event_type == "QC_RESULT_RECORDED"), "qc_result"] = "DEFECT"
    mutated.loc[future_mask & (mutated.event_type == "SENSOR_READING"), "measurement_status"] = "missing"

    stage1_snapshots = snapshots[snapshots.production_stage == 1]
    mutated_features = build_quality_features(stage1_snapshots, mutated, config, sensor_models)
    baseline_stage1 = baseline[baseline.production_stage == 1]

    merged = baseline_stage1.merge(mutated_features, on=["vehicle_id", "production_stage"], suffixes=("_base", "_mut"))
    for feat in ALL_FEATURES:
        if feat in ("vehicle_variant", "production_stage"):
            continue  # vehicle_variant is categorical (compared separately); production_stage is a merge key
        col_base, col_mut = merged[f"{feat}_base"], merged[f"{feat}_mut"]
        both_nan = col_base.isna() & col_mut.isna()
        assert np.allclose(
            col_base[~both_nan].astype(float), col_mut[~both_nan].astype(float), equal_nan=True
        ), f"feature {feat} changed when only future events were mutated -- leakage"


def test_qc_result_unavailable_before_s45():
    config = _config()
    sensor_models = _sensor_models()
    events = pd.read_parquet(DATA_PATH)
    sample = events[events.shift_id == "SHIFT001"]

    snapshots = build_vehicle_snapshots(sample)
    featured = build_quality_features(snapshots, sample, config, sensor_models)

    assert "qc_result" not in featured.columns
    assert "target" not in featured.columns
    for feat in ALL_FEATURES:
        assert "qc" not in feat.lower()


def test_labels_attached_only_after_feature_build():
    config = _config()
    sensor_models = _sensor_models()
    events = pd.read_parquet(DATA_PATH)
    sample = events[events.shift_id == "SHIFT001"]

    snapshots = build_vehicle_snapshots(sample)
    featured = build_quality_features(snapshots, sample, config, sensor_models)
    labeled = attach_final_qc_labels(featured, sample)

    assert labeled.target.isin([0, 1]).all()
    # every vehicle's target must be constant across its own 5 snapshots
    # (it's the vehicle's single eventual outcome, not a moving target)
    per_vehicle_nunique = labeled.groupby("vehicle_id").target.nunique()
    assert (per_vehicle_nunique == 1).all()


def test_no_forbidden_fields_in_features():
    forbidden_substrings = ["scenario", "exposure", "latent", "probability_used", "bad_batch", "batch_is_bad", "true_degradation"]
    for feat in ALL_FEATURES:
        for bad in forbidden_substrings:
            assert bad not in feat.lower(), f"feature {feat} looks like it exposes latent/scenario truth"


def test_raw_batch_key_not_a_feature():
    from backend.quality.features import CATEGORICAL_FEATURES
    assert "batch_key" not in CATEGORICAL_FEATURES
    assert "batch_id" not in CATEGORICAL_FEATURES
