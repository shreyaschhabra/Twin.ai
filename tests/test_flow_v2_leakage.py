"""Future-mutation leakage test for Flow v2 labels (Section 33), same
philosophy as tests/test_flow_leakage.py: mutating events strictly after
a row's own window_end_time must never change that row's label."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.pipeline import build_station_minute_grid
from backend.flow_v2.labels import label_rows_v2

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "observable" / "events.parquet"


def test_future_event_mutation_does_not_change_v2_labels():
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    events = pd.read_parquet(DATA_PATH)
    sample = events[events.shift_id == "SHIFT004"].copy()  # known busy shift

    impacts = detect_bottleneck_events(sample, config)
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(sample, station_ids)
    baseline = label_rows_v2(grid, impacts, sample)

    cutoff = grid.window_end_time.median()
    mutated = sample.copy()
    future_mask = mutated.simulation_time > cutoff
    mutated.loc[future_mask & mutated.value.notna(), "value"] = mutated.loc[future_mask & mutated.value.notna(), "value"] + 999999.0

    mutated_impacts = detect_bottleneck_events(mutated, config)
    mutated_grid = build_station_minute_grid(mutated, station_ids)
    mutated_labeled = label_rows_v2(mutated_grid, mutated_impacts, mutated)

    early_rows = grid[grid.window_end_time <= cutoff]
    merged = baseline.merge(early_rows[["shift_id", "station_id", "window_end_time"]], on=["shift_id", "station_id", "window_end_time"])
    merged_mutated = mutated_labeled.merge(early_rows[["shift_id", "station_id", "window_end_time"]], on=["shift_id", "station_id", "window_end_time"])

    compare = merged[["shift_id", "station_id", "window_end_time", "label"]].merge(
        merged_mutated[["shift_id", "station_id", "window_end_time", "label"]],
        on=["shift_id", "station_id", "window_end_time"], suffixes=("_base", "_mut"),
    )
    mismatches = compare[compare.label_base != compare.label_mut]
    assert len(mismatches) == 0, f"{len(mismatches)} label mismatches after future-only mutation:\n{mismatches.head(10)}"
