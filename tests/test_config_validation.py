"""
Validation tests for the 12-station development factory configuration.

These same test functions are written generically against a loaded
FactoryConfig object, so they are intended to keep working unchanged
against the future 45-station configuration (only the fixture would need
to point at a different YAML file / expected station count).
"""

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.config.schemas import FactoryConfig, SensorMaturity

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


@pytest.fixture(scope="module")
def config() -> FactoryConfig:
    return load_factory_config(
        station_types_path=CONFIG_DIR / "station_types.yaml",
        line_path=CONFIG_DIR / "development_line.yaml",
    )


def test_loads_without_error(config: FactoryConfig):
    # Successfully constructing FactoryConfig already ran every
    # cross-reference validator in schemas.py's model_validator.
    assert config.line_name == "trusttwin_development_line_12"


def test_exact_station_count(config: FactoryConfig):
    assert len(config.stations) == 12


def test_station_ids_unique(config: FactoryConfig):
    ids = [s.station_id for s in config.stations.values()]
    assert len(ids) == len(set(ids))


def test_every_station_references_valid_type(config: FactoryConfig):
    for station in config.stations.values():
        assert station.station_type in config.station_types


def test_every_station_has_specific_operation(config: FactoryConfig):
    for station in config.stations.values():
        assert station.specific_operation.strip() != ""


def test_vehicle_variants_exist(config: FactoryConfig):
    assert set(config.vehicle_variants.keys()) == {"ICE_SEDAN", "ICE_SUV", "EV"}


def test_all_routes_reference_valid_stations(config: FactoryConfig):
    for variant in config.vehicle_variants.values():
        for station_id in variant.route:
            assert station_id in config.stations


def test_all_variants_reach_final_qc(config: FactoryConfig):
    for variant in config.vehicle_variants.values():
        assert variant.route[-1] == "S12"
        assert config.stations["S12"].station_type == "INSPECTION_EOL_TESTING"


def test_route_graph_has_no_cycles(config: FactoryConfig):
    # A cycle would have already raised during FactoryConfig construction;
    # this test additionally verifies each individual route is a simple
    # path with no repeated station.
    for variant in config.vehicle_variants.values():
        assert len(variant.route) == len(set(variant.route))


def test_buffers_reference_valid_stations(config: FactoryConfig):
    for buffer in config.buffers.values():
        assert buffer.upstream_station in config.stations
        assert buffer.downstream_station in config.stations


def test_buffer_ids_unique(config: FactoryConfig):
    assert len(config.buffers) == len(set(config.buffers.keys()))


def test_required_fields_present(config: FactoryConfig):
    for station in config.stations.values():
        assert station.station_name
        assert station.station_type
        assert station.baseline_cycle_time_seconds > 0
        assert station.sensor_maturity in SensorMaturity


def test_sensor_maturity_uses_valid_enum(config: FactoryConfig):
    valid = {m.value for m in SensorMaturity}
    for station in config.stations.values():
        assert station.sensor_maturity.value in valid


def test_sensors_compatible_with_station_type(config: FactoryConfig):
    for station in config.stations.values():
        station_type = config.station_types[station.station_type]
        justified = set((station.sensor_justifications or {}).keys())
        allowed = set(station_type.possible_sensor_families)
        for sensor in station.available_sensors:
            assert sensor in allowed or sensor in justified


def test_processing_times_positive(config: FactoryConfig):
    for station in config.stations.values():
        assert station.baseline_cycle_time_seconds > 0
        assert station.cycle_time_variability >= 0


def test_no_null_or_dangling_route_references(config: FactoryConfig):
    for variant in config.vehicle_variants.values():
        assert all(station_id for station_id in variant.route)
        for station_id in variant.processing_time_modifiers:
            assert station_id in config.stations


def test_sensor_maturity_distribution(config: FactoryConfig):
    counts = {SensorMaturity.RICH: 0, SensorMaturity.PARTIAL: 0, SensorMaturity.POOR: 0}
    for station in config.stations.values():
        counts[station.sensor_maturity] += 1
    assert counts[SensorMaturity.RICH] == 8
    assert counts[SensorMaturity.PARTIAL] == 3
    assert counts[SensorMaturity.POOR] == 1


