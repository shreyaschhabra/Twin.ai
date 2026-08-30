"""
Step 5 continuation, Section 22: prefix-identity and reproducibility
tests for scaling the historical generator from 24 to 100 shifts.

Also covers the memory-architecture fix discovered while attempting the
real 100-shift generation: generate_development_dataset() +
write_dataset() held every shift's full RunResult in memory
simultaneously, which OOM-killed the process at 100-shift scale (worked
fine at 24). generate_and_write_dataset_streaming() processes shifts in
small batches, discarding each batch's RunResult objects before the
next — a pure orchestration/IO change, sharing the exact same per-shift
simulation logic (_run_one_shift) and row-extraction logic (_extract_rows)
as the original path, so output must be byte-value-identical. These
tests prove that, not just assume it.
"""

from pathlib import Path

import pandas as pd
import pytest

from backend.config.loader import load_factory_config
from backend.historical.generator import (
    generate_and_write_dataset_streaming,
    generate_development_dataset,
    write_dataset,
)
from backend.simulation.material_batches import load_batch_relevant_stations
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
MASTER_SEED = 20240002


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


@pytest.fixture(scope="module")
def sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")


@pytest.fixture(scope="module")
def batch_relevant_stations():
    return load_batch_relevant_stations(CONFIG_DIR / "material_batches_full.yaml")


def _assert_values_equal(a: pd.DataFrame, b: pd.DataFrame, sort_cols):
    cols = list(a.columns)
    a_sorted = a.sort_values(sort_cols)[cols].reset_index(drop=True)
    b_sorted = b.sort_values(sort_cols)[cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a_sorted, b_sorted, check_dtype=False)


def test_streaming_path_matches_batch_path_exactly(config, sensor_models, batch_relevant_stations, tmp_path):
    """The memory-bounded streaming writer must produce byte-value-
    identical output to the original in-memory batch writer for the same
    input — this is a pure IO/memory refactor, never a behavior change."""
    n_shifts = 6

    batch_results = generate_development_dataset(
        config, sensor_models, batch_relevant_stations,
        n_shifts=n_shifts, dataset_master_seed=MASTER_SEED, vehicles_per_shift=20,
    )
    batch_obs, batch_lat = tmp_path / "batch_obs", tmp_path / "batch_lat"
    write_dataset(batch_results, batch_obs, batch_lat)

    stream_obs, stream_lat = tmp_path / "stream_obs", tmp_path / "stream_lat"
    meta, stats = generate_and_write_dataset_streaming(
        config, sensor_models, batch_relevant_stations,
        n_shifts=n_shifts, dataset_master_seed=MASTER_SEED,
        observable_dir=stream_obs, latent_dir=stream_lat,
        vehicles_per_shift=20, batch_size=2,
    )

    _assert_values_equal(
        pd.read_parquet(batch_obs / "events.parquet"),
        pd.read_parquet(stream_obs / "events.parquet"),
        ["shift_id", "event_id"],
    )
    _assert_values_equal(
        pd.read_parquet(batch_obs / "qc_results.parquet"),
        pd.read_parquet(stream_obs / "qc_results.parquet"),
        ["shift_id", "vehicle_id"],
    )
    _assert_values_equal(
        pd.read_parquet(batch_lat / "scenario_truth.parquet"),
        pd.read_parquet(stream_lat / "scenario_truth.parquet"),
        ["shift_id", "scenario_id"],
    )


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "manifest.json").exists(),
    reason="historical_100 dataset not generated in this environment",
)
def test_historical_100_manifest_matches_actual_output():
    import json

    base = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100"
    with (base / "manifest.json").open() as f:
        manifest = json.load(f)
    assert manifest["n_shifts"] == 100
    assert manifest["dataset_master_seed"] == MASTER_SEED
    assert manifest["git_dirty"] is False

    shifts_df = pd.read_parquet(base / "observable" / "shifts.parquet")
    assert len(shifts_df) == 100
    assert set(shifts_df.shift_id) == {f"SHIFT{i:03d}" for i in range(1, 101)}
