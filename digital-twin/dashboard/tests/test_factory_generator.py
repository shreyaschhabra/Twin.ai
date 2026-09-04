"""Demo factory generator tests.

The important property is not "looks plausible" but "the existing simulator would
accept it", so these assert the ConfigLoader rules directly.
"""

from __future__ import annotations

import pytest

from dashboard.factory.generator import (
    MAX_DEMO_STATIONS,
    MIN_DEMO_STATIONS,
    generate_demo_factory,
    is_demo_factory,
)
from dashboard.factory.validator import MAX_DARK_CORRIDOR_POLICY, validate_factory

SEEDS = [0, 1, 7, 42, 99, 100, 999, 12345]


@pytest.fixture(scope="module")
def factory() -> dict:
    return generate_demo_factory(seed=42)


class TestDeterminism:
    def test_same_seed_is_identical(self):
        assert generate_demo_factory(seed=99) == generate_demo_factory(seed=99)

    def test_different_seeds_differ(self):
        assert generate_demo_factory(seed=1) != generate_demo_factory(seed=2)

    def test_seed_is_recorded(self, factory: dict):
        assert factory["_seed"] == 42


class TestSimulatorContract:
    @pytest.mark.parametrize("seed", SEEDS)
    def test_no_validation_errors(self, seed: int):
        result = validate_factory(generate_demo_factory(seed=seed))
        assert result.errors == []

    @pytest.mark.parametrize("seed", SEEDS)
    def test_no_policy_warnings(self, seed: int):
        result = validate_factory(generate_demo_factory(seed=seed))
        assert result.warnings == []

    def test_ids_are_contiguous(self, factory: dict):
        ids = [station["id"] for station in factory["stations"]]
        assert ids == list(range(len(ids)))

    def test_source_and_sink_are_the_endpoints(self, factory: dict):
        stations = factory["stations"]
        assert stations[0].get("source") is True
        assert stations[-1].get("sink") is True
        assert all(not s.get("source") for s in stations[1:])
        assert all(not s.get("sink") for s in stations[:-1])

    @pytest.mark.parametrize("seed", SEEDS)
    def test_dark_zones_hold_no_inspection_stations(self, seed: int):
        generated = generate_demo_factory(seed=seed)
        archetypes = {s["id"]: s["archetype"] for s in generated["stations"]}
        for zone in generated["darkZones"]:
            span = range(zone["startStationId"], zone["endStationId"] + 1)
            assert all(archetypes[i] != "INSPECTION" for i in span)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_dark_zones_are_non_adjacent_and_ordered(self, seed: int):
        zones = generate_demo_factory(seed=seed)["darkZones"]
        for previous, current in zip(zones, zones[1:]):
            assert current["startStationId"] >= previous["endStationId"] + 2

    @pytest.mark.parametrize("seed", SEEDS)
    def test_checkpoints_carry_every_required_field(self, seed: int):
        for checkpoint in generate_demo_factory(seed=seed)["checkpoints"]:
            assert set(checkpoint) >= {"id", "stationId", "type", "progress", "reliability"}
            assert 0 < checkpoint["progress"] < 1
            assert 0 <= checkpoint["reliability"] <= 1

    def test_no_scaffolding_leaks_into_stations(self, factory: dict):
        assert all("_segment" not in station for station in factory["stations"])


class TestDemoShape:
    @pytest.mark.parametrize("seed", SEEDS)
    def test_station_count_in_range(self, seed: int):
        count = len(generate_demo_factory(seed=seed)["stations"])
        assert MIN_DEMO_STATIONS <= count <= MAX_DEMO_STATIONS

    @pytest.mark.parametrize("seed", SEEDS)
    def test_dark_corridor_length_capped(self, seed: int):
        for zone in generate_demo_factory(seed=seed)["darkZones"]:
            span = zone["endStationId"] - zone["startStationId"] + 1
            assert 2 <= span <= MAX_DARK_CORRIDOR_POLICY

    @pytest.mark.parametrize("seed", SEEDS)
    def test_has_light_and_dark_areas(self, seed: int):
        generated = generate_demo_factory(seed=seed)
        dark = {
            index
            for zone in generated["darkZones"]
            for index in range(zone["startStationId"], zone["endStationId"] + 1)
        }
        assert len(generated["darkZones"]) >= 2
        assert dark
        assert len(dark) < len(generated["stations"])

    @pytest.mark.parametrize("seed", SEEDS)
    def test_mixed_archetypes(self, seed: int):
        archetypes = {s["archetype"] for s in generate_demo_factory(seed=seed)["stations"]}
        assert archetypes == {"AUTOMATED", "MANUAL", "INSPECTION"}

    @pytest.mark.parametrize("seed", SEEDS)
    def test_uneven_sensor_coverage(self, seed: int):
        stations = generate_demo_factory(seed=seed)["stations"]
        counts = {level: 0 for level in ("HIGH", "PARTIAL", "NONE")}
        for station in stations:
            counts[station["sensorCoverage"]] += 1
        assert all(count > 0 for count in counts.values())
        # "uneven" means genuinely lopsided, not a near-even split.
        assert max(counts.values()) > min(counts.values()) * 1.5

    @pytest.mark.parametrize("seed", SEEDS)
    def test_every_dark_corridor_contains_an_unobserved_manual_station(self, seed: int):
        generated = generate_demo_factory(seed=seed)
        by_id = {s["id"]: s for s in generated["stations"]}
        for zone in generated["darkZones"]:
            span = range(zone["startStationId"], zone["endStationId"] + 1)
            assert any(
                by_id[i]["archetype"] == "MANUAL" and by_id[i]["sensorCoverage"] == "NONE"
                for i in span
            )

    @pytest.mark.parametrize("seed", SEEDS)
    def test_manual_stations_are_unobserved(self, seed: int):
        for station in generate_demo_factory(seed=seed)["stations"]:
            if station["archetype"] == "MANUAL":
                assert station["sensorCoverage"] == "NONE"

    @pytest.mark.parametrize("seed", SEEDS)
    def test_parameters_vary_between_stations(self, seed: int):
        stations = generate_demo_factory(seed=seed)["stations"]
        assert len({s["meanCycleTimeMs"] for s in stations}) > 5
        assert len({s["bufferCapacity"] for s in stations}) > 1


class TestDemoMarking:
    def test_marked_as_demo(self, factory: dict):
        assert factory["_demo"] is True
        assert factory["_generated_by"] == "dashboard.factory.generator"
        assert "demo" in factory["_note"].lower()

    def test_is_demo_factory_detects_marker(self, factory: dict):
        assert is_demo_factory(factory) is True

    def test_is_demo_factory_rejects_plain_factory(self):
        assert is_demo_factory({"stations": []}) is False
