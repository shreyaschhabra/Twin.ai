"""
Step 4, Section AJ: simulation + sensor + QC tests on the full 45-station
line. Complements test_full_line_config.py (pure config validation) with
actual simulation runs.
"""

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.material_batches import load_batch_relevant_stations
from backend.simulation.qc import QCParameters
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
SEED = 42
N_VEHICLES = 200
MEAN_INTERARRIVAL = 115.0
STD_INTERARRIVAL = 15.0


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


@pytest.fixture(scope="module")
def sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")


@pytest.fixture(scope="module")
def batch_relevant_stations():
    return load_batch_relevant_stations(CONFIG_DIR / "material_batches_full.yaml")


@pytest.fixture(scope="module")
def result(config, sensor_models, batch_relevant_stations):
    return run_simulation(
        config, n_vehicles=N_VEHICLES, seed=SEED,
        mean_interarrival_seconds=MEAN_INTERARRIVAL, std_interarrival_seconds=STD_INTERARRIVAL,
        sensor_models=sensor_models, batch_relevant_stations=batch_relevant_stations,
        qc_station_id="S45", qc_params=QCParameters(),
    )


# ---- simulation ----

def test_nominal_full_line_run_completes(result):
    assert result.summary["vehicles_completed"] == result.summary["vehicles_generated"] == N_VEHICLES


def test_no_station_capacity_violation(config, result):
    # every station is capacity=1; StationRuntime already enforces this at
    # construction (raises NotImplementedError otherwise) — confirm no
    # vehicle is ever processed at two stations simultaneously
    for vehicle_id, visits in result.genealogy.items():
        intervals = sorted((v.processing_start_time, v.processing_completion_time) for v in visits)
        for (s1, e1), (s2, e2) in zip(intervals, intervals[1:]):
            assert e1 <= s2


def test_blocked_transitions_correspond_to_genuinely_full_buffers(config, sensor_models):
    """Step 4 patch 1 invariant: every BLOCKED transition must carry a
    buffer_id/occupancy that shows the named buffer was ACTUALLY at its
    configured capacity at that instant — proving BLOCKED is never
    entered for any other reason. This was previously only reconstructable
    by hand-joining genealogy against events; the event itself now says
    so directly.

    The plain nominal `result` fixture is paced NOT to saturate (by
    design — see ASSUMPTIONS.md), so it reliably shows zero blocking;
    this test deliberately forces a slowdown severe enough to guarantee
    at least one real BLOCKED episode to check the invariant against."""
    from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily

    scenario = ScenarioDefinition(
        scenario_id="force_block_s19", family=ScenarioFamily.MANUAL_VARIATION,
        station_ids=["S19"], start_time=0, duration=100000, severity=0.9,
        params={"cycle_time_multiplier": 4.0, "variability_multiplier": 1.0},
    )
    forced = run_simulation(
        config, n_vehicles=N_VEHICLES, seed=SEED,
        mean_interarrival_seconds=MEAN_INTERARRIVAL, std_interarrival_seconds=STD_INTERARRIVAL,
        sensor_models=sensor_models, scenarios=[scenario],
    )

    blocked = [e for e in forced.events
               if e.event_type == EventType.STATION_STATE_CHANGED.value and e.to_state == "BLOCKED"]
    assert len(blocked) > 0, "expected at least one BLOCKED episode in this run"
    for e in blocked:
        assert e.vehicle_id is not None
        assert e.buffer_id is not None
        assert e.occupancy is not None
        capacity = config.buffers[e.buffer_id].capacity
        assert e.occupancy == capacity, (
            f"BLOCKED at {e.station_id} for buffer {e.buffer_id} recorded occupancy "
            f"{e.occupancy} but capacity is {capacity} — buffer was not actually full"
        )


def test_no_buffer_capacity_violation(config, result):
    occupancy = {bid: 0 for bid in config.buffers}
    for e in result.events:
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value and e.buffer_id in occupancy:
            occupancy[e.buffer_id] += 1
            assert occupancy[e.buffer_id] <= config.buffers[e.buffer_id].capacity
        elif e.event_type == EventType.VEHICLE_LEFT_BUFFER.value and e.buffer_id in occupancy:
            occupancy[e.buffer_id] -= 1


