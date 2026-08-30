"""Tests for episode-level evaluation (Section 25)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from backend.flow_v2.episode_evaluation import evaluate_episodes


def _row(shift_id, station_id, event_id, time_to_impact):
    return {"shift_id": shift_id, "station_id": station_id, "impact_event_id": event_id,
            "time_to_impact_seconds": time_to_impact, "label": "POSITIVE"}


def _impact(event_id, shift_id="SHIFT001", station_id="S22"):
    return {"impact_event_id": event_id, "shift_id": shift_id, "impact_station_id": station_id}


def test_any_warning_and_band_detection():
    rows = pd.DataFrame([
        _row("SHIFT001", "S22", "E1", 450.0),  # 5-10min band
        _row("SHIFT001", "S22", "E1", 100.0),  # 0-5min band, same episode
    ])
    impacts = pd.DataFrame([_impact("E1")])
    predictions = np.array([1, 1])

    res = evaluate_episodes(rows, predictions, impacts)
    assert res.total_episodes == 1
    assert res.any_warning_detected == 1
    assert res.band_5_10_min_detected == 1
    assert res.band_0_5_min_detected == 1
    assert res.first_warning_lead_times == [450.0]


def test_missed_episode():
    rows = pd.DataFrame([_row("SHIFT001", "S22", "E1", 450.0)])
    impacts = pd.DataFrame([_impact("E1")])
    predictions = np.array([0])

    res = evaluate_episodes(rows, predictions, impacts)
    assert res.any_warning_detected == 0
    assert res.missed_episodes == 1
    assert res.any_warning_recall == 0.0


def test_only_0_5_band_does_not_count_as_5_10():
    rows = pd.DataFrame([_row("SHIFT001", "S22", "E1", 100.0)])
    impacts = pd.DataFrame([_impact("E1")])
    predictions = np.array([1])

    res = evaluate_episodes(rows, predictions, impacts)
    assert res.any_warning_detected == 1
    assert res.band_0_5_min_detected == 1
    assert res.band_5_10_min_detected == 0
