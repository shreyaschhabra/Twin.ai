"""Sections 15, 18, 31: the event-aligned observation builder never reads
banned queue/occupancy fields, and -- critically -- offline batch slicing
and incremental "runtime" accumulation are structurally forced to agree
because both feed the exact same function
(`backend.flow_v3.observations.build_observation_features`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.observability.policy import PublicEvent, public_events_as_of
from backend.flow_v3.observations import BANNED_QUEUE_TERMS, build_observation_features

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def config():
    return load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")


def _completion(event_id, t, station_id, vehicle_id, value):
    return PublicEvent(
        event_id=event_id, simulation_time=t, event_type="STATION_PROCESSING_COMPLETED",
        observability_class="PUBLIC_DIRECT", evidence_source="PLC_SCADA", confidence=0.98,
        station_id=station_id, vehicle_id=vehicle_id, value=value,
    )


def _entry(event_id, t, station_id, vehicle_id, variant):
    return PublicEvent(
        event_id=event_id, simulation_time=t, event_type="VEHICLE_ENTERED_STATION",
        observability_class="PUBLIC_DIRECT", evidence_source="MES", confidence=0.97,
        station_id=station_id, vehicle_id=vehicle_id, vehicle_variant=variant,
    )


def _synthetic_stream(station_id):
    events = []
    event_id = 1
    for i in range(20):
        vehicle_id = f"V{i}"
        variant = ["ICE_SEDAN", "ICE_SUV", "EV"][i % 3]
        t_entry = 100.0 * i
        events.append(_entry(event_id, t_entry, station_id, vehicle_id, variant)); event_id += 1
        events.append(_completion(event_id, t_entry + 72.0, station_id, vehicle_id, 72.0)); event_id += 1
    return sorted(events, key=lambda e: e.simulation_time)


def test_no_banned_queue_terms_ever_reach_a_feature_key(config):
    events = _synthetic_stream("S11")
    features = build_observation_features(
        public_events_upto_t=public_events_as_of(events, 950.0),
        station_id="S11", observation_time=950.0, config=config,
    )
    for key in features:
        for term in BANNED_QUEUE_TERMS:
            assert term not in key.lower(), f"banned term {term!r} leaked into feature {key!r}"


def test_offline_slicing_and_incremental_runtime_replay_agree(config):
    """Section 31 parity: offline uses `public_events_as_of` on the full
    stream; runtime accumulates events one at a time as they arrive. Both
    paths must hand the identical filtered list to the identical function."""
    full_stream = _synthetic_stream("S11")
    cutoff = 950.0

    offline_visible = public_events_as_of(full_stream, cutoff)
    offline_features = build_observation_features(
        public_events_upto_t=offline_visible, station_id="S11", observation_time=cutoff, config=config,
    )

    runtime_buffer: list[PublicEvent] = []
    for event in full_stream:
        if event.simulation_time > cutoff:
            break
        runtime_buffer.append(event)
    runtime_features = build_observation_features(
        public_events_upto_t=list(runtime_buffer), station_id="S11", observation_time=cutoff, config=config,
    )

    assert offline_visible == runtime_buffer
    assert offline_features == runtime_features


def test_events_strictly_after_the_cutoff_never_change_the_result(config):
    """A future-mutation leakage check: appending/altering events after the
    cutoff must not change features computed at that cutoff, since both
    call sites always pre-filter before calling the shared function."""
    stream = _synthetic_stream("S11")
    cutoff = 950.0
    baseline = build_observation_features(
        public_events_upto_t=public_events_as_of(stream, cutoff), station_id="S11",
        observation_time=cutoff, config=config,
    )

    mutated = list(stream) + [_completion(9999, cutoff + 1.0, "S11", "VFUTURE", 999.0)]
    mutated_result = build_observation_features(
        public_events_upto_t=public_events_as_of(mutated, cutoff), station_id="S11",
        observation_time=cutoff, config=config,
    )
    assert baseline == mutated_result


def test_static_group_reflects_config_not_observed_history(config):
    events = _synthetic_stream("S20")
    features = build_observation_features(
        public_events_upto_t=public_events_as_of(events, 950.0),
        station_id="S20", observation_time=950.0, config=config,
    )
    assert features["station_type"] == config.stations["S20"].station_type
    assert features["baseline_cycle_time_seconds"] == config.stations["S20"].baseline_cycle_time_seconds
