"""Validator tests: the dashboard's mirror of simulation/src/ConfigLoader.cpp."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.factory.validator import (
    MAX_DARK_CORRIDOR_POLICY,
    is_valid_factory,
    validate_factory,
    validate_factory_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_FACTORY = PROJECT_ROOT / "simulation" / "config" / "factory.json"


def _factory(station_count: int = 8) -> dict:
    stations = []
    for index in range(station_count):
        station = {
            "id": index,
            "name": f"Station {index}",
            "archetype": "AUTOMATED",
            "meanCycleTimeMs": 40_000,
            "cycleTimeCV": 0.1,
            "bufferCapacity": 4,
            "sensorCoverage": "HIGH",
        }
        if index == 0:
            station["source"] = True
            station["bufferCapacity"] = 0
        if index == station_count - 1:
            station["sink"] = True
        stations.append(station)
    return {"stations": stations}


def _zone(start: int, end: int, zone_id: str = "DZ_01") -> dict:
    return {
        "id": zone_id,
        "name": "Test Corridor",
        "startStationId": start,
        "endStationId": end,
        "observability": {"sensorTelemetry": True, "manualChecks": True, "checkpoints": True},
    }


def _checkpoint(station_id: int, checkpoint_id: str = "CP_01") -> dict:
    return {
        "id": checkpoint_id,
        "stationId": station_id,
        "type": "RFID",
        "progress": 0.5,
        "reliability": 0.9,
        "falsePositiveRate": 0.01,
        "identifiesUnit": True,
    }


class TestBaseline:
    def test_minimal_factory_is_valid(self):
        assert validate_factory(_factory()).ok

    def test_is_valid_convenience(self):
        assert is_valid_factory(_factory()) is True

    def test_result_is_truthy_when_ok(self):
        assert bool(validate_factory(_factory())) is True

    def test_repository_factory_is_valid(self):
        """The repository's own factory.json must never be reported as INVALID."""
        result = validate_factory_file(REPO_FACTORY)
        assert result.ok, result.errors

    def test_repository_factory_long_corridor_is_a_warning_not_an_error(self):
        """DZ_BODY_01 spans 4 stations: a demo-policy warning, not a simulator error."""
        result = validate_factory_file(REPO_FACTORY)
        assert result.errors == []
        assert any(str(MAX_DARK_CORRIDOR_POLICY) in w for w in result.warnings)


class TestStationRules:
    def test_missing_stations_key(self):
        assert not validate_factory({}).ok

    def test_non_dict_payload(self):
        assert not validate_factory("nope").ok

    def test_fewer_than_three_stations(self):
        factory = _factory(3)
        factory["stations"] = factory["stations"][:2]
        assert not validate_factory(factory).ok

    def test_non_contiguous_ids(self):
        factory = _factory()
        factory["stations"][3]["id"] = 99
        result = validate_factory(factory)
        assert not result.ok

    def test_duplicate_ids(self):
        factory = _factory()
        factory["stations"][3]["id"] = 2
        assert not validate_factory(factory).ok

    def test_first_station_must_be_source(self):
        factory = _factory()
        del factory["stations"][0]["source"]
        result = validate_factory(factory)
        assert any("source" in error for error in result.errors)

    def test_last_station_must_be_sink(self):
        factory = _factory()
        del factory["stations"][-1]["sink"]
        result = validate_factory(factory)
        assert any("sink" in error for error in result.errors)

    def test_interior_source_is_rejected(self):
        factory = _factory()
        factory["stations"][3]["source"] = True
        result = validate_factory(factory)
        assert any("source" in error for error in result.errors)

    def test_invalid_archetype(self):
        factory = _factory()
        factory["stations"][2]["archetype"] = "ROBOTIC"
        assert any("archetype" in e for e in validate_factory(factory).errors)

    def test_invalid_sensor_coverage(self):
        factory = _factory()
        factory["stations"][2]["sensorCoverage"] = "FULL"
        assert any("sensorCoverage" in e for e in validate_factory(factory).errors)

    def test_non_positive_cycle_time(self):
        factory = _factory()
        factory["stations"][2]["meanCycleTimeMs"] = 0
        assert not validate_factory(factory).ok

    def test_negative_buffer_capacity(self):
        factory = _factory()
        factory["stations"][2]["bufferCapacity"] = -1
        assert not validate_factory(factory).ok

    def test_zero_cv_is_allowed(self):
        """ConfigLoader rejects cycleTimeCV < 0, not == 0."""
        factory = _factory()
        factory["stations"][2]["cycleTimeCV"] = 0
        assert validate_factory(factory).ok


