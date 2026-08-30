"""Tests for grouped split isolation, sampling reproducibility, and Flow
v1 non-regression (Section 33)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

from backend.flow_v2.sampling import deduplicate_rows
from backend.flow_v2.split import locked_flow_v2_split, validate_split


def test_one_run_group_never_crosses_partitions():
    all_shifts = [f"SHIFT{i:03d}" for i in range(1, 101)]
    split = locked_flow_v2_split(all_shifts)
    validate_split(split, all_shifts)  # raises on any overlap or coverage gap
    train, val, test = set(split.train_shifts), set(split.validation_shifts), set(split.test_shifts)
    assert not (train & val) and not (train & test) and not (val & test)


def test_split_covers_every_shift_exactly_once():
    all_shifts = [f"SHIFT{i:03d}" for i in range(1, 101)]
    split = locked_flow_v2_split(all_shifts)
    covered = split.train_shifts + split.validation_shifts + split.test_shifts
    assert sorted(covered) == sorted(all_shifts)
    assert len(covered) == len(set(covered))  # no duplicates


def test_split_is_deterministic():
    all_shifts = [f"SHIFT{i:03d}" for i in range(1, 101)]
    split_a = locked_flow_v2_split(all_shifts)
    split_b = locked_flow_v2_split(all_shifts)
    assert split_a == split_b


def test_deduplication_is_deterministic_and_label_blind():
    df = pd.DataFrame({
        "shift_id": ["S1"] * 5, "station_id": ["A"] * 5, "window_end_time": [60, 120, 180, 240, 300],
        "inbound_occupancy_ratio": [0.1, 0.1, 0.1, 0.9, 0.9], "cycle_time_dev_relative": [0.0] * 5,
        "prop_blocked_5m": [0.0] * 5, "prop_starved_5m": [0.0] * 5, "prop_down_5m": [0.0] * 5,
        "target": [0, 0, 0, 1, 0],  # label present but must not influence dedup
    })
    result_a = deduplicate_rows(df)
    result_b = deduplicate_rows(df)
    pd.testing.assert_frame_equal(result_a.reset_index(drop=True), result_b.reset_index(drop=True))
    # first 3 rows share a bucket (occupancy 0.1) -> only the first survives;
    # row 4 (0.9) is a new bucket -> survives; row 5 (0.9) repeats -> dropped
    assert len(result_a) == 2
    assert list(result_a.window_end_time) == [60, 240]


def test_deduplication_never_reads_target_column():
    """Two frames identical except for the target column must dedup identically."""
    base = pd.DataFrame({
        "shift_id": ["S1"] * 3, "station_id": ["A"] * 3, "window_end_time": [60, 120, 180],
        "inbound_occupancy_ratio": [0.1, 0.5, 0.9], "cycle_time_dev_relative": [0.0] * 3,
        "prop_blocked_5m": [0.0] * 3, "prop_starved_5m": [0.0] * 3, "prop_down_5m": [0.0] * 3,
    })
    df1 = base.copy(); df1["target"] = [0, 0, 0]
    df2 = base.copy(); df2["target"] = [0, 1, 0]
    result1 = deduplicate_rows(df1)
    result2 = deduplicate_rows(df2)
    assert list(result1.window_end_time) == list(result2.window_end_time)


