"""Tests for the four demo builders (Section 49): each demo file exists
and conforms to the canonical schema expected by later API/frontend work."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

DEMO_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "demo"

pytestmark = pytest.mark.skipif(not DEMO_DIR.exists(), reason="demos not built yet")


def _load(name):
    path = DEMO_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not built yet")
    with path.open() as f:
        return json.load(f)


def test_bottleneck_demo_schema():
    demo = _load("bottleneck_demo.json")
    assert demo["scenario"] == "bottleneck"
    assert "station_id" in demo and "shift_id" in demo
    assert isinstance(demo["timeline"], list) and len(demo["timeline"]) > 0
    for step in demo["timeline"]:
        assert "bottleneck_risk" in step
        assert "label" in step


def test_quality_demo_schema():
    demo = _load("quality_demo.json")
    assert demo["scenario"] == "quality"
    assert demo["final_qc"] == "DEFECT"
    assert len(demo["checkpoints"]) == 5
    for cp in demo["checkpoints"]:
        assert 0.0 <= cp["quality_risk"] <= 1.0
        assert cp["risk_level"] in {"LOW", "MEDIUM", "HIGH"}


def test_sensor_loss_demo_schema():
    demo = _load("sensor_loss_demo.json")
    assert demo["scenario"] == "sensor_loss"
    states = [s["data_state"] for s in demo["stages"]]
    assert states == ["LIVE", "INFERRED", "UNKNOWN"]


def test_benign_variation_demo_schema():
    demo = _load("benign_variation_demo.json")
    assert demo["scenario"] == "benign_variation"
    assert demo["family"] == "VEHICLE_MIX_OVERLOAD"
    assert "aggregate_across_all_instances" in demo
    assert demo["aggregate_across_all_instances"]["n_instances"] > 0


def test_manager_analytics_schema():
    path = DEMO_DIR / "manager_analytics.json"
    if not path.exists():
        pytest.skip("manager analytics not built yet")
    with path.open() as f:
        data = json.load(f)
    for key in ["throughput_by_shift", "bottleneck_events_by_station", "average_cycle_deviation_by_station",
                "sensor_coverage_by_maturity", "data_state_distribution"]:
        assert key in data