class TestDarkZoneRules:
    def test_two_station_corridor_is_valid(self):
        factory = _factory()
        factory["darkZones"] = [_zone(2, 3)]
        assert validate_factory(factory).ok

    def test_single_station_corridor_is_rejected(self):
        """ConfigLoader requires startStationId < endStationId."""
        factory = _factory()
        factory["darkZones"] = [_zone(2, 2)]
        assert not validate_factory(factory).ok

    def test_reversed_corridor_is_rejected(self):
        factory = _factory()
        factory["darkZones"] = [_zone(4, 2)]
        assert not validate_factory(factory).ok

    def test_corridor_may_not_start_at_source(self):
        factory = _factory()
        factory["darkZones"] = [_zone(0, 2)]
        assert not validate_factory(factory).ok

    def test_corridor_may_not_reach_the_sink_boundary(self):
        factory = _factory(8)
        factory["darkZones"] = [_zone(5, 7)]
        assert not validate_factory(factory).ok

    def test_adjacent_corridors_are_rejected(self):
        factory = _factory(12)
        factory["darkZones"] = [_zone(1, 2, "DZ_A"), _zone(3, 4, "DZ_B")]
        result = validate_factory(factory)
        assert any("non-adjacent" in error for error in result.errors)

    def test_separated_corridors_are_accepted(self):
        factory = _factory(12)
        factory["darkZones"] = [_zone(1, 2, "DZ_A"), _zone(4, 5, "DZ_B")]
        assert validate_factory(factory).ok

    def test_inspection_station_inside_corridor_is_rejected(self):
        factory = _factory()
        factory["stations"][3]["archetype"] = "INSPECTION"
        factory["darkZones"] = [_zone(2, 3)]
        result = validate_factory(factory)
        assert any("INSPECTION" in error for error in result.errors)

    def test_missing_name_is_rejected(self):
        factory = _factory()
        zone = _zone(2, 3)
        del zone["name"]
        factory["darkZones"] = [zone]
        assert any("name" in e for e in validate_factory(factory).errors)

    def test_missing_observability_is_rejected(self):
        factory = _factory()
        zone = _zone(2, 3)
        del zone["observability"]
        factory["darkZones"] = [zone]
        assert any("observability" in e for e in validate_factory(factory).errors)

    def test_unknown_station_reference_is_rejected(self):
        factory = _factory()
        factory["darkZones"] = [_zone(2, 99)]
        assert not validate_factory(factory).ok

    def test_long_corridor_is_a_warning_only(self):
        factory = _factory(12)
        factory["darkZones"] = [_zone(1, 5)]
        result = validate_factory(factory)
        assert result.ok
        assert result.warnings


class TestCheckpointRules:
    def test_valid_checkpoint(self):
        factory = _factory()
        factory["checkpoints"] = [_checkpoint(3)]
        assert validate_factory(factory).ok

    def test_progress_is_required(self):
        factory = _factory()
        checkpoint = _checkpoint(3)
        del checkpoint["progress"]
        factory["checkpoints"] = [checkpoint]
        assert any("progress" in e for e in validate_factory(factory).errors)

    def test_reliability_is_required(self):
        factory = _factory()
        checkpoint = _checkpoint(3)
        del checkpoint["reliability"]
        factory["checkpoints"] = [checkpoint]
        assert any("reliability" in e for e in validate_factory(factory).errors)

    @pytest.mark.parametrize("progress", [0, 1, 1.5, -0.1])
    def test_progress_must_be_strictly_between_zero_and_one(self, progress):
        factory = _factory()
        checkpoint = _checkpoint(3)
        checkpoint["progress"] = progress
        factory["checkpoints"] = [checkpoint]
        assert not validate_factory(factory).ok

    def test_unknown_type_is_rejected(self):
        factory = _factory()
        checkpoint = _checkpoint(3)
        checkpoint["type"] = "BARCODE"
        factory["checkpoints"] = [checkpoint]
        assert not validate_factory(factory).ok

    def test_duplicate_ids_are_rejected(self):
        factory = _factory()
        factory["checkpoints"] = [_checkpoint(2, "CP"), _checkpoint(3, "CP")]
        assert not validate_factory(factory).ok

    def test_unknown_station_is_rejected(self):
        factory = _factory()
        factory["checkpoints"] = [_checkpoint(99)]
        assert not validate_factory(factory).ok


class TestFileValidation:
    def test_missing_file(self, tmp_path: Path):
        result = validate_factory_file(tmp_path / "absent.json")
        assert not result.ok
        assert "not found" in result.errors[0]

    def test_malformed_json(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text("{not json", encoding="utf-8")
        result = validate_factory_file(path)
        assert not result.ok
        assert "valid JSON" in result.errors[0]

    def test_valid_file(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text(json.dumps(_factory()), encoding="utf-8")
        assert validate_factory_file(path).ok
