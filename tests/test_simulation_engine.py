"""
Step 2 required tests, run against the nominal 12-station development
simulation. Controlled blocking/starvation tests live separately in
tests/test_simulation_controlled.py since a healthy nominal run isn't
expected to reliably exercise those paths (see engine docs / ASSUMPTIONS.md
on arrival pacing near the S06 bottleneck).
"""

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.config.schemas import FactoryConfig
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
NOMINAL_SEED = 42
NOMINAL_N = 80


@pytest.fixture(scope="module")
def config() -> FactoryConfig:
    return load_factory_config(
        CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml"
    )


@pytest.fixture(scope="module")
def nominal_run(config):
    return run_simulation(config, n_vehicles=NOMINAL_N, seed=NOMINAL_SEED)


# ---- configuration independence -------------------------------------------------

def test_simulator_uses_config_not_hardcoded_stations(config, nominal_run):
    # every station that actually processed a vehicle is one that exists in
    # config, and every configured station appears — nothing hardcoded
    stations_seen = {e.station_id for e in nominal_run.events if e.station_id}
    assert stations_seen <= set(config.stations.keys())
    assert stations_seen == set(config.stations.keys())  # all 12 exercised


# ---- vehicle routing --------------------------------------------------------------

def test_ice_sedan_follows_valid_route(config, nominal_run):
    expected = config.vehicle_variants["ICE_SEDAN"].route
    for vehicle in nominal_run.vehicles.values():
        if vehicle.variant_id == "ICE_SEDAN":
            visited = [v.station_id for v in nominal_run.genealogy[vehicle.vehicle_id]]
            assert visited == expected


def test_ice_suv_follows_valid_route(config, nominal_run):
    expected = config.vehicle_variants["ICE_SUV"].route
    for vehicle in nominal_run.vehicles.values():
        if vehicle.variant_id == "ICE_SUV":
            visited = [v.station_id for v in nominal_run.genealogy[vehicle.vehicle_id]]
            assert visited == expected


def test_ev_skips_s11(nominal_run):
    ev_vehicles = [v for v in nominal_run.vehicles.values() if v.variant_id == "EV"]
    assert len(ev_vehicles) > 0
    for vehicle in ev_vehicles:
        visited = [v.station_id for v in nominal_run.genealogy[vehicle.vehicle_id]]
        assert "S11" not in visited


def test_every_completed_vehicle_ends_at_s12(nominal_run):
    for vehicle in nominal_run.vehicles.values():
        assert vehicle.completed
        visits = nominal_run.genealogy[vehicle.vehicle_id]
        assert visits[-1].station_id == "S12"


# ---- vehicle integrity --------------------------------------------------------------

def test_vehicle_ids_unique(nominal_run):
    ids = list(nominal_run.vehicles.keys())
    assert len(ids) == len(set(ids))


def test_no_vehicle_processed_at_two_stations_simultaneously(nominal_run):
    # for each vehicle, processing intervals across its genealogy must not overlap
    for vehicle_id, visits in nominal_run.genealogy.items():
        intervals = sorted(
            (v.processing_start_time, v.processing_completion_time) for v in visits
        )
        for (s1, e1), (s2, e2) in zip(intervals, intervals[1:]):
            assert e1 <= s2, f"{vehicle_id} overlaps processing between stations"


def test_vehicle_route_positions_not_repeated(nominal_run):
    for vehicle_id, visits in nominal_run.genealogy.items():
        stations = [v.station_id for v in visits]
        assert len(stations) == len(set(stations))


def test_genealogy_timestamps_monotonic(nominal_run):
    for vehicle_id, visits in nominal_run.genealogy.items():
        for visit in visits:
            assert visit.entry_time <= visit.processing_start_time <= visit.processing_completion_time <= visit.exit_time
        for prev, nxt in zip(visits, visits[1:]):
            assert prev.exit_time <= nxt.entry_time


def test_processing_time_always_positive(nominal_run):
    for visits in nominal_run.genealogy.values():
        for visit in visits:
            assert visit.processing_time > 0


# ---- buffer integrity --------------------------------------------------------------

def test_buffer_occupancy_never_exceeds_capacity(config, nominal_run):
    occupancy = {bid: 0 for bid in config.buffers}
    for e in nominal_run.events:
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value and e.buffer_id in occupancy:
            occupancy[e.buffer_id] += 1
            assert occupancy[e.buffer_id] <= config.buffers[e.buffer_id].capacity
        elif e.event_type == EventType.VEHICLE_LEFT_BUFFER.value and e.buffer_id in occupancy:
            occupancy[e.buffer_id] -= 1


def test_buffer_occupancy_never_negative(config, nominal_run):
    occupancy = {bid: 0 for bid in config.buffers}
    for e in nominal_run.events:
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value and e.buffer_id in occupancy:
            occupancy[e.buffer_id] += 1
        elif e.event_type == EventType.VEHICLE_LEFT_BUFFER.value and e.buffer_id in occupancy:
            occupancy[e.buffer_id] -= 1
        assert occupancy.get(e.buffer_id, 0) >= 0


