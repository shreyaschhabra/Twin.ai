from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config.loader import load_factory_config
from backend.observability.policy import PublicEvent, build_public_event_stream, public_events_as_of
from backend.simulation.events import Event, EventType
from backend.simulation.engine import run_simulation
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily
from backend.trust.virtual_sensor import METHOD_OPERATIONAL_BASELINE, estimate_virtual_sensor_value
from backend.intelligence.trust_service import TrustService

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def config():
    return load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")


def _event(number, time, event_type, station_id=None, **kwargs):
    return Event(
        event_id=number,
        simulation_time=time,
        event_type=event_type.value,
        station_id=station_id,
        **kwargs,
    )


def test_rich_station_public_parity_and_future_duration_is_hidden(config):
    internal = [
        _event(10, 1.0, EventType.VEHICLE_ENTERED_BUFFER, "S01", vehicle_id="V1", buffer_id="ENTRY::S01", occupancy=2),
        _event(11, 2.0, EventType.VEHICLE_ENTERED_STATION, "S01", vehicle_id="V1", vehicle_variant="EV", route_position=0),
        _event(12, 2.0, EventType.STATION_PROCESSING_STARTED, "S01", vehicle_id="V1", value=87.0),
        _event(13, 89.0, EventType.STATION_PROCESSING_COMPLETED, "S01", vehicle_id="V1", value=87.0),
        _event(14, 89.0, EventType.STATION_STATE_CHANGED, "S01", from_state="PROCESSING", to_state="BLOCKED", buffer_id="B01", occupancy=4),
        _event(15, 89.0, EventType.SENSOR_READING, "S01", vehicle_id="V1", sensor_name="weld_current", unit="A", value=9000.0, measurement_status="available"),
    ]
    public = build_public_event_stream(internal, config)
    assert [event.event_id for event in public] == list(range(1, len(public) + 1))
    assert public[0].occupancy == 2
    started = next(event for event in public if event.event_type == EventType.STATION_PROCESSING_STARTED.value)
    completed = next(event for event in public if event.event_type == EventType.STATION_PROCESSING_COMPLETED.value)
    state = next(event for event in public if event.event_type == EventType.STATION_STATE_CHANGED.value)
    assert started.value is None  # sampled future work is internal-only
    assert completed.value == 87.0
    assert (state.from_state, state.to_state, state.occupancy) == ("PROCESSING", "BLOCKED", 4)
    assert {event.observability_class for event in public} == {"PUBLIC_DIRECT"}


def test_partial_station_reduces_exact_fields_and_uses_coarse_state(config):
    internal = [
        _event(1, 1.0, EventType.VEHICLE_ENTERED_BUFFER, "S05", buffer_id="B04", occupancy=3),
        _event(2, 2.0, EventType.STATION_PROCESSING_STARTED, "S05", value=70.0),
        _event(3, 72.0, EventType.STATION_PROCESSING_COMPLETED, "S05", value=70.0),
        _event(4, 72.0, EventType.STATION_STATE_CHANGED, "S05", from_state="PROCESSING", to_state="DOWN"),
        _event(5, 73.0, EventType.MICRO_STOP_OCCURRED, "S05", value=9.0),
    ]
    public = build_public_event_stream(internal, config)
    assert public[0].occupancy is None
    assert next(event for event in public if event.event_type == EventType.STATION_PROCESSING_COMPLETED.value).value is None
    state = next(event for event in public if event.event_type == EventType.STATION_STATE_CHANGED.value)
    assert (state.from_state, state.to_state) == ("RUNNING", "EQUIPMENT_STOP")
    assert state.observability_class == "PUBLIC_DERIVED"
    assert next(event for event in public if event.event_type == EventType.MICRO_STOP_OCCURRED.value).value is None


def test_poor_station_keeps_sparse_checkpoint_manual_evidence_but_hides_exact_state(config):
    internal = [
        _event(1, 1.0, EventType.VEHICLE_ENTERED_BUFFER, "S11", buffer_id="B10", occupancy=3),
        _event(2, 2.0, EventType.VEHICLE_ENTERED_STATION, "S11", vehicle_id="V1"),
        _event(3, 2.0, EventType.STATION_PROCESSING_STARTED, "S11", vehicle_id="V1", value=90.0),
        _event(4, 10.0, EventType.STATION_STATE_CHANGED, "S11", from_state="PROCESSING", to_state="DOWN"),
        _event(5, 10.0, EventType.MICRO_STOP_OCCURRED, "S11", vehicle_id="V1", value=12.0),
        _event(6, 104.0, EventType.STATION_PROCESSING_COMPLETED, "S11", vehicle_id="V1", value=102.0),
        _event(7, 104.0, EventType.SENSOR_READING, "S11", vehicle_id="V1", sensor_name="checklist_completion", unit="fraction", value=1.0, measurement_status="available"),
    ]
    public = build_public_event_stream(internal, config)
    types = {event.event_type for event in public}
    assert EventType.VEHICLE_ENTERED_BUFFER.value not in types
    assert EventType.STATION_PROCESSING_STARTED.value not in types
    assert EventType.STATION_STATE_CHANGED.value not in types
    assert EventType.MICRO_STOP_OCCURRED.value not in types
    completed = next(event for event in public if event.event_type == EventType.STATION_PROCESSING_COMPLETED.value)
    manual = next(event for event in public if event.event_type == EventType.SENSOR_READING.value)
    assert completed.value is None
    assert manual.evidence_source == "MANUAL"
    assert manual.observability_class == "CONDITIONALLY_OBSERVABLE"
    assert manual.confidence < 0.60


