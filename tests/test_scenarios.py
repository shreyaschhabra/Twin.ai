"""
Controlled, matched-baseline tests for all 8 scenario families (Step 3,
Section Q) plus one composition test (Section R).

Pattern throughout: run a BASELINE (no scenarios) and an ABNORMAL run
(identical config, identical seed, one scenario injected) and show the
expected difference traces back to the injected scenario specifically —
unrelated stations/streams stay exactly as they were, not just
"statistically similar."
"""

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily
from backend.simulation.scenarios.latent import PROHIBITED_OBSERVABLE_FIELDS
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
SEED = 42
N_VEHICLES = 40


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml")


@pytest.fixture(scope="module")
def sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models_dev.yaml")


@pytest.fixture(scope="module")
def baseline(config, sensor_models):
    return run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models)


def sensor_readings(result, station_id, sensor_name):
    return [e for e in result.events if e.event_type == EventType.SENSOR_READING.value
            and e.station_id == station_id and e.sensor_name == sensor_name]


def processing_times(result, station_id):
    return [e.value for e in result.events if e.event_type == EventType.STATION_PROCESSING_COMPLETED.value
            and e.station_id == station_id]


# ============================================================ 1. EQUIPMENT DEGRADATION

def test_equipment_degradation(config, sensor_models, baseline):
    scenario = ScenarioDefinition(
        scenario_id="degrade_s02", family=ScenarioFamily.EQUIPMENT_DEGRADATION,
        station_ids=["S02"], start_time=0, duration=100000, severity=0.8,
        affected_sensors=["weld_current"],
        params={"ramp_duration_seconds": 12000, "max_cycle_time_multiplier": 2.0,
                "max_noise_multiplier": 2.0, "max_sensor_mean_shift": -1200.0,
                "quality_weight_per_visit": 0.02},
    )
    result = run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    weld = sensor_readings(result, "S02", "weld_current")
    assert len(weld) >= 10
    # gradual precursor: later readings deviate further from the 8800
    # baseline than earlier ones (not an abrupt jump to one broken value)
    early_dev = abs(weld[2].value - 8800)
    late_dev = abs(weld[-1].value - 8800)
    assert late_dev > early_dev

    # S02 cycle time grows over the window too
    s02_times = processing_times(result, "S02")
    assert s02_times[-1] > s02_times[2]

    # latent quality exposure accumulated, chronologically, only for S02 visits
    exposures = [r for r in result.latent_truth.quality_exposure if r.scenario_id == "degrade_s02"]
    assert len(exposures) >= 10
    assert all(r.station_id == "S02" for r in exposures)
    assert exposures[-1].simulation_time > exposures[0].simulation_time

    # unrelated station S01 is byte-identical to baseline: isolated RNG
    # streams mean a scenario on S02 cannot perturb S01 at all
    assert processing_times(result, "S01") == processing_times(baseline, "S01")
    assert [r.value for r in sensor_readings(result, "S01", "weld_current")] == \
           [r.value for r in sensor_readings(baseline, "S01", "weld_current")]


# ============================================================ 2. MICRO-STOPS

