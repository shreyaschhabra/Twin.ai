from pathlib import Path

from backend.config.loader import load_factory_config
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_capability_v2 import build_scenario_capability_matrix_v2

ROOT = Path(__file__).resolve().parent.parent


def _rows():
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))
    return build_scenario_capability_matrix_v2(config)


def test_matrix_has_unique_valid_station_mechanism_severity_profile_rows():
    rows = _rows()
    keys = {(r["station_id"], r["mechanism"], r["severity"], r["profile"]) for r in rows}
    assert len(keys) == len(rows)
    assert rows


def test_every_row_has_required_physics_fields_and_ignores_buffer_for_capability():
    required = {
        "baseline_rho", "expected_effective_service_time_seconds", "effective_rho",
        "expected_demand_service_deficit_vehicles_per_hour", "scenario_duration_minutes",
        "scenario_duration_station_cycles", "buffer_capacity",
        "theoretical_time_to_fill_minutes_if_deficit_persists", "classification",
    }
    for row in _rows():
        assert required <= set(row)
        assert row["buffer_used_to_determine_capability"] is False
        assert row["scenario_duration_minutes"] <= 90.0


def test_mix_is_never_forced_positive_and_degradation_is_unseen_only():
    rows = _rows()
    mix = [r for r in rows if r["mechanism"] == "VEHICLE_MIX_OVERLOAD"]
    assert not any(r["classification"] == "POSITIVE_CAPABLE" for r in mix)
    degradation = [r for r in rows if r["mechanism"] == "EQUIPMENT_DEGRADATION"]
    assert degradation and {r["supervision_role"] for r in degradation} == {"UNSEEN_ONLY"}


def test_supervised_physics_has_three_capable_mechanisms_and_cross_zone_stations():
    rows = _rows()
    capable = [
        r for r in rows
        if r["supervision_role"] == "SUPERVISED" and r["classification"] == "POSITIVE_CAPABLE"
    ]
    assert {r["mechanism"] for r in capable} >= {"MANUAL_VARIATION", "MICRO_STOPS", "ARRIVAL_BURST"}
    assert {r["zone"] for r in capable} >= {"body_joining", "paint_surface", "final_assembly"}
    assert len({r["station_id"] for r in capable}) >= 6
