"""Tests for Flow v2 consequence-based labeling (Section 33)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from backend.flow_v2.labels import HORIZON_SECONDS, apply_already_full_exclusion, label_rows_v2


def _grid_row(shift_id, station_id, t):
    return {"shift_id": shift_id, "station_id": station_id, "window_end_time": t}


def _impact(shift_id, station_id, onset, end, event_id="E1"):
    return {"impact_event_id": event_id, "shift_id": shift_id, "impact_station_id": station_id,
            "onset_time": onset, "end_time": end}


def _events(shift_id, max_time):
    return pd.DataFrame([{"shift_id": shift_id, "simulation_time": max_time}])


def test_positive_within_full_10_minute_window():
    """Unlike v1, a row 2 minutes before onset (not just 5-10) must be POSITIVE."""
    onset = 1000.0
    grid = pd.DataFrame([_grid_row("SHIFT001", "S22", onset - 120)])  # 2 min before onset
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset, onset + 10)])
    events = _events("SHIFT001", onset + 10000)

    labeled = label_rows_v2(grid, impacts, events)
    assert labeled.iloc[0].label == "POSITIVE"
    assert labeled.iloc[0].target == 1
    assert labeled.iloc[0].impact_event_id == "E1"
    assert abs(labeled.iloc[0].time_to_impact_seconds - 120.0) < 1e-6


def test_boundary_exactly_600_seconds_is_positive():
    onset = 1000.0
    grid = pd.DataFrame([_grid_row("SHIFT001", "S22", onset - 600)])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset, onset + 10)])
    events = _events("SHIFT001", onset + 10000)
    labeled = label_rows_v2(grid, impacts, events)
    assert labeled.iloc[0].label == "POSITIVE"


def test_boundary_beyond_600_seconds_is_negative():
    onset = 1000.0
    grid = pd.DataFrame([_grid_row("SHIFT001", "S22", onset - 601)])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset, onset + 10)])
    events = _events("SHIFT001", onset + 10000)
    labeled = label_rows_v2(grid, impacts, events)
    assert labeled.iloc[0].label == "NEGATIVE"


def test_active_row_excluded():
    onset = 1000.0
    grid = pd.DataFrame([_grid_row("SHIFT001", "S22", onset + 5)])  # inside [onset, end]
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset, onset + 10)])
    events = _events("SHIFT001", onset + 10000)
    labeled = label_rows_v2(grid, impacts, events)
    assert labeled.iloc[0].label == "ACTIVE_EXCLUDED"
    assert pd.isna(labeled.iloc[0].target)


def test_horizon_incomplete_excluded():
    """Shift ends before a full 10-minute future window is available."""
    grid = pd.DataFrame([_grid_row("SHIFT001", "S22", 9700.0)])
    impacts = pd.DataFrame(columns=["impact_event_id", "shift_id", "impact_station_id", "onset_time", "end_time"])
    events = _events("SHIFT001", 10000.0)  # shift ends 300s after t -- not a full 600s horizon
    labeled = label_rows_v2(grid, impacts, events)
    assert labeled.iloc[0].label == "HORIZON_INCOMPLETE_EXCLUDED"
    assert pd.isna(labeled.iloc[0].target)


def test_already_full_exclusion_applied_after_features():
    labeled = pd.DataFrame([
        {"label": "NEGATIVE", "target": 0, "impact_event_id": None, "time_to_impact_seconds": np.nan, "inbound_occupancy_ratio": 1.0},
        {"label": "POSITIVE", "target": 1, "impact_event_id": "E1", "time_to_impact_seconds": 200.0, "inbound_occupancy_ratio": 0.5},
    ])
    result = apply_already_full_exclusion(labeled)
    assert result.iloc[0].label == "ALREADY_FULL_EXCLUDED"
    assert pd.isna(result.iloc[0].target)
    assert result.iloc[1].label == "POSITIVE"  # untouched -- not already full


def test_time_to_impact_and_event_id_are_metadata_not_features():
    from backend.flow.baselines import ALL_FEATURES
    assert "impact_event_id" not in ALL_FEATURES
    assert "time_to_impact_seconds" not in ALL_FEATURES