def test_micro_stops(config, sensor_models):
    scenario = ScenarioDefinition(
        scenario_id="microstop_s10", family=ScenarioFamily.MICRO_STOPS,
        station_ids=["S10"], start_time=0, duration=100000, severity=0.5,
        params={"stop_probability": 1.0, "min_duration_seconds": 20, "max_duration_seconds": 20},
    )
    baseline = run_simulation(config, n_vehicles=15, seed=SEED, sensor_models=sensor_models)
    abnormal = run_simulation(config, n_vehicles=15, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    micro_stops = [e for e in abnormal.events if e.event_type == EventType.MICRO_STOP_OCCURRED.value]
    assert len(micro_stops) >= 10
    assert all(e.station_id == "S10" and e.value == 20 for e in micro_stops)
    assert not any(e.event_type == EventType.MICRO_STOP_OCCURRED.value for e in baseline.events)

    # DOWN state actually occurred and resolved
    down_transitions = [e for e in abnormal.events
                         if e.event_type == EventType.STATION_STATE_CHANGED.value
                         and e.station_id == "S10" and e.to_state == "DOWN"]
    assert len(down_transitions) >= 10
    resumed = [e for e in abnormal.events
               if e.event_type == EventType.STATION_STATE_CHANGED.value
               and e.station_id == "S10" and e.from_state == "DOWN"]
    assert all(e.to_state == "PROCESSING" for e in resumed)

    # Corrected chronology (patch 1): STATION_PROCESSING_STARTED happens
    # BEFORE the micro-stop interruption — the vehicle is already being
    # processed when it gets interrupted, not still waiting to start.
    proc_started = {e.vehicle_id: e.simulation_time for e in abnormal.events
                    if e.event_type == EventType.STATION_PROCESSING_STARTED.value and e.station_id == "S10"}
    proc_completed = {e.vehicle_id: e.simulation_time for e in abnormal.events
                      if e.event_type == EventType.STATION_PROCESSING_COMPLETED.value and e.station_id == "S10"}
    for stop in micro_stops:
        assert proc_started[stop.vehicle_id] <= stop.simulation_time
        # and completion happens only after the micro-stop fully resolves
        assert proc_completed[stop.vehicle_id] >= stop.simulation_time + stop.value

    # downstream flow consequence: vehicles exit S10 later than in baseline
    def exit_time(result, vehicle_id):
        return next(v.exit_time for v in result.genealogy[vehicle_id] if v.station_id == "S10")

    delayed_count = sum(
        1 for vid in abnormal.vehicles
        if vid in baseline.vehicles and exit_time(abnormal, vid) > exit_time(baseline, vid)
    )
    assert delayed_count >= 10


def test_micro_stop_delay_lands_in_processing_not_waiting(config, sensor_models):
    """Patch-1-required test: (completion - start) grows by exactly the
    micro-stop duration in a matched comparison, while pre-processing
    waiting_time is unaffected — proving the delay was correctly placed."""
    scenario = ScenarioDefinition(
        scenario_id="microstop_s10_precise", family=ScenarioFamily.MICRO_STOPS,
        station_ids=["S10"], start_time=0, duration=100000, severity=0.5,
        params={"stop_probability": 1.0, "min_duration_seconds": 15, "max_duration_seconds": 15},
    )
    baseline = run_simulation(config, n_vehicles=10, seed=SEED, sensor_models=sensor_models)
    abnormal = run_simulation(config, n_vehicles=10, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    for vid in baseline.vehicles:
        base_visit = next(v for v in baseline.genealogy[vid] if v.station_id == "S10")
        abn_visit = next(v for v in abnormal.genealogy[vid] if v.station_id == "S10")

        base_span = base_visit.processing_completion_time - base_visit.processing_start_time
        abn_span = abn_visit.processing_completion_time - abn_visit.processing_start_time
        assert abn_span == pytest.approx(base_span + 15.0, abs=1e-6)

        # waiting_time (entry -> start) must be identical: the micro-stop
        # must never leak into upstream queue waiting time
        assert abn_visit.waiting_time == pytest.approx(base_visit.waiting_time, abs=1e-6)
        assert abn_visit.processing_start_time == pytest.approx(base_visit.processing_start_time, abs=1e-6)


# ============================================================ 3. VEHICLE-MIX OVERLOAD

def test_vehicle_mix_overload(config, sensor_models, baseline):
    scenario = ScenarioDefinition(
        scenario_id="mix_overload", family=ScenarioFamily.VEHICLE_MIX_OVERLOAD,
        start_time=0, duration=100000, severity=0.5,
        variant_mix_override={"ICE_SEDAN": 0.05, "ICE_SUV": 0.90, "EV": 0.05},
    )
    result = run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    variants = [v.variant_id for v in result.vehicles.values()]
    suv_fraction = variants.count("ICE_SUV") / len(variants)
    baseline_variants = [v.variant_id for v in baseline.vehicles.values()]
    baseline_suv_fraction = baseline_variants.count("ICE_SUV") / len(baseline_variants)
    assert suv_fraction > baseline_suv_fraction  # mix genuinely shifted

    # no equipment-health effect: S01 weld_current sensor stream is
    # byte-identical to baseline, position by position, because sensor
    # generation happens once per S01 visit regardless of which variant
    # that visit is, and nothing in this family touches S01's effects
    base_weld = [r.value for r in sensor_readings(baseline, "S01", "weld_current")]
    result_weld = [r.value for r in sensor_readings(result, "S01", "weld_current")]
    assert base_weld == result_weld

    # no hidden equipment-degradation latent exposure from this family
    assert not any(r.family == "VEHICLE_MIX_OVERLOAD" for r in result.latent_truth.quality_exposure)


# ============================================================ 4. BAD BATCH

BATCH_STATIONS = {"S03": 5}  # cohort size 5 -> B1001, B1002, B1003, ... at S03


def test_bad_batch(config, sensor_models):
    scenario = ScenarioDefinition(
        scenario_id="bad_batch_b1002", family=ScenarioFamily.BAD_BATCH,
        station_ids=["S03"], start_time=0, duration=None, severity=0.5,
        affected_batch_id="B1002",
        params={"quality_weight_per_visit": 0.2},
    )
    result = run_simulation(config, n_vehicles=20, seed=SEED, sensor_models=sensor_models,
                             scenarios=[scenario], batch_relevant_stations=BATCH_STATIONS)

    # patch 2 requirement: EVERY vehicle at S03 gets a neutral batch_id —
    # not just the ones in the bad cohort
    assignments = [e for e in result.events if e.event_type == EventType.MATERIAL_BATCH_ASSIGNED.value]
    assert len(assignments) == 20
    assert all(e.station_id == "S03" for e in assignments)

    # many distinct normal batches exist (not one batch per vehicle, not
    # one batch for the whole run)
    distinct_batches = {e.batch_id for e in assignments}
    assert len(distinct_batches) >= 3
    assert "B1002" in distinct_batches

    # only the B1002 cohort accumulates latent exposure from this scenario
    b1002_cohort = {e.vehicle_id for e in assignments if e.batch_id == "B1002"}
    assert 1 < len(b1002_cohort) < 20  # a real cohort, not one vehicle, not everyone
    exposures = [r for r in result.latent_truth.quality_exposure if r.scenario_id == "bad_batch_b1002"]
    assert {r.vehicle_id for r in exposures} == b1002_cohort
    assert all(r.contribution > 0 for r in exposures)

    # no observable "is bad" field anywhere
    for e in result.events:
        blob = str(e.__dict__).lower()
        assert "is_bad" not in blob and "bad_batch_truth" not in blob and "bad=true" not in blob


def test_bad_batch_observable_schedule_matches_healthy_baseline(config, sensor_models):
    """Patch-2-required test: the strongest matched A/B design. Same
    master seed, same batch_relevant_stations, one run with no scenario
    and one with B1002 declared bad — the OBSERVABLE batch-id sequence
    must be byte-identical; only latent exposure should differ."""
    healthy = run_simulation(config, n_vehicles=20, seed=SEED, sensor_models=sensor_models,
                              batch_relevant_stations=BATCH_STATIONS)
    bad_batch_scenario = ScenarioDefinition(
        scenario_id="bad_batch_b1002", family=ScenarioFamily.BAD_BATCH,
        station_ids=["S03"], start_time=0, duration=None, severity=0.5,
        affected_batch_id="B1002", params={"quality_weight_per_visit": 0.2},
    )
    abnormal = run_simulation(config, n_vehicles=20, seed=SEED, sensor_models=sensor_models,
                               scenarios=[bad_batch_scenario], batch_relevant_stations=BATCH_STATIONS)

    def batch_schedule(result):
        return [(e.vehicle_id, e.station_id, e.batch_id) for e in result.events
                if e.event_type == EventType.MATERIAL_BATCH_ASSIGNED.value]

    assert batch_schedule(healthy) == batch_schedule(abnormal)

    # healthy run has zero latent exposure; abnormal run has some — the
    # *only* difference between the two runs
    assert healthy.latent_truth.quality_exposure == []
    assert len(abnormal.latent_truth.quality_exposure) > 0

    # and the healthy run's own batch schedule already contains multiple
    # distinct normal batches, with no scenario involved at all
    healthy_batches = {b for _, _, b in batch_schedule(healthy)}
    assert len(healthy_batches) >= 3


# ============================================================ 5. ENVIRONMENTAL DRIFT

def test_environmental_drift(config, sensor_models):
    scenario = ScenarioDefinition(
        scenario_id="env_drift_s05", family=ScenarioFamily.ENVIRONMENTAL_DRIFT,
        station_ids=["S05"], start_time=0, duration=100000, severity=0.6,
        affected_sensors=["booth_temperature"],
        params={"ramp_duration_seconds": 12000, "max_sensor_mean_shift": 10.0,
                "deviation_threshold_fraction": 0.3, "quality_weight_per_visit": 0.1},
    )
    result = run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    temps = sensor_readings(result, "S05", "booth_temperature")
    assert len(temps) >= 10
    # smooth temporal continuity: consecutive readings' means move in a
    # consistent direction (upward), not independently re-randomized
    values = [r.value for r in temps]
    assert values[-1] > values[0]
    # roughly monotonic trend (allow noise): majority of steps non-decreasing
    increases = sum(1 for a, b in zip(values, values[1:]) if b >= a - 1.0)
    assert increases >= len(values) * 0.6

    # exposure only kicks in once deviation crosses the configured
    # threshold — early in-window visits should NOT yet contribute
    exposures = {r.simulation_time: r.contribution for r in result.latent_truth.quality_exposure
                 if r.scenario_id == "env_drift_s05"}
    assert len(exposures) >= 1
    first_temp_time = temps[0].simulation_time
    assert first_temp_time not in exposures  # too early, below threshold


# ============================================================ 6. SENSOR DROPOUT

def test_sensor_dropout(config, sensor_models):
    scenario = ScenarioDefinition(
        scenario_id="dropout_s04", family=ScenarioFamily.SENSOR_DROPOUT,
        station_ids=["S04"], start_time=0, duration=100000, severity=0.5,
        affected_sensors=["laser_scan"], dropout_type="missing",
        params={"dropout_probability": 1.0},
    )
    baseline = run_simulation(config, n_vehicles=15, seed=SEED, sensor_models=sensor_models)
    abnormal = run_simulation(config, n_vehicles=15, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    laser = sensor_readings(abnormal, "S04", "laser_scan")
    assert len(laser) >= 10
    assert all(r.measurement_status == "missing" and r.value is None for r in laser)

    # the OTHER sensor at S04 (vision_camera) is unaffected
    vision = sensor_readings(abnormal, "S04", "vision_camera")
    assert all(r.measurement_status == "available" for r in vision)

    # physical processing time at S04 is unchanged — a dropout is purely a
    # measurement-visibility effect, never a process effect
    assert processing_times(abnormal, "S04") == processing_times(baseline, "S04")


# ============================================================ 7. MANUAL VARIATION

def test_manual_variation(config, sensor_models, baseline):
    scenario = ScenarioDefinition(
        scenario_id="manual_var_s09", family=ScenarioFamily.MANUAL_VARIATION,
        station_ids=["S09"], start_time=0, duration=100000, severity=0.5,
        params={"cycle_time_multiplier": 1.5, "variability_multiplier": 3.0, "quality_weight_per_visit": 0.03},
    )
    result = run_simulation(config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    base_times = processing_times(baseline, "S09")
    abnormal_times = processing_times(result, "S09")
    import statistics
    assert statistics.mean(abnormal_times) > statistics.mean(base_times) * 1.2
    assert statistics.pstdev(abnormal_times) > statistics.pstdev(base_times) * 1.5

    # no operator/individual identity field anywhere in the schema or output
    for e in result.events:
        assert "operator" not in str(e.__dict__).lower()


# ============================================================ 8. RARE BACKGROUND QUALITY EVENT

def test_random_quality_event(config, sensor_models):
    scenario = ScenarioDefinition(
        scenario_id="background_quality", family=ScenarioFamily.RANDOM_QUALITY_EVENT,
        start_time=0, duration=None, severity=0.2,
        params={"per_vehicle_probability": 0.05, "min_magnitude": 0.02, "max_magnitude": 0.08},
    )
    result = run_simulation(config, n_vehicles=200, seed=SEED, sensor_models=sensor_models, scenarios=[scenario])

    exposures = [r for r in result.latent_truth.quality_exposure if r.family == "RANDOM_QUALITY_EVENT"]
    # rare: with p=0.05 over 200 vehicles, expect ~10; must not be "every vehicle"
    assert 1 <= len(exposures) <= 40
    # no station attribution — genuinely unexplained, no obvious precursor
    assert all(r.station_id is None for r in exposures)
    # and no corresponding sensor anomaly exists anywhere for those vehicles
    affected_vehicles = {r.vehicle_id for r in exposures}
    dropout_events = [e for e in result.events if e.event_type == EventType.SENSOR_READING.value
                      and e.measurement_status != "available" and e.vehicle_id in affected_vehicles]
    assert dropout_events == []


# ============================================================ COMPOSITION (Section R)

def test_scenario_composition_two_compatible_scenarios(config, sensor_models, baseline):
    """Two scenarios on different, non-overlapping stations must compose
    predictably: both effects show up, unrelated stations remain
    untouched, and the simulation completes without corruption."""
    degradation = ScenarioDefinition(
        scenario_id="compose_degrade_s02", family=ScenarioFamily.EQUIPMENT_DEGRADATION,
        station_ids=["S02"], start_time=0, duration=100000, severity=0.6,
        affected_sensors=["weld_current"],
        params={"ramp_duration_seconds": 12000, "max_cycle_time_multiplier": 1.5,
                "max_sensor_mean_shift": -800.0, "quality_weight_per_visit": 0.02},
    )
    dropout = ScenarioDefinition(
        scenario_id="compose_dropout_s04", family=ScenarioFamily.SENSOR_DROPOUT,
        station_ids=["S04"], start_time=0, duration=100000, severity=0.5,
        affected_sensors=["laser_scan"], dropout_type="missing",
        params={"dropout_probability": 1.0},
    )
    result = run_simulation(
        config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models,
        scenarios=[degradation, dropout],
    )

    # simulation completed cleanly for everyone
    assert all(v.completed for v in result.vehicles.values())

    # both effects independently present
    weld = sensor_readings(result, "S02", "weld_current")
    assert abs(weld[-1].value - 8800) > abs(weld[1].value - 8800)
    laser = sensor_readings(result, "S04", "laser_scan")
    assert any(r.measurement_status == "missing" for r in laser)

    # unrelated station S01 still byte-identical to the true baseline
    assert processing_times(result, "S01") == processing_times(baseline, "S01")


def test_same_station_composition_degradation_and_dropout(config, sensor_models, baseline):
    """Patch-3-required test: the important same-station case — gradual
    equipment degradation AND sensor dropout both targeting S02's
    weld_current. Composition semantics (documented in manager.py):
    cycle_time_multiplier is a pure function of the degradation scenario
    (dropout carries no cycle-time effect at all), while the weld_current
    READING itself becomes unobservable because dropout is checked first
    in sensors.py — proving a hidden physical effect can coexist with a
    hidden sensor, without one cancelling the other."""
    degradation = ScenarioDefinition(
        scenario_id="same_station_degrade", family=ScenarioFamily.EQUIPMENT_DEGRADATION,
        station_ids=["S02"], start_time=0, duration=100000, severity=0.7,
        affected_sensors=["weld_current"],
        params={"ramp_duration_seconds": 10000, "max_cycle_time_multiplier": 1.8,
                "max_sensor_mean_shift": -900.0, "quality_weight_per_visit": 0.03},
    )
    dropout = ScenarioDefinition(
        scenario_id="same_station_dropout", family=ScenarioFamily.SENSOR_DROPOUT,
        station_ids=["S02"], start_time=0, duration=100000, severity=0.5,
        affected_sensors=["weld_current"], dropout_type="missing",
        params={"dropout_probability": 1.0},
    )
    result = run_simulation(
        config, n_vehicles=N_VEHICLES, seed=SEED, sensor_models=sensor_models,
        scenarios=[degradation, dropout],
    )

    # 1+2. physical degradation still changes cycle time, even though its
    # target sensor is invisible
    s02_times = processing_times(result, "S02")
    assert s02_times[-1] > s02_times[2] * 1.3

    # 3. latent quality exposure from degradation still accumulates
    exposures = [r for r in result.latent_truth.quality_exposure if r.scenario_id == "same_station_degrade"]
    assert len(exposures) >= 10

    # 4. the targeted sensor is missing because of dropout — the
    # degraded VALUE is never actually observable
    weld = sensor_readings(result, "S02", "weld_current")
    assert all(r.measurement_status == "missing" and r.value is None for r in weld)

    # 5. dropout does not cancel the physical degradation: cycle time grew
    # (checked above) despite the sensor being fully hidden the whole time
    # — process truth and measurement truth are provably separable here.

    # 6a. S02's OTHER sensors (not targeted by either scenario) are
    # completely unaffected — byte-identical to true baseline
    assert [r.value for r in sensor_readings(result, "S02", "weld_time")] == \
           [r.value for r in sensor_readings(baseline, "S02", "weld_time")]
    # 6b. unrelated station S01 also byte-identical to true baseline
    assert processing_times(result, "S01") == processing_times(baseline, "S01")

    # 7. no latent scenario fields leak into observable data
    for e in result.events:
        blob = str(e.__dict__).lower()
        for prohibited in PROHIBITED_OBSERVABLE_FIELDS:
            assert prohibited not in blob


# ============================================================ LEAKAGE (Section T)

def test_no_prohibited_fields_on_events(config, sensor_models):
    all_scenarios_yaml = CONFIG_DIR / "development_scenarios.yaml"
    from backend.simulation.scenarios.config import load_scenarios
    scenarios = load_scenarios(all_scenarios_yaml)
    result = run_simulation(config, n_vehicles=30, seed=SEED, sensor_models=sensor_models, scenarios=scenarios)

    event_field_names = {f for e in result.events for f in e.__dict__.keys()}
    for prohibited in PROHIBITED_OBSERVABLE_FIELDS:
        assert prohibited not in event_field_names

    for e in result.events:
        blob = str(e.__dict__).lower()
        for prohibited in PROHIBITED_OBSERVABLE_FIELDS:
            assert prohibited not in blob, f"prohibited field '{prohibited}' leaked into event {e}"


def test_latent_and_observable_are_physically_separate_objects(config, sensor_models):
    result = run_simulation(config, n_vehicles=10, seed=SEED, sensor_models=sensor_models)
    assert not hasattr(result.events[0] if result.events else object(), "scenario_id")
    # the latent log is a distinct object from the event list
    assert result.latent_truth is not None
    assert isinstance(result.latent_truth.scenario_truth, list)
    assert isinstance(result.latent_truth.quality_exposure, list)
