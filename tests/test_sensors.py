"""
Sensor sanity tests (Step 3, Section U).
"""

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
SEED = 7
N_VEHICLES = 30


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml")


@pytest.fixture(scope="module")
def sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models.yaml")


@pytest.fixture(scope="module")
def result(config, sensor_models):
    return run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models)


def readings(result, station_id=None):
    events = [e for e in result.events if e.event_type == EventType.SENSOR_READING.value]
    if station_id:
        events = [e for e in events if e.station_id == station_id]
    return events


def test_rich_station_produces_full_sensor_set(result):
    names = {r.sensor_name for r in readings(result, "S01")}
    assert names == {"weld_current", "weld_time", "electrode_force"}


def test_partial_station_produces_only_allowed_subset(result):
    names = {r.sensor_name for r in readings(result, "S03")}
    assert names == {"adhesive_flow_rate"}


def test_poor_station_does_not_expose_rich_telemetry(result):
    names = {r.sensor_name for r in readings(result, "S09")}
    assert names == {"checklist_completion"}
    # explicitly nothing resembling a continuous process sensor
    assert "torque_value" not in names and "weld_current" not in names


def test_sensor_values_finite_when_available(result):
    for r in readings(result):
        if r.measurement_status == "available":
            assert r.value is not None
            assert r.value == r.value  # not NaN
            assert abs(r.value) != float("inf")


def test_missing_values_only_with_appropriate_status(result):
    for r in readings(result):
        if r.value is None:
            assert r.measurement_status in ("missing",)


def test_sensor_timestamps_chronological_per_station_sensor(result):
    from collections import defaultdict
    by_key = defaultdict(list)
    for r in readings(result):
        by_key[(r.station_id, r.sensor_name)].append(r.simulation_time)
    for key, times in by_key.items():
        assert times == sorted(times)


def test_sensor_station_references_valid(config, result):
    for r in readings(result):
        assert r.station_id in config.stations


def test_units_consistent_for_same_sensor_definition(result):
    from collections import defaultdict
    units = defaultdict(set)
    for r in readings(result):
        units[(r.station_id, r.sensor_name)].add(r.unit)
    for key, unit_set in units.items():
        assert len(unit_set) == 1


def test_same_seed_reproduces_sensor_values(config, sensor_models):
    r1 = run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models)
    r2 = run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models)
    v1 = [(r.station_id, r.sensor_name, r.simulation_time, r.value) for r in readings(r1)]
    v2 = [(r.station_id, r.sensor_name, r.simulation_time, r.value) for r in readings(r2)]
    assert v1 == v2


def test_draining_unrelated_rng_stream_does_not_change_sensor_sequence(config, sensor_models):
    from backend.simulation.engine import FactoryEngine

    engine_a = FactoryEngine(config, seed=SEED, sensor_models=sensor_models)
    result_a = engine_a.run(n_vehicles=N_VEHICLES, mean_interarrival_seconds=200.0, std_interarrival_seconds=20.0)

    engine_b = FactoryEngine(config, seed=SEED, sensor_models=sensor_models)
    for _ in range(300):
        engine_b.rng_factory.get("sensor_noise::S99::hypothetical_future_sensor").random()
    result_b = engine_b.run(n_vehicles=N_VEHICLES, mean_interarrival_seconds=200.0, std_interarrival_seconds=20.0)

    v_a = [(r.station_id, r.sensor_name, r.simulation_time, r.value) for r in readings(result_a)]
    v_b = [(r.station_id, r.sensor_name, r.simulation_time, r.value) for r in readings(result_b)]
    assert v_a == v_b
