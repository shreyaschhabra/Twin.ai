"""
Controlled blocking and starvation tests (Step 2, Sections P & Q).

A healthy nominal run paces arrivals near the bottleneck station's rate
specifically so it does NOT saturate (see ASSUMPTIONS.md) — so it cannot be
relied on to reliably exercise blocking, and per instructions it must not
be. These tests build tiny, deliberate in-memory FactoryConfigs instead:
one with a slow downstream station and a tiny buffer to force blocking,
and one with slow arrivals to force starvation — and inspect the raw event
stream to prove the exact mechanics required.
"""

from backend.config.schemas import (
    Buffer,
    FactoryConfig,
    StationInstance,
    StationType,
    VehicleVariant,
)
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType


def _simple_type() -> StationType:
    return StationType(
        type_id="GENERIC",
        display_name="Generic",
        process_family="test",
        possible_sensor_families=["cycle_time"],
    )


def _make_blocking_config() -> FactoryConfig:
    """S01 (fast) -> B01 (capacity 1) -> S02 (slow). Fast arrivals guarantee
    S01 finishes vehicle 2 before S02 has finished vehicle 1, and B01's
    capacity of 1 guarantees S01 cannot immediately hand it off."""
    station_type = _simple_type()
    stations = {
        "S01": StationInstance(
            station_id="S01", station_name="Fast Station", station_type="GENERIC",
            specific_operation="fast op", baseline_cycle_time_seconds=5,
            cycle_time_variability=0.0, sensor_maturity="rich",
            available_sensors=["cycle_time"], applicable_vehicle_variants=["V1"],
        ),
        "S02": StationInstance(
            station_id="S02", station_name="Slow Station", station_type="GENERIC",
            specific_operation="slow op", baseline_cycle_time_seconds=100,
            cycle_time_variability=0.0, sensor_maturity="rich",
            available_sensors=["cycle_time"], applicable_vehicle_variants=["V1"],
        ),
    }
    buffers = {"B01": Buffer(buffer_id="B01", upstream_station="S01", downstream_station="S02", capacity=1)}
    variants = {"V1": VehicleVariant(variant_id="V1", display_name="V1", route=["S01", "S02"])}
    return FactoryConfig(
        line_name="blocking_test", station_types={"GENERIC": station_type},
        stations=stations, buffers=buffers, vehicle_variants=variants,
    )


def _make_starvation_config() -> FactoryConfig:
    """Single station, very slow/sparse arrivals: the station will finish
    each vehicle long before the next one arrives, guaranteeing a visible
    STARVED period between them."""
    station_type = _simple_type()
    stations = {
        "S01": StationInstance(
            station_id="S01", station_name="Only Station", station_type="GENERIC",
            specific_operation="op", baseline_cycle_time_seconds=5,
            cycle_time_variability=0.0, sensor_maturity="rich",
            available_sensors=["cycle_time"], applicable_vehicle_variants=["V1"],
        ),
    }
    variants = {"V1": VehicleVariant(variant_id="V1", display_name="V1", route=["S01"])}
    return FactoryConfig(
        line_name="starvation_test", station_types={"GENERIC": station_type},
        stations=stations, buffers={}, vehicle_variants=variants,
    )


