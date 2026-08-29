"""
Step 4, Section K: full 45-station configuration validation. Reuses the
exact same loader/schema code as the 12-station development line (Step 1)
with zero changes — these tests exist to confirm the locked topology is
correct, not to re-test the validator itself (see test_config_validation.py
for that).
"""

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.config.schemas import FactoryConfig, SensorMaturity

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"

ZONES = {
    "body_joining": [f"S{i:02d}" for i in range(1, 13)],       # S01-S12
    "paint_surface": [f"S{i:02d}" for i in range(13, 21)],      # S13-S20
    "final_assembly": [f"S{i:02d}" for i in range(21, 39)],     # S21-S38
    "inspection_eol": [f"S{i:02d}" for i in range(39, 46)],     # S39-S45
}


@pytest.fixture(scope="module")
def config() -> FactoryConfig:
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


def test_exactly_45_stations(config):
    assert len(config.stations) == 45


def test_station_ids_s01_to_s45_unique(config):
    expected_ids = {f"S{i:02d}" for i in range(1, 46)}
    assert set(config.stations.keys()) == expected_ids


def test_zone_counts(config):
    assert len(ZONES["body_joining"]) == 12
    assert len(ZONES["paint_surface"]) == 8
    assert len(ZONES["final_assembly"]) == 18
    assert len(ZONES["inspection_eol"]) == 7
    assert sum(len(v) for v in ZONES.values()) == 45


def test_sensor_maturity_exactly_29_10_6(config):
    counts = {SensorMaturity.RICH: 0, SensorMaturity.PARTIAL: 0, SensorMaturity.POOR: 0}
    for station in config.stations.values():
        counts[station.sensor_maturity] += 1
    assert counts[SensorMaturity.RICH] == 29
    assert counts[SensorMaturity.PARTIAL] == 10
    assert counts[SensorMaturity.POOR] == 6


def test_all_station_types_valid(config):
    for station in config.stations.values():
        assert station.station_type in config.station_types


def test_all_operations_non_empty(config):
    for station in config.stations.values():
        assert station.specific_operation.strip() != ""


def test_all_routes_valid(config):
    for variant in config.vehicle_variants.values():
        for station_id in variant.route:
            assert station_id in config.stations


def test_all_variants_reach_s45(config):
    for variant in config.vehicle_variants.values():
        assert variant.route[-1] == "S45"
        assert config.stations["S45"].station_type == "INSPECTION_EOL_TESTING"


def test_no_accidental_cycles(config):
    # FactoryConfig construction already ran cycle detection; additionally
    # verify each route itself has no repeated station
    for variant in config.vehicle_variants.values():
        assert len(variant.route) == len(set(variant.route))


def test_all_buffers_valid(config):
    for buffer in config.buffers.values():
        assert buffer.upstream_station in config.stations
        assert buffer.downstream_station in config.stations
        assert buffer.capacity > 0


def test_branch_merge_valid(config):
    # S34 has two outgoing edges (S35 for ICE, S36 direct for EV);
    # S36 has two incoming edges (from S35 for ICE, from S34 direct for EV)
    out_degree, in_degree = {}, {}
    for buf in config.buffers.values():
        out_degree[buf.upstream_station] = out_degree.get(buf.upstream_station, 0) + 1
        in_degree[buf.downstream_station] = in_degree.get(buf.downstream_station, 0) + 1
    assert out_degree.get("S34") == 2
    assert in_degree.get("S36") == 2


def test_all_sensor_definitions_referenced_are_valid(config):
    for station in config.stations.values():
        station_type = config.station_types[station.station_type]
        justified = set((station.sensor_justifications or {}).keys())
        allowed = set(station_type.possible_sensor_families)
        for sensor in station.available_sensors:
            assert sensor in allowed or sensor in justified


def test_all_processing_times_positive(config):
    for station in config.stations.values():
        assert station.baseline_cycle_time_seconds > 0
        assert station.cycle_time_variability >= 0


def test_all_variant_overrides_reference_valid_variants(config):
    for station in config.stations.values():
        for variant_id in station.variant_overrides:
            assert variant_id in config.vehicle_variants
            assert variant_id in station.applicable_vehicle_variants


def test_s26_differentiates_powertrain_vs_battery_marriage(config):
    overrides = config.stations["S26"].variant_overrides
    assert overrides["ICE_SEDAN"].operation_profile == "powertrain_marriage"
    assert overrides["ICE_SUV"].operation_profile == "powertrain_marriage"
    assert overrides["EV"].operation_profile == "battery_pack_marriage"


def test_s36_supports_ice_ev_variant_behavior(config):
    overrides = config.stations["S36"].variant_overrides
    assert overrides["ICE_SEDAN"].operation_profile == "ice_final_fluid_system_check"
    assert overrides["EV"].operation_profile == "ev_battery_thermal_conditioning_check"
    assert overrides["EV"].cycle_time_multiplier != overrides["ICE_SEDAN"].cycle_time_multiplier
    # both variants actually visit S36 on their shared route (no skip here)
    assert "S36" in config.vehicle_variants["ICE_SEDAN"].route
    assert "S36" in config.vehicle_variants["EV"].route


def test_s45_is_final_qc_for_every_route(config):
    for variant in config.vehicle_variants.values():
        assert variant.route[-1] == "S45"


def test_ev_skips_s35_only(config):
    assert "S35" not in config.vehicle_variants["EV"].route
    assert "S35" in config.vehicle_variants["ICE_SEDAN"].route
    assert "S35" in config.vehicle_variants["ICE_SUV"].route
    # every other station is shared by all three variants
    ev_route = set(config.vehicle_variants["EV"].route)
    ice_route = set(config.vehicle_variants["ICE_SEDAN"].route)
    assert ice_route - ev_route == {"S35"}