def test_buffer_fifo_order_preserved(nominal_run):
    # for each buffer, vehicles must leave in the same order they entered
    entered_order = {}
    left_order = {}
    for e in nominal_run.events:
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value:
            entered_order.setdefault(e.buffer_id, []).append(e.vehicle_id)
        elif e.event_type == EventType.VEHICLE_LEFT_BUFFER.value:
            left_order.setdefault(e.buffer_id, []).append(e.vehicle_id)
    for buffer_id, left in left_order.items():
        entered = entered_order.get(buffer_id, [])
        assert left == entered[: len(left)]


# ---- station integrity --------------------------------------------------------------

def test_station_processed_count_matches_events(config, nominal_run):
    completed_events = {}
    for e in nominal_run.events:
        if e.event_type == EventType.STATION_PROCESSING_COMPLETED.value:
            completed_events[e.station_id] = completed_events.get(e.station_id, 0) + 1
    assert completed_events == nominal_run.summary["processing_counts_per_station"]


def test_station_state_transitions_are_from_valid_set(nominal_run):
    valid_states = {"IDLE", "STARVED", "PROCESSING", "BLOCKED", "DOWN"}
    for e in nominal_run.events:
        if e.event_type == EventType.STATION_STATE_CHANGED.value:
            assert e.from_state in valid_states
            assert e.to_state in valid_states
            assert e.from_state != e.to_state  # no-op transitions must never be logged


def test_down_state_never_occurs_in_step2(nominal_run):
    for e in nominal_run.events:
        if e.event_type == EventType.STATION_STATE_CHANGED.value:
            assert e.to_state != "DOWN"


# ---- event integrity --------------------------------------------------------------

def test_event_timestamps_globally_non_decreasing(nominal_run):
    times = [e.simulation_time for e in nominal_run.events]
    assert times == sorted(times)


def test_event_ids_unique(nominal_run):
    ids = [e.event_id for e in nominal_run.events]
    assert len(ids) == len(set(ids))


def test_required_event_fields_present(nominal_run):
    for e in nominal_run.events:
        assert e.event_id is not None
        assert e.simulation_time is not None
        assert e.event_type is not None


def test_no_hidden_future_fields_on_events(nominal_run):
    forbidden = {"defect", "future_", "scenario_id", "will_fail", "ground_truth"}
    for e in nominal_run.events:
        blob = str(e.__dict__).lower()
        for f in forbidden:
            assert f not in blob


# ---- completion --------------------------------------------------------------

def test_all_vehicles_eventually_complete(nominal_run):
    assert all(v.completed for v in nominal_run.vehicles.values())
    assert nominal_run.summary["vehicles_completed"] == nominal_run.summary["vehicles_generated"]


def test_simulation_terminates_without_deadlock(nominal_run):
    # if run() returned at all and every vehicle completed, there was no
    # deadlock; explicitly assert no vehicle was left mid-route
    for vehicle in nominal_run.vehicles.values():
        assert vehicle.completed
        assert vehicle.current_station is None


# ---- reproducibility --------------------------------------------------------------

def test_same_seed_same_config_reproducible(config):
    r1 = run_simulation(config, n_vehicles=40, seed=7)
    r2 = run_simulation(config, n_vehicles=40, seed=7)
    seq1 = [(e.event_type, e.simulation_time, e.vehicle_id, e.station_id) for e in r1.events]
    seq2 = [(e.event_type, e.simulation_time, e.vehicle_id, e.station_id) for e in r2.events]
    assert seq1 == seq2
    assert r1.summary == r2.summary


def test_different_seed_changes_timing_preserves_structure(config):
    r1 = run_simulation(config, n_vehicles=40, seed=7)
    r2 = run_simulation(config, n_vehicles=40, seed=1234)
    times1 = [e.simulation_time for e in r1.events]
    times2 = [e.simulation_time for e in r2.events]
    assert times1 != times2  # stochastic timing differs
    # structural invariants preserved regardless of seed
    assert all(v.completed for v in r1.vehicles.values())
    assert all(v.completed for v in r2.vehicles.values())


# ---- branch/merge behavior --------------------------------------------------------------

def test_ev_bypass_actually_exercised(nominal_run):
    left_via_s10_direct = [
        e for e in nominal_run.events
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value and e.buffer_id == "B12"
    ]
    assert len(left_via_s10_direct) > 0


def test_s12_merge_receives_from_both_paths(nominal_run):
    entered_s12 = [
        e for e in nominal_run.events
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value and e.station_id == "S12"
    ]
    buffers_used = {e.buffer_id for e in entered_s12}
    assert buffers_used == {"B11", "B12"}
