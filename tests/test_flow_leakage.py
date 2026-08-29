"""
Step 5, Section P: mandatory future-mutation leakage test, plus the
strict point-in-time checks from Section AB. Uses a small real slice of
the frozen development dataset (SHIFT004, which has genuine activity at
several stations) rather than only synthetic data, so the test exercises
the real feature-computation code paths.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.config.loader import load_factory_config
from backend.flow.features import build_features
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "development_45" / "observable"


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


@pytest.fixture(scope="module")
def sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")


@pytest.fixture(scope="module")
def sample_events():
    events = pd.read_parquet(DATA_DIR / "events.parquet")
    return events[events.shift_id == "SHIFT004"].copy()


def _grid_for(shift_id, station_id, t_values):
    return pd.DataFrame({"shift_id": shift_id, "station_id": station_id, "window_end_time": t_values})


def test_future_event_mutation_does_not_change_current_features(config, sensor_models, sample_events):
    """Mandatory Section P test: build features at t, drastically mutate
    everything strictly after t, rebuild, and require identical features."""
    t = 20000.0
    station_id = "S21"
    grid = _grid_for("SHIFT004", station_id, [t])

    baseline = build_features(grid, sample_events, config, sensor_models)

    mutated = sample_events.copy()
    future_mask = mutated.simulation_time > t
    assert future_mask.sum() > 0, "test needs future events to actually mutate"
    # dramatic mutation: blow out every numeric value after t
    mutated.loc[future_mask, "value"] = mutated.loc[future_mask, "value"].apply(
        lambda v: v * 1000 + 999999 if pd.notna(v) else v
    )
    mutated.loc[future_mask, "occupancy"] = 999
    mutated.loc[future_mask & (mutated.event_type == "SENSOR_READING"), "measurement_status"] = "missing"
    # add entirely new fabricated future events too
    fabricated = sample_events[sample_events.simulation_time > t].copy()
    fabricated["simulation_time"] = fabricated.simulation_time + 100000
    mutated = pd.concat([mutated, fabricated], ignore_index=True)

    rebuilt = build_features(grid, mutated, config, sensor_models)

    feature_cols = [c for c in baseline.columns if c not in ("shift_id", "station_id", "window_end_time")]
    for col in feature_cols:
        b, r = baseline.iloc[0][col], rebuilt.iloc[0][col]
        if isinstance(b, float) and np.isnan(b) and isinstance(r, float) and np.isnan(r):
            continue
        assert b == r, f"feature '{col}' changed from future mutation: {b} -> {r}"


def test_future_sensor_mutation_alone_does_not_change_features(config, sensor_models, sample_events):
    t = 15000.0
    station_id = "S05"  # a partial-maturity station with a real sensor
    grid = _grid_for("SHIFT004", station_id, [t])

    baseline = build_features(grid, sample_events, config, sensor_models)

    mutated = sample_events.copy()
    future_sensor_mask = (mutated.event_type == "SENSOR_READING") & (mutated.simulation_time > t)
    assert future_sensor_mask.sum() > 0
    mutated.loc[future_sensor_mask, "value"] = -99999.0

    rebuilt = build_features(grid, mutated, config, sensor_models)
    sensor_cols = [c for c in baseline.columns if c.startswith("sensor_")]
    for col in sensor_cols:
        b, r = baseline.iloc[0][col], rebuilt.iloc[0][col]
        if pd.isna(b) and pd.isna(r):
            continue
        assert b == r, f"sensor feature '{col}' changed from future sensor mutation: {b} -> {r}"


def test_all_feature_source_events_are_at_or_before_t(config, sensor_models, sample_events):
    """Section O: directly verify no event/reading strictly after t was
    ever consulted, by checking the feature-relevant event slice used
    internally matches a manual <= t filter for a representative window."""
    t = 25000.0
    relevant = sample_events[sample_events.simulation_time <= t]
    future = sample_events[sample_events.simulation_time > t]
    assert len(future) > 0
    # rebuild with ONLY the <=t slice and compare against full-table build
    # at the same t: if the pipeline only ever looks backward, restricting
    # the input to already-past events must not change the result at all
    grid = _grid_for("SHIFT004", "S22", [t])
    full_result = build_features(grid, sample_events, config, sensor_models)
    past_only_result = build_features(grid, relevant, config, sensor_models)

    feature_cols = [c for c in full_result.columns if c not in ("shift_id", "station_id", "window_end_time")]
    for col in feature_cols:
        b, r = full_result.iloc[0][col], past_only_result.iloc[0][col]
        if isinstance(b, float) and np.isnan(b) and isinstance(r, float) and np.isnan(r):
            continue
        assert b == r, f"feature '{col}' used future data: full={b} past_only={r}"