def test_no_vehicle_duplication(result):
    ids = list(result.vehicles.keys())
    assert len(ids) == len(set(ids))


def test_genealogy_valid_for_full_line(result):
    for vehicle_id, visits in result.genealogy.items():
        stations = [v.station_id for v in visits]
        assert len(stations) == len(set(stations))
        for visit in visits:
            assert visit.entry_time <= visit.processing_start_time <= visit.processing_completion_time <= visit.exit_time


def test_ev_ice_route_differences_correct(config, result):
    for vehicle in result.vehicles.values():
        visited = [v.station_id for v in result.genealogy[vehicle.vehicle_id]]
        if vehicle.variant_id == "EV":
            assert "S35" not in visited
        else:
            assert "S35" in visited
        assert visited[-1] == "S45"


def test_s26_variant_operation_semantics(result):
    # indirect check: S26 processing times differ systematically by
    # variant due to variant_overrides (EV multiplier 1.20 vs ICE 1.0/1.10)
    import statistics
    times_by_variant = {"ICE_SEDAN": [], "ICE_SUV": [], "EV": []}
    for vehicle in result.vehicles.values():
        visit = next(v for v in result.genealogy[vehicle.vehicle_id] if v.station_id == "S26")
        times_by_variant[vehicle.variant_id].append(visit.processing_time)
    assert statistics.mean(times_by_variant["EV"]) > statistics.mean(times_by_variant["ICE_SEDAN"]) * 1.05


def test_s36_variant_operation_semantics(result):
    import statistics
    times_by_variant = {"ICE_SEDAN": [], "EV": []}
    for vehicle in result.vehicles.values():
        if vehicle.variant_id not in times_by_variant:
            continue
        visit = next(v for v in result.genealogy[vehicle.vehicle_id] if v.station_id == "S36")
        times_by_variant[vehicle.variant_id].append(visit.processing_time)
    assert statistics.mean(times_by_variant["EV"]) > statistics.mean(times_by_variant["ICE_SEDAN"]) * 1.05


# ---- sensors ----

def test_full_sensor_definitions_valid(sensor_models, config):
    for (station_id, sensor_name) in sensor_models:
        assert station_id in config.stations
        assert sensor_name in config.stations[station_id].available_sensors


def test_full_line_sensor_observability_by_maturity(result):
    def sensor_names(station_id):
        return {e.sensor_name for e in result.events
                if e.event_type == EventType.SENSOR_READING.value and e.station_id == station_id}

    assert sensor_names("S01") == {"weld_current", "weld_time", "electrode_force"}  # rich
    assert sensor_names("S05") == {"adhesive_flow_rate"}  # partial
    assert sensor_names("S11") == {"checklist_completion"}  # poor


def test_full_line_sensor_values_reproducible(config, sensor_models, batch_relevant_stations):
    r1 = run_simulation(config, n_vehicles=50, seed=5, sensor_models=sensor_models,
                         mean_interarrival_seconds=MEAN_INTERARRIVAL, std_interarrival_seconds=STD_INTERARRIVAL)
    r2 = run_simulation(config, n_vehicles=50, seed=5, sensor_models=sensor_models,
                         mean_interarrival_seconds=MEAN_INTERARRIVAL, std_interarrival_seconds=STD_INTERARRIVAL)
    v1 = [(e.station_id, e.sensor_name, e.value) for e in r1.events if e.event_type == EventType.SENSOR_READING.value]
    v2 = [(e.station_id, e.sensor_name, e.value) for e in r2.events if e.event_type == EventType.SENSOR_READING.value]
    assert v1 == v2


# ---- QC ----

def test_qc_event_occurs_only_at_configured_station(result):
    qc_events = [e for e in result.events if e.event_type == EventType.QC_RESULT_RECORDED.value]
    assert len(qc_events) > 0
    assert all(e.station_id == "S45" for e in qc_events)


def test_exactly_one_qc_result_per_completed_vehicle(result):
    qc_events = [e for e in result.events if e.event_type == EventType.QC_RESULT_RECORDED.value]
    vehicle_ids = [e.vehicle_id for e in qc_events]
    assert len(vehicle_ids) == len(set(vehicle_ids)) == len(result.vehicles)


