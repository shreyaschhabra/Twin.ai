"""Tests for the canonical station/vehicle/alert objects (Section 49)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from backend.intelligence.factory_state import build_alert, build_station_object, build_vehicle_object
from backend.intelligence.onset import estimate_onset_window


def test_build_station_object_schema():
    obj = build_station_object(
        station_id="S22", operation="Wiring Harness Installation", zone="final_assembly",
        bottleneck_risk=0.82, status="HIGH_RISK", predicted_onset_min=6.0, predicted_onset_max=8.0,
        cycle_time=104, baseline_cycle_time=88, buffer_occupancy=3, buffer_capacity=4,
        arrivals_per_min=0.58, departures_per_min=0.49, data_state="LIVE", trust_level="HIGH", evidence=[],
    )
    for key in ["station_id", "operation", "zone", "status", "bottleneck_risk", "predicted_onset_min",
                "predicted_onset_max", "cycle_time", "baseline_cycle_time", "buffer_occupancy",
                "buffer_capacity", "arrivals_per_min", "departures_per_min", "data_state", "trust_level", "evidence"]:
        assert key in obj


def test_build_vehicle_object_schema():
    obj = build_vehicle_object(
        vehicle_id="VH-10428", variant="EV", current_station="S31", quality_risk=0.72, risk_level="HIGH",
        data_state="LIVE", trust_level="MEDIUM", evidence=[{"station_id": "S27", "description": "Fastening process deviation"}],
    )
    assert obj["final_qc"] is None
    obj2 = build_vehicle_object(
        vehicle_id="VH-10428", variant="EV", current_station=None, quality_risk=0.72, risk_level="HIGH",
        data_state="LIVE", trust_level="MEDIUM", evidence=[], final_qc="PASS",
    )
    assert obj2["final_qc"] == "PASS"


def test_build_alert_schema_and_type_validation():
    alert = build_alert(alert_type="FLOW", severity="HIGH", station_id="S22", title="Bottleneck risk rising",
                         description="Blocking predicted in approximately 6-8 minutes", risk=0.82,
                         trust_level="HIGH", data_state="LIVE")
    assert alert["type"] == "FLOW"
    with pytest.raises(AssertionError):
        build_alert(alert_type="NOT_A_TYPE", severity="HIGH", station_id=None, title="x", description="x",
                    risk=None, trust_level="LOW", data_state="UNKNOWN")


def test_onset_estimate_returns_none_when_not_growing():
    lo, hi = estimate_onset_window(current_occupancy=1, buffer_capacity=4, arrivals_per_min=0.4, departures_per_min=0.5)
    assert lo is None and hi is None


def test_onset_estimate_returns_band_when_growing():
    lo, hi = estimate_onset_window(current_occupancy=2, buffer_capacity=4, arrivals_per_min=0.6, departures_per_min=0.4)
    assert lo is not None and hi is not None
    assert lo < hi