def test_blocking_mechanics_end_to_end():
    config = _make_blocking_config()
    # 5 fast, tight arrivals: S01 (5s) easily outpaces S02 (100s) through
    # B01 (capacity 1), so B01 fills, S01 must block holding a completed
    # vehicle, and — critically — there are still unprocessed vehicles
    # queued up (v4, v5) that a buggy engine might start processing while
    # blocked. That's exactly what this test proves never happens.
    result = run_simulation(
        config, n_vehicles=5, seed=1,
        mean_interarrival_seconds=1.0, std_interarrival_seconds=0.0,
        variant_mix={"V1": 1.0},
    )

    state_changes = [e for e in result.events if e.event_type == EventType.STATION_STATE_CHANGED.value]
    s01_transitions = [e for e in state_changes if e.station_id == "S01"]

    # 1. S01 must have entered BLOCKED at some point
    assert any(e.to_state == "BLOCKED" for e in s01_transitions), s01_transitions
    blocked_at = next(e.simulation_time for e in s01_transitions if e.to_state == "BLOCKED")
    released_at = next(e.simulation_time for e in s01_transitions if e.from_state == "BLOCKED")
    assert released_at > blocked_at

    # 2. S01 must NOT begin processing any vehicle strictly during the
    # blocked window — every STATION_PROCESSING_STARTED on S01 either
    # happened before the block began, or at/after the moment it was
    # released. None fall inside (blocked_at, released_at).
    s01_proc_started = [
        e for e in result.events
        if e.event_type == EventType.STATION_PROCESSING_STARTED.value and e.station_id == "S01"
    ]
    assert len(s01_proc_started) == 5  # all 5 vehicles were eventually processed
    during_block = [e for e in s01_proc_started if blocked_at < e.simulation_time < released_at]
    assert during_block == [], f"processed a vehicle while blocked: {during_block}"
    after_block = [e for e in s01_proc_started if e.simulation_time >= released_at]
    assert len(after_block) >= 1  # the queued vehicle(s) resume right at/after release

    # 3. buffer B01 occupancy never exceeded capacity 1
    occ = 0
    for e in result.events:
        if e.event_type == EventType.VEHICLE_ENTERED_BUFFER.value and e.buffer_id == "B01":
            occ += 1
            assert occ <= 1
        elif e.event_type == EventType.VEHICLE_LEFT_BUFFER.value and e.buffer_id == "B01":
            occ -= 1

    # 4. all 5 vehicles eventually completed despite the blocking episode
    assert all(v.completed for v in result.vehicles.values())

    # 5. the specific vehicle S01 was holding while blocked is
    # genealogically coherent: its exit_time from S01 is strictly after
    # its processing completion time (it waited, held, before release)
    blocked_visit = None
    for visits in result.genealogy.values():
        for visit in visits:
            if visit.station_id == "S01" and visit.blocked_time > 0:
                blocked_visit = visit
    assert blocked_visit is not None
    assert blocked_visit.exit_time > blocked_visit.processing_completion_time


def test_starvation_mechanics_end_to_end():
    config = _make_starvation_config()
    # very slow arrivals relative to the 5s cycle time: guarantees S01
    # finishes and then waits a long time before the next vehicle shows up
    result = run_simulation(
        config, n_vehicles=3, seed=1,
        mean_interarrival_seconds=200.0, std_interarrival_seconds=0.0,
        variant_mix={"V1": 1.0},
    )

    state_changes = [
        (e.from_state, e.to_state, e.simulation_time)
        for e in result.events
        if e.event_type == EventType.STATION_STATE_CHANGED.value and e.station_id == "S01"
    ]

    # PROCESSING -> STARVED must occur (station goes idle waiting after
    # finishing a vehicle, well before the next one arrives)
    assert any(frm == "PROCESSING" and to == "STARVED" for frm, to, _ in state_changes)
    # STARVED -> PROCESSING must occur when the next vehicle arrives
    assert any(frm == "STARVED" and to == "PROCESSING" for frm, to, _ in state_changes)

    # the very first transition should be IDLE -> STARVED (station starts
    # idle, waits for the first vehicle) not IDLE -> PROCESSING
    assert state_changes[0][:2] == ("IDLE", "STARVED")

    # after the run, since arrivals stopped, the station should have been
    # finalized back to IDLE (production ended)
    assert state_changes[-1][1] == "IDLE"

    assert all(v.completed for v in result.vehicles.values())


def test_starvation_does_not_log_repeated_identical_states():
    config = _make_starvation_config()
    result = run_simulation(
        config, n_vehicles=3, seed=2,
        mean_interarrival_seconds=200.0, std_interarrival_seconds=0.0,
        variant_mix={"V1": 1.0},
    )
    state_changes = [
        e for e in result.events
        if e.event_type == EventType.STATION_STATE_CHANGED.value and e.station_id == "S01"
    ]
    # the engine is event-driven (no per-tick polling), so the only way a
    # "repeated identical state" bug could show up is a logged transition
    # whose from_state equals its to_state — assert that never happens,
    # and that consecutive events form a proper chain (each one's
    # from_state matches the previous one's to_state).
    for e in state_changes:
        assert e.from_state != e.to_state
    for prev, nxt in zip(state_changes, state_changes[1:]):
        assert prev.to_state == nxt.from_state
