from collections import Counter
from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.flow_v3.precursor_observables import micro_stop_rolling_quantities
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_physics import (
    MANUAL_CANDIDATES,
    build_arrival_burst,
    build_manual_variation,
    build_micro_stops,
    expected_micro_stop_service_seconds,
    manual_cycle_multiplier,
)
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def config():
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    return apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))


def test_temporal_profiles_are_deterministic_and_recovering_returns_to_zero():
    scenario = ScenarioDefinition(
        scenario_id="p", family=ScenarioFamily.MANUAL_VARIATION,
        start_time=100.0, duration=1000.0, temporal_profile="RECOVERING",
    )
    assert scenario.profile_fraction(50.0) == 0.0
    assert scenario.profile_fraction(100.0) == 0.0
    assert scenario.profile_fraction(350.0) == pytest.approx(1.0)
    assert scenario.profile_fraction(750.0) == pytest.approx(1.0)
    assert scenario.profile_fraction(1100.0) == pytest.approx(0.0)

    gradual = scenario.model_copy(update={"temporal_profile": "GRADUAL"})
    assert gradual.profile_fraction(350.0) == pytest.approx(0.5)
    assert gradual.profile_fraction(600.0) == pytest.approx(1.0)
    assert gradual.profile_fraction(900.0) == pytest.approx(1.0)


def test_manual_severity_is_station_aware_and_physically_ordered(config):
    for station_id in MANUAL_CANDIDATES:
        mild = manual_cycle_multiplier(config, station_id, "MILD")
        moderate = manual_cycle_multiplier(config, station_id, "MODERATE")
        severe = manual_cycle_multiplier(config, station_id, "SEVERE")
        assert 1.0 < mild <= moderate <= severe <= 1.65
    # The same severity is not one fixed multiplier across stations.
    assert manual_cycle_multiplier(config, "S11", "SEVERE") != manual_cycle_multiplier(config, "S22", "SEVERE")


def test_manual_builder_has_short_physics_based_duration(config):
    scenario = build_manual_variation(
        config, scenario_id="m", station_id="S11", severity="SEVERE",
        profile="GRADUAL", start_time=1000.0,
    )
    assert scenario.duration == 60 * 60
    assert scenario.temporal_profile == "GRADUAL"
    assert scenario.params["cycle_time_multiplier"] > 1.0


def _micro_run(config, seed):
    scenario = build_micro_stops(
        scenario_id="micro", station_id="S26", severity="SEVERE",
        profile="STEP", start_time=0.0,
    )
    return run_simulation(
        config, n_vehicles=80, seed=seed,
        mean_interarrival_seconds=102.5, std_interarrival_seconds=15.0,
        scenarios=[scenario],
    )


def test_rate_process_can_generate_multiple_stops_inside_one_visit(config):
    result = _micro_run(config, 51001)
    stops = [event for event in result.events if event.event_type == EventType.MICRO_STOP_OCCURRED.value]
    counts = Counter(event.vehicle_id for event in stops)
    assert stops
    assert max(counts.values()) >= 2
    for event in stops:
        assert event.station_id == "S26"

    starts = {(e.vehicle_id, e.station_id): e for e in result.events if e.event_type == EventType.STATION_PROCESSING_STARTED.value}
    completions = [e for e in result.events if e.event_type == EventType.STATION_PROCESSING_COMPLETED.value and e.station_id == "S26"]
    for completed in completions:
        started = starts[(completed.vehicle_id, completed.station_id)]
        assert completed.simulation_time - started.simulation_time == pytest.approx(completed.value)


def test_rate_process_rng_is_reproducible(config):
    first = [e.__dict__ for e in _micro_run(config, 51002).events]
    second = [e.__dict__ for e in _micro_run(config, 51002).events]
    assert first == second


def test_micro_stop_expected_burden_orders_severity():
    base = 77.4
    values = [expected_micro_stop_service_seconds(base, severity) for severity in ("MILD", "MODERATE", "SEVERE")]
    assert base < values[0] < values[1] < values[2]


def test_rolling_micro_stop_quantities_are_observable(config):
    result = _micro_run(config, 51003)
    last_stop = max(
        event.simulation_time for event in result.events
        if event.event_type == EventType.MICRO_STOP_OCCURRED.value
    )
    values = micro_stop_rolling_quantities(result.events, "S26", last_stop, window_seconds=600.0)
    assert set(values) == {
        "micro_stop_count_recent", "micro_stop_seconds_recent", "mean_micro_stop_duration",
        "micro_stop_rate", "micro_stop_rate_trend",
    }
    assert values["micro_stop_count_recent"] > 0
    assert values["micro_stop_seconds_recent"] > 0


def test_arrival_burst_reduces_headways_without_impossible_arrivals(config):
    scenario = build_arrival_burst(
        scenario_id="burst", severity="SEVERE", profile="STEP_BURST", start_time=0.0
    )
    result = run_simulation(
        config, n_vehicles=60, seed=52001,
        mean_interarrival_seconds=102.5, std_interarrival_seconds=15.0,
        scenarios=[scenario],
    )
    times = [e.simulation_time for e in result.events if e.event_type == EventType.VEHICLE_CREATED.value]
    headways = [b - a for a, b in zip(times, times[1:])]
    assert min(headways) >= 102.5 * 0.60 * 0.30
    assert sum(headways) / len(headways) < 75.0
