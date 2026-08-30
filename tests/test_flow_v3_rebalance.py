from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.simulation.engine import run_simulation

ROOT = Path(__file__).resolve().parent.parent


def _configs():
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    plan = load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml")
    return base, apply_rebalance(base, plan), plan


def test_rebalance_is_versioned_and_does_not_mutate_flow_v2_config():
    base, rebalanced, plan = _configs()
    assert plan["plan_id"] == "flow_v3_rebalance_review_1"
    assert base.stations["S11"].baseline_cycle_time_seconds == 65.0
    assert rebalanced.stations["S11"].baseline_cycle_time_seconds == 72.0
    assert base.buffers["B10"].capacity == 4
    assert rebalanced.buffers["B10"].capacity == 3


def test_s22_is_explicitly_unchanged_and_adjustments_are_modest():
    base, rebalanced, plan = _configs()
    assert "S22" not in plan["cycle_time_overrides"]
    assert "S43" not in plan["cycle_time_overrides"]
    assert rebalanced.stations["S22"].baseline_cycle_time_seconds == base.stations["S22"].baseline_cycle_time_seconds
    assert rebalanced.stations["S43"].baseline_cycle_time_seconds == 55.0
    for station_id, change in plan["cycle_time_overrides"].items():
        pct = float(change["new_seconds"]) / float(change["old_seconds"]) - 1.0
        assert 0 < pct <= 0.20, station_id


def test_buffer_changes_are_selective_not_global():
    base, rebalanced, plan = _configs()
    assert len(plan["buffer_capacity_overrides"]) == 5
    assert len(plan["buffer_capacity_overrides"]) < len(base.buffers) / 5
    assert {buffer.capacity for buffer in rebalanced.buffers.values()} == {3, 4, 5}
    assert rebalanced.buffers["B20"].capacity == 5
    assert rebalanced.buffers["B21"].capacity == 4


def test_plan_rejects_stale_old_values():
    base, _, plan = _configs()
    altered = dict(plan)
    altered["cycle_time_overrides"] = {"S11": {**plan["cycle_time_overrides"]["S11"], "old_seconds": 64}}
    with pytest.raises(ValueError, match="old cycle mismatch"):
        apply_rebalance(base, altered)


def test_rebalanced_selected_headway_is_nominally_stable():
    _, rebalanced, _ = _configs()
    result = run_simulation(
        rebalanced,
        n_vehicles=200,
        seed=43001,
        mean_interarrival_seconds=102.5,
        std_interarrival_seconds=15.0,
    )
    assert result.summary["vehicles_completed"] == 200
    assert sum(result.summary["blocked_time_per_station"].values()) == 0.0
