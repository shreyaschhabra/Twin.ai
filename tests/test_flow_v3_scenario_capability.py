from pathlib import Path

from backend.config.loader import load_factory_config
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_capability import MECHANISMS, build_scenario_capability_matrix

ROOT = Path(__file__).resolve().parent.parent


def _matrix():
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))
    return build_scenario_capability_matrix(config)


def test_matrix_covers_every_station_mechanism_and_finalist_headway():
    rows = _matrix()
    assert len(rows) == 45 * len(MECHANISMS) * 3
    keys = {(r["headway_seconds"], r["station_id"], r["mechanism"]) for r in rows}
    assert len(keys) == len(rows)


def test_buffer_capacity_is_never_used_for_capability():
    assert all(row["buffer_capacity_used_in_classification"] is False for row in _matrix())


def test_manual_and_microstop_applicability_are_semantic():
    rows = [row for row in _matrix() if row["headway_seconds"] == 102.5]
    lookup = {(r["station_id"], r["mechanism"]): r for r in rows}
    assert lookup[("S11", "MANUAL_VARIATION")]["applicable"]
    assert not lookup[("S11", "MICRO_STOPS")]["applicable"]
    assert lookup[("S20", "MICRO_STOPS")]["applicable"]
    assert not lookup[("S20", "MANUAL_VARIATION")]["applicable"]


def test_s22_cycle_is_not_increased_but_remains_physically_visible():
    rows = [
        row for row in _matrix()
        if row["headway_seconds"] == 100.0 and row["station_id"] == "S22"
    ]
    assert {row["baseline_rho"] for row in rows} == {90.64 / 100.0}
