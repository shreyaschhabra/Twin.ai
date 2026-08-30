"""Tests for the corrected eligible-event evaluator (backend/flow/event_evaluation.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from backend.flow.event_evaluation import evaluate_events, lead_time_report


def _row(shift_id, station_id, window_end_time, label, target_onset_time=None):
    return {"shift_id": shift_id, "station_id": station_id, "window_end_time": window_end_time,
            "label": label, "target_onset_time": target_onset_time}


def _impact(shift_id, station_id, onset_time, event_id="E1"):
    return {"impact_event_id": event_id, "shift_id": shift_id, "impact_station_id": station_id,
            "onset_time": onset_time}


def test_eligible_event_detected_by_valid_alert():
    onset = 1000.0
    rows = pd.DataFrame([
        _row("SHIFT001", "S22", onset - 450, "POSITIVE", onset),  # valid: lead=450s
        _row("SHIFT001", "S22", 100.0, "NEGATIVE"),
    ])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset)])
    predictions = np.array([1, 0])  # fires on the valid row

    res = evaluate_events(rows, predictions, impacts)
    assert res.total_impact_events == 1
    assert res.eligible_events == 1
    assert res.detected_eligible_events == 1
    assert res.event_recall == 1.0
    assert res.missed_events == 0
    assert res.first_valid_lead_times == [450.0]


def test_ineligible_event_excluded_from_denominator():
    """An event with NO valid POSITIVE row 5-10 min before onset (e.g. too
    close to shift start) must not count toward event recall at all."""
    onset = 1000.0
    rows = pd.DataFrame([
        _row("SHIFT001", "S22", 100.0, "NEGATIVE"),  # no POSITIVE row exists for this event
    ])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset)])
    predictions = np.array([0])

    res = evaluate_events(rows, predictions, impacts)
    assert res.total_impact_events == 1
    assert res.eligible_events == 0
    assert res.detected_eligible_events == 0
    assert np.isnan(res.event_recall)  # undefined, not zero -- no eligible events to measure


def test_missed_eligible_event():
    onset = 1000.0
    rows = pd.DataFrame([
        _row("SHIFT001", "S22", onset - 450, "POSITIVE", onset),
    ])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset)])
    predictions = np.array([0])  # model did not fire

    res = evaluate_events(rows, predictions, impacts)
    assert res.eligible_events == 1
    assert res.detected_eligible_events == 0
    assert res.missed_events == 1
    assert res.event_recall == 0.0


def test_different_station_prediction_does_not_count():
    onset = 1000.0
    rows = pd.DataFrame([
        _row("SHIFT001", "S22", onset - 450, "POSITIVE", onset),
        _row("SHIFT001", "S21", onset - 450, "NEGATIVE"),  # wrong station, even if it fired
    ])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", onset)])
    predictions = np.array([0, 1])  # fires on S21, not S22

    res = evaluate_events(rows, predictions, impacts)
    assert res.detected_eligible_events == 0
    assert res.missed_events == 1
    # S21's positive prediction doesn't match the S22 event's onset -> false warning
    assert res.false_warnings == 1


def test_lead_time_report_bounds_enforced():
    report = lead_time_report([305.0, 450.0, 599.0])
    assert report["count"] == 3
    assert report["min_lead_time_s"] == 305.0
    assert report["max_lead_time_s"] == 599.0
    assert report["median_valid_lead_time_s"] == 450.0


def test_lead_time_report_rejects_out_of_bounds():
    import pytest
    with pytest.raises(AssertionError):
        lead_time_report([700.0])  # outside [300,600] -- must never happen


def test_false_warning_counted_when_onset_time_does_not_match_any_event():
    rows = pd.DataFrame([
        _row("SHIFT001", "S22", 100.0, "POSITIVE", 99999.0),  # predicted positive, but no matching real event
    ])
    impacts = pd.DataFrame([_impact("SHIFT001", "S22", 1000.0)])
    predictions = np.array([1])

    res = evaluate_events(rows, predictions, impacts)
    assert res.false_warnings == 1