def test_public_schema_cannot_expose_latent_or_future_fields_and_asof_blocks_future(config):
    forbidden = {
        "scenario_id", "scenario_truth", "hidden_degradation_severity", "latent_quality_exposure",
        "future_bottleneck_time", "future_qc", "future_station_readings", "source_event_id",
    }
    assert forbidden.isdisjoint({field.name for field in fields(PublicEvent)})

    internal = [
        _event(50, 10.0, EventType.VEHICLE_CREATED, vehicle_id="V1", vehicle_variant="EV"),
        _event(75, 20.0, EventType.SENSOR_READING, "S01", vehicle_id="V1", sensor_name="weld_current", value=1.0, unit="A", measurement_status="available"),
        _event(80, 25.0, EventType.SENSOR_READING, "S01", vehicle_id="V1", sensor_name="weld_current", value=2.0, unit="A", measurement_status="available"),
        _event(90, 30.0, EventType.QC_RESULT_RECORDED, "S45", vehicle_id="V1", qc_result="PASS"),
    ]
    public = build_public_event_stream(internal, config)
    as_of = public_events_as_of(public, 20.0)
    assert all(event.simulation_time <= 20.0 for event in as_of)
    assert [event.value for event in as_of if event.event_type == EventType.SENSOR_READING.value] == [1.0]
    assert not any(event.qc_result for event in as_of)
    assert not hasattr(public[0], "scenario_id")


def test_scenario_truth_and_latent_exposure_remain_outside_actual_public_stream(config):
    scenario = ScenarioDefinition(
        scenario_id="hidden_manual_truth",
        family=ScenarioFamily.MANUAL_VARIATION,
        station_ids=["S11"],
        start_time=0.0,
        duration=1200.0,
        severity=0.9,
        temporal_profile="STEP",
        params={"cycle_time_multiplier": 1.3, "quality_weight_per_visit": 0.2},
    )
    result = run_simulation(
        config, n_vehicles=8, seed=77001,
        mean_interarrival_seconds=102.5, std_interarrival_seconds=0.0,
        scenarios=[scenario],
    )
    assert result.latent_truth.scenario_truth
    assert result.latent_truth.quality_exposure
    public = build_public_event_stream(result.events, config)
    serialized = "\n".join(repr(event) for event in public)
    assert "hidden_manual_truth" not in serialized
    assert "quality_weight_per_visit" not in serialized
    assert not any(
        event.station_id == "S11" and event.event_type == EventType.STATION_STATE_CHANGED.value
        for event in public
    )


def test_public_projection_order_and_content_are_deterministic(config):
    internal = [
        _event(3, 1.0, EventType.STATION_STATE_CHANGED, "S11", from_state="IDLE", to_state="STARVED"),
        _event(8, 2.0, EventType.VEHICLE_ENTERED_STATION, "S11", vehicle_id="V1"),
        _event(10, 3.0, EventType.STATION_PROCESSING_COMPLETED, "S11", vehicle_id="V1", value=1.0),
    ]
    first = build_public_event_stream(internal, config)
    second = build_public_event_stream(internal, config)
    assert first == second
    assert [event.event_id for event in first] == [1, 2]
    assert [event.simulation_time for event in first] == sorted(event.simulation_time for event in first)


def test_static_operational_baseline_is_unknown_not_inferred():
    models = {("S01", "weld_current"): SimpleNamespace(baseline=9000.0)}
    value, method, reliable = estimate_virtual_sensor_value(
        "S01", "weld_current", "WELDING_BODY_JOINING", {}, {}, models,
    )
    assert value == 9000.0  # retained as an internal prior
    assert method == METHOD_OPERATIONAL_BASELINE
    assert reliable is False

    assessment = TrustService(models).assess(
        station_id="S01", sensor_name="weld_current", station_type="WELDING_BODY_JOINING",
        has_direct_reading=False, evidence_age_seconds=None,
        recent_readings_by_station={}, recent_readings_by_type={},
    )
    assert assessment["data_state"] == "UNKNOWN"
    assert assessment["estimated_value"] is None
    assert assessment["inference_method"] is None
