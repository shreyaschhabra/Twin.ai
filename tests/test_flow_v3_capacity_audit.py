"""Phase-A tests for the runtime-derived Flow-v3 capacity audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.flow_v3.capacity_audit import (
    build_capacity_audit,
    summarize_utilization,
    variant_service_time,
    write_capacity_audit,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def config():
    return load_factory_config(ROOT / "configs" / "station_types.yaml", ROOT / "configs" / "full_line.yaml")


@pytest.fixture(scope="module")
def rows(config):
    return build_capacity_audit(config)


def _by_station(rows):
    return {row["station_id"]: row for row in rows}


def test_audit_covers_all_runtime_stations_and_bands(rows):
    assert len(rows) == 45
    assert len({row["station_id"] for row in rows}) == 45
    bands = summarize_utilization(rows)
    assert sum(band["station_count"] for band in bands) == 45
    assert sum(band["percentage"] for band in bands) == pytest.approx(100.0)


def test_variant_service_time_uses_runtime_override_precedence(config):
    assert variant_service_time(config, "S26", "ICE_SEDAN") == pytest.approx(72.0)
    assert variant_service_time(config, "S26", "ICE_SUV") == pytest.approx(79.2)
    assert variant_service_time(config, "S26", "EV") == pytest.approx(86.4)
    assert variant_service_time(config, "S22", "EV") == pytest.approx(101.2)


def test_route_skip_changes_s35_arrival_rate(rows):
    s35 = _by_station(rows)["S35"]
    assert s35["ev_service_time_seconds"] is None
    assert s35["station_visit_probability"] == pytest.approx(0.8)
    assert s35["nominal_station_arrival_headway_seconds"] == pytest.approx(143.75)
    assert s35["nominal_utilization_rho"] == pytest.approx(0.8 * 38.0 / 115.0)


def test_known_weighted_operating_points_are_derived_exactly(rows):
    stations = _by_station(rows)
    assert stations["S22"]["mix_weighted_service_time_seconds"] == pytest.approx(90.64)
    assert stations["S22"]["nominal_utilization_rho"] == pytest.approx(90.64 / 115.0)
    assert stations["S26"]["mix_weighted_service_time_seconds"] == pytest.approx(77.4)
    assert stations["S26"]["nominal_utilization_rho"] == pytest.approx(77.4 / 115.0)


def test_capacity_crossing_diagnostics_are_ordered_by_physical_burden(rows):
    for row in rows:
        assert row["background_micro_stops_rho_at_severity_0_9_if_targeted"] > row["nominal_utilization_rho"]
        assert row["flow_calibrated_micro_stops_rho_at_severity_0_95_if_targeted"] > row["background_micro_stops_rho_at_severity_0_9_if_targeted"]
        assert row["slowdown_multiplier_to_rho_1"] == pytest.approx(1.0 / row["nominal_utilization_rho"])


def test_scenario_capability_is_separated_from_target_applicability(rows):
    stations = _by_station(rows)
    assert stations["S26"]["manual_variation_capacity_crossing_possible_current_max"]
    assert not stations["S26"]["manual_variation_current_target"]
    assert stations["S26"]["flow_calibrated_micro_stops_current_target"]
    assert stations["S26"]["flow_calibrated_micro_stops_capacity_crossing_possible_current_max"]


def test_writer_creates_versioned_csv_and_markdown(rows, tmp_path):
    csv_path, markdown_path = write_capacity_audit(
        rows,
        tmp_path,
        starting_commit="02a01b4e663e32fe0316c7d1dbbba154016a5b38",
    )
    assert csv_path.name == "current_capacity_audit.csv"
    assert markdown_path.name == "current_capacity_audit.md"
    assert len(csv_path.read_text().splitlines()) == 46
    summary = markdown_path.read_text()
    assert "## Utilization distribution" in summary
    assert "S22" in summary
    assert "237 passed" in summary
