"""Tests for the Trust/missing-data layer (Section 49): LIVE/INFERRED/UNKNOWN,
deterministic transitions, and trust degrading with evidence quality."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.trust.data_state import LIVE_FRESHNESS_SECONDS, classify_data_state
from backend.trust.trust_level import compute_trust_level
from backend.trust.virtual_sensor import estimate_virtual_sensor_value


def test_live_when_fresh_direct_reading():
    result = classify_data_state(has_direct_reading=True, evidence_age_seconds=10.0,
                                  inference_available=False)
    assert result.data_state == "LIVE"


def test_inferred_when_stale_but_fallback_available():
    result = classify_data_state(
        has_direct_reading=True, evidence_age_seconds=LIVE_FRESHNESS_SECONDS + 100,
        inference_available=True, inference_method="same_station_recent", inference_reliable=True,
    )
    assert result.data_state == "INFERRED"
    assert result.inference_method == "same_station_recent"


def test_unknown_when_no_direct_and_no_reliable_inference():
    result = classify_data_state(has_direct_reading=False, evidence_age_seconds=None,
                                  inference_available=False)
    assert result.data_state == "UNKNOWN"


def test_unknown_when_inference_unreliable():
    result = classify_data_state(has_direct_reading=False, evidence_age_seconds=None,
                                  inference_available=True, inference_reliable=False)
    assert result.data_state == "UNKNOWN"


def test_unknown_not_forced_into_inferred_when_too_stale():
    result = classify_data_state(
        has_direct_reading=False, evidence_age_seconds=10000.0,
        inference_available=True, inference_method="operational_baseline", inference_reliable=True,
    )
    assert result.data_state == "UNKNOWN"


def test_deterministic_transitions_live_to_inferred_to_unknown():
    live = classify_data_state(True, 5.0, False)
    inferred = classify_data_state(False, 300.0, True, "same_station_type", True)
    unknown = classify_data_state(False, None, False)
    assert [live.data_state, inferred.data_state, unknown.data_state] == ["LIVE", "INFERRED", "UNKNOWN"]


def test_trust_degrades_with_evidence_quality():
    high = compute_trust_level(live_fraction=1.0, inferred_fraction=0.0, unknown_fraction=0.0,
                                freshness_seconds=10.0, n_supporting_signals=3)
    medium = compute_trust_level(live_fraction=0.5, inferred_fraction=0.5, unknown_fraction=0.0,
                                  freshness_seconds=60.0, n_supporting_signals=3)
    low = compute_trust_level(live_fraction=0.2, inferred_fraction=0.3, unknown_fraction=0.5,
                               freshness_seconds=60.0, n_supporting_signals=3)
    assert high.trust_level == "HIGH"
    assert medium.trust_level == "MEDIUM"
    assert low.trust_level == "LOW"


def test_trust_low_when_stale():
    result = compute_trust_level(live_fraction=1.0, inferred_fraction=0.0, unknown_fraction=0.0,
                                  freshness_seconds=10000.0, n_supporting_signals=3)
    assert result.trust_level == "LOW"


def test_trust_low_when_virtual_sensor_error_high():
    result = compute_trust_level(live_fraction=0.9, inferred_fraction=0.1, unknown_fraction=0.0,
                                  freshness_seconds=30.0, virtual_sensor_error=5.0, n_supporting_signals=3)
    assert result.trust_level == "LOW"


def test_virtual_sensor_hierarchy_same_station_first():
    value, method, reliable = estimate_virtual_sensor_value(
        "S01", "weld_current", "WELDING_BODY_JOINING",
        recent_readings_by_station={("S01", "weld_current"): [100, 102, 98, 101]},
        recent_readings_by_type={("WELDING_BODY_JOINING", "weld_current"): [50, 51, 52, 53, 54]},
        sensor_models={},
    )
    assert method == "same_station_recent"
    assert reliable
    assert 98 <= value <= 102


def test_virtual_sensor_falls_back_to_station_type():
    value, method, reliable = estimate_virtual_sensor_value(
        "S01", "weld_current", "WELDING_BODY_JOINING",
        recent_readings_by_station={}, recent_readings_by_type={("WELDING_BODY_JOINING", "weld_current"): [50, 51, 52, 53, 54]},
        sensor_models={},
    )
    assert method == "same_station_type"
    assert reliable


def test_virtual_sensor_unreliable_when_nothing_available():
    value, method, reliable = estimate_virtual_sensor_value(
        "S01", "weld_current", "WELDING_BODY_JOINING",
        recent_readings_by_station={}, recent_readings_by_type={}, sensor_models={},
    )
    assert not reliable
    assert value is None