def test_ev_skips_fuel_station(config: FactoryConfig):
    assert "S11" not in config.vehicle_variants["EV"].route
    assert "S11" in config.vehicle_variants["ICE_SEDAN"].route
    assert "S11" in config.vehicle_variants["ICE_SUV"].route


def test_buffer_model_supports_branching_and_merging(config: FactoryConfig):
    """The future SimPy simulator must not assume each station has exactly
    one upstream and one downstream neighbor. Prove the config already
    represents at least one branch (a station with >1 outgoing buffer) and
    one merge (a station with >1 incoming buffer), generically, not just by
    construction."""
    out_degree: dict = {}
    in_degree: dict = {}
    for buffer in config.buffers.values():
        out_degree[buffer.upstream_station] = out_degree.get(buffer.upstream_station, 0) + 1
        in_degree[buffer.downstream_station] = in_degree.get(buffer.downstream_station, 0) + 1

    assert any(count > 1 for count in out_degree.values()), (
        "expected at least one station with multiple outgoing buffers (a branch)"
    )
    assert any(count > 1 for count in in_degree.values()), (
        "expected at least one station with multiple incoming buffers (a merge)"
    )

    # document the specific known branch/merge point in this dev config
    assert out_degree.get("S10") == 2  # S10 -> S11 (ICE) and S10 -> S12 (EV)
    assert in_degree.get("S12") == 2  # S12 <- S11 (ICE) and S12 <- S10 (EV)


def test_variant_override_operation_profiles(config: FactoryConfig):
    marriage = config.stations["S07"].variant_overrides
    assert marriage["ICE_SEDAN"].operation_profile == "powertrain_marriage"
    assert marriage["ICE_SUV"].operation_profile == "powertrain_marriage"
    assert marriage["EV"].operation_profile == "battery_pack_marriage"
    assert marriage["EV"].cycle_time_multiplier != marriage["ICE_SEDAN"].cycle_time_multiplier


def test_variant_override_rejects_unknown_variant():
    from backend.config.schemas import (
        FactoryConfig,
        StationInstance,
        StationType,
        StationVariantOverride,
        VehicleVariant,
    )

    station_types = {
        "T1": StationType(
            type_id="T1", display_name="T1", process_family="f",
            possible_sensor_families=["cycle_time"],
        )
    }
    stations = {
        "S01": StationInstance(
            station_id="S01", station_name="A", station_type="T1",
            specific_operation="op", baseline_cycle_time_seconds=10,
            cycle_time_variability=0.1, sensor_maturity="rich",
            available_sensors=["cycle_time"],
            applicable_vehicle_variants=["V1"],
            variant_overrides={"GHOST_VARIANT": StationVariantOverride(operation_profile="x")},
        )
    }
    variants = {"V1": VehicleVariant(variant_id="V1", display_name="V1", route=["S01"])}
    try:
        FactoryConfig(
            line_name="bad", station_types=station_types, stations=stations,
            buffers={}, vehicle_variants=variants,
        )
        assert False, "expected ValueError for unknown variant in variant_overrides"
    except ValueError:
        pass


def test_applicable_variants_consistent_with_routes(config: FactoryConfig):
    """Extra consistency check beyond the required 15: a station's
    applicable_vehicle_variants should agree with which variants' routes
    actually pass through it, in both directions."""
    for station in config.stations.values():
        for variant_id in station.applicable_vehicle_variants:
            variant = config.vehicle_variants[variant_id]
            assert station.station_id in variant.route, (
                f"{station.station_id} lists {variant_id} as applicable "
                f"but {variant_id}'s route does not visit it"
            )
    for variant in config.vehicle_variants.values():
        for station_id in variant.route:
            station = config.stations[station_id]
            assert variant.variant_id in station.applicable_vehicle_variants, (
                f"{variant.variant_id}'s route visits {station_id} but that "
                f"station does not list {variant.variant_id} as applicable"
            )


def test_no_future_outcome_fields_leak_into_config(config: FactoryConfig):
    """Guard against accidentally encoding hidden future-outcome
    information into static station config (PRD Section 26)."""
    forbidden_substrings = ["defect_label", "future_", "scenario_id", "will_fail"]
    for station in config.stations.values():
        blob = " ".join(
            [station.station_name, station.specific_operation, station.notes or ""]
            + list(station.process_parameters.keys())
            + station.available_sensors
        ).lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in blob