def test_qc_result_never_appears_before_s45(result):
    qc_times = {e.vehicle_id: e.simulation_time for e in result.events
                if e.event_type == EventType.QC_RESULT_RECORDED.value}
    for vehicle_id, visits in result.genealogy.items():
        for visit in visits:
            if visit.station_id == "S45":
                continue
            assert visit.exit_time <= qc_times[vehicle_id]


def test_same_seed_reproduces_qc_outcomes(config, sensor_models):
    r1 = run_simulation(config, n_vehicles=100, seed=11, sensor_models=sensor_models, qc_station_id="S45")
    r2 = run_simulation(config, n_vehicles=100, seed=11, sensor_models=sensor_models, qc_station_id="S45")
    qc1 = [(e.vehicle_id, e.qc_result) for e in r1.events if e.event_type == EventType.QC_RESULT_RECORDED.value]
    qc2 = [(e.vehicle_id, e.qc_result) for e in r2.events if e.event_type == EventType.QC_RESULT_RECORDED.value]
    assert qc1 == qc2


def test_unrelated_rng_drains_do_not_alter_qc_outcomes(config, sensor_models):
    from backend.simulation.engine import FactoryEngine

    engine_a = FactoryEngine(config, seed=22, sensor_models=sensor_models, qc_station_id="S45")
    result_a = engine_a.run(n_vehicles=80, mean_interarrival_seconds=115.0, std_interarrival_seconds=15.0)

    engine_b = FactoryEngine(config, seed=22, sensor_models=sensor_models, qc_station_id="S45")
    for _ in range(500):
        engine_b.rng_factory.get("sensor_noise::S99::hypothetical").random()
        engine_b.rng_factory.get("micro_stop::S99").random()
    result_b = engine_b.run(n_vehicles=80, mean_interarrival_seconds=115.0, std_interarrival_seconds=15.0)

    qc_a = [(e.vehicle_id, e.qc_result) for e in result_a.events if e.event_type == EventType.QC_RESULT_RECORDED.value]
    qc_b = [(e.vehicle_id, e.qc_result) for e in result_b.events if e.event_type == EventType.QC_RESULT_RECORDED.value]
    assert qc_a == qc_b


def test_qc_mapping_is_probabilistic_not_deterministic(config, sensor_models):
    from backend.simulation.qc import QCOutcomeGenerator, QCParameters
    import random

    gen = QCOutcomeGenerator(QCParameters(), random.Random(0))
    p_zero = gen.compute_probability(0.0)
    p_high = gen.compute_probability(0.3)
    assert 0 < p_zero < 1
    assert 0 < p_high < 1
    assert p_high > p_zero  # monotonic
    assert p_high < 1.0  # never guaranteed, per requirement 3
    assert p_zero > 0.0   # non-zero background, per requirement 2


# ---- leakage (full-line specific) ----

def test_no_prohibited_fields_on_full_line_events(result):
    from backend.simulation.scenarios.latent import PROHIBITED_OBSERVABLE_FIELDS
    event_field_names = {f for e in result.events for f in e.__dict__.keys()}
    assert event_field_names.isdisjoint(PROHIBITED_OBSERVABLE_FIELDS)


def test_scenario_truth_physically_separated(result):
    assert result.latent_truth is not None
    assert not any(hasattr(e, "family") for e in result.events)


def test_batch_health_truth_absent(config, sensor_models, batch_relevant_stations):
    from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily

    scenario = ScenarioDefinition(
        scenario_id="bad_b1001", family=ScenarioFamily.BAD_BATCH,
        station_ids=["S05"], start_time=0, duration=None, severity=0.5,
        affected_batch_id="B1001", params={"quality_weight_per_visit": 0.2},
    )
    result_bad = run_simulation(
        config, n_vehicles=100, seed=1, sensor_models=sensor_models,
        batch_relevant_stations=batch_relevant_stations, scenarios=[scenario],
    )
    for e in result_bad.events:
        blob = str(e.__dict__).lower()
        assert "is_bad" not in blob and "bad_batch_truth" not in blob
