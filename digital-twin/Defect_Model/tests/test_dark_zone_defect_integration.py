from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from Defect_Model.defect_main import build_pipeline
from Defect_Model.runtime.dark_zone_adapter import DefectDarkZoneAdapter


ROOT = Path(__file__).resolve().parents[2]
BASE_RUN = ROOT / "bottlenecks_prediction" / "data" / "input" / "current_run"
HISTORY = ROOT / "bottlenecks_prediction" / "data" / "calibration" / "history" / "train_182_gradual"
DARK_ZONE_DIR = ROOT / "bottlenecks_prediction" / "dark_zone"


def _make_files(tmp_path: Path, *, units_count: int = 1, sensor=True, manual=True, checkpoints=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    stations = pd.read_csv(BASE_RUN / "stations.csv")
    stations.to_csv(tmp_path / "stations.csv", index=False)
    units = pd.read_csv(BASE_RUN / "units.csv").head(units_count).copy()
    units.to_csv(tmp_path / "units.csv", index=False)
    pd.DataFrame([{
        "dark_zone_id": "DZ_TEST",
        "name": "Dark S12-S15",
        "start_station_id": "S12",
        "end_station_id": "S15",
        "sensor_telemetry": str(bool(sensor)).lower(),
        "manual_checks": str(bool(manual)).lower(),
        "checkpoints": str(bool(checkpoints)).lower(),
    }]).to_csv(tmp_path / "dz.csv", index=False)
    return stations, units


def _pipeline(tmp_path: Path, *, units_count: int = 1, sensor=True, manual=True, checkpoints=True, sensor_conf=0.55, random_seed=None):
    _, units = _make_files(
        tmp_path,
        units_count=units_count,
        sensor=sensor,
        manual=manual,
        checkpoints=checkpoints,
    )
    adapter = DefectDarkZoneAdapter(
        stations_csv=tmp_path / "stations.csv",
        dz_csv=tmp_path / "dz.csv",
        units_csv=tmp_path / "units.csv",
        history_runs=[HISTORY],
        runtime_dir=tmp_path / "dark_runtime",
        dark_zone_dir=DARK_ZONE_DIR,
        run_id="DARK_TEST",
        corridor_particles=250,
        random_seed=random_seed,
        transition_confidence=0.35,
        sensor_assignment_confidence=sensor_conf,
    )
    pipe = build_pipeline(
        stations_csv=tmp_path / "stations.csv",
        units_csv=tmp_path / "units.csv",
        run_id="DARK_TEST",
        explain_mode="off",
        dark_adapter=adapter,
    )
    return pipe, adapter, [str(v) for v in units["unit_id"]]


def test_dark_sensor_attribution_is_monotonic_and_causal(tmp_path: Path):
    pipe, adapter, units = _pipeline(tmp_path)
    uid = units[0]

    records = [
        {"stream": "station_event", "timestamp_ms": 0, "station_id": "S12", "unit_id": uid,
         "event_type": "DARK_ZONE_ENTERED", "event_sequence": 1},
        {"stream": "sensor_reading", "timestamp_ms": 35_000, "station_id": "S13",
         "sensor_type": "TORQUE", "value": 10.0},
        {"stream": "evidence", "timestamp_ms": 36_000, "station_id": "S13", "unit_id": uid,
         "event_type": "RFID_CHECKPOINT", "checkpoint_progress": 0.45, "event_sequence": 3},
        {"stream": "sensor_reading", "timestamp_ms": 40_000, "station_id": "S13",
         "sensor_type": "TORQUE", "value": 12.0},
        {"stream": "sensor_reading", "timestamp_ms": 80_000, "station_id": "S14",
         "sensor_type": "VIBRATION", "value": 1.5},
        {"stream": "station_event", "timestamp_ms": 130_000, "station_id": "S16", "unit_id": uid,
         "event_type": "DARK_ZONE_EXITED", "event_sequence": 6},
        {"stream": "station_event", "timestamp_ms": 130_000, "station_id": "S16", "unit_id": uid,
         "event_type": "UNIT_ARRIVED", "event_sequence": 7, "queue_length_after": 1},
    ]

    predictions = []
    for record in records:
        predictions.extend(pipe.process_record(record))

    dark_stations = [p.station_id for p in predictions if p.route == "DARK_INFERRED"]
    assert dark_stations == ["S12", "S13", "S14"]
    assert all(a < b for a, b in zip(
        [adapter._station_index[s] for s in dark_stations],
        [adapter._station_index[s] for s in dark_stations][1:],
    ))

    # S13 torque remains unavailable until the inferred transition to S14.
    torque = pipe.features._sensor_history[uid]["TORQUE"]
    assert [(t, sidx, value, available) for t, sidx, value, available in torque] == [
        (35_000, 12, 10.0, 80_000),
        (40_000, 12, 12.0, 80_000),
    ]
    # S14 telemetry only becomes available at the observable corridor exit.
    vibration = pipe.features._sensor_history[uid]["VIBRATION"]
    assert vibration == [(80_000, 13, 1.5, 130_000)]

    cycles = pipe.features._cycle_history[uid]
    assert [sidx for _, sidx, _ in cycles] == [11, 12, 13]
    assert all(value > 0 for _, _, value in cycles)
    assert adapter.diagnostics()["backward_transitions_suppressed"] >= 1


def test_ambiguous_dark_sensor_is_not_guessed(tmp_path: Path):
    pipe, adapter, units = _pipeline(tmp_path, units_count=2, sensor_conf=0.60)
    u1, u2 = units
    for seq, uid in enumerate((u1, u2), 1):
        pipe.process_record({
            "stream": "station_event", "timestamp_ms": 0, "station_id": "S12",
            "unit_id": uid, "event_type": "DARK_ZONE_ENTERED", "event_sequence": seq,
        })

    pipe.process_record({
        "stream": "sensor_reading", "timestamp_ms": 1_000, "station_id": "S12",
        "sensor_type": "CURRENT", "value": 12.5,
    })

    assert pipe.features._dark_pending_sensors == {}
    diag = pipe.features.diagnostics()
    assert diag["dark_sensor_readings_dropped_low_confidence"] == 1
    assert adapter.diagnostics()["sensor_association_low_confidence"] == 1


def test_hidden_dark_processing_truth_is_rejected(tmp_path: Path):
    pipe, _, units = _pipeline(tmp_path)
    with pytest.raises(RuntimeError, match="Hidden DARK processing event leaked"):
        pipe.process_record({
            "stream": "station_event", "timestamp_ms": 1, "station_id": "S13",
            "unit_id": units[0], "event_type": "PROCESSING_STARTED", "event_sequence": 1,
        })


def test_dark_observability_flags_are_enforced(tmp_path: Path):
    pipe, _, units = _pipeline(tmp_path, sensor=False, manual=False, checkpoints=False)
    uid = units[0]
    pipe.process_record({
        "stream": "station_event", "timestamp_ms": 0, "station_id": "S12",
        "unit_id": uid, "event_type": "DARK_ZONE_ENTERED", "event_sequence": 1,
    })
    with pytest.raises(RuntimeError, match="sensor_telemetry=false"):
        pipe.process_record({
            "stream": "sensor_reading", "timestamp_ms": 10, "station_id": "S12",
            "sensor_type": "TORQUE", "value": 1.0,
        })
    with pytest.raises(RuntimeError, match="manual_checks=false"):
        pipe.process_record({
            "stream": "manual_check", "timestamp_ms": 11, "station_id": "S12",
            "unit_id": uid, "check_type": "VISUAL", "result": "PASS",
        })
    with pytest.raises(RuntimeError, match="checkpoints=false"):
        pipe.process_record({
            "stream": "evidence", "timestamp_ms": 12, "station_id": "S13",
            "unit_id": uid, "event_type": "RFID_CHECKPOINT", "checkpoint_progress": 0.45,
        })


def test_dark_reconstruction_is_reproducible_when_seeded(tmp_path: Path):
    records = [
        {"stream": "station_event", "timestamp_ms": 0, "station_id": "S12",
         "unit_id": None, "event_type": "DARK_ZONE_ENTERED", "event_sequence": 1},
    ]
    # Use the same concrete unit id in both independently constructed consumers.
    p1, _, units1 = _pipeline(tmp_path / "a", random_seed=2026)
    p2, _, units2 = _pipeline(tmp_path / "b", random_seed=2026)
    uid1, uid2 = units1[0], units2[0]
    sequence = [
        {"stream": "station_event", "timestamp_ms": 0, "station_id": "S12",
         "event_type": "DARK_ZONE_ENTERED", "event_sequence": 1},
        {"stream": "sensor_reading", "timestamp_ms": 35_000, "station_id": "S13",
         "sensor_type": "TORQUE", "value": 10.0},
        {"stream": "evidence", "timestamp_ms": 36_000, "station_id": "S13",
         "event_type": "RFID_CHECKPOINT", "checkpoint_progress": 0.45, "event_sequence": 3},
        {"stream": "sensor_reading", "timestamp_ms": 80_000, "station_id": "S14",
         "sensor_type": "VIBRATION", "value": 1.5},
        {"stream": "station_event", "timestamp_ms": 130_000, "station_id": "S16",
         "event_type": "DARK_ZONE_EXITED", "event_sequence": 5},
    ]
    packets = []
    for pipe, uid in ((p1, uid1), (p2, uid2)):
        emitted = []
        for record in sequence:
            item = dict(record)
            if item["stream"] in {"station_event", "evidence"}:
                item["unit_id"] = uid
            emitted.extend(pipe.process_record_packets(item))
        packets.append(emitted)

    left, right = packets
    assert [(p.station_id, p.route, p.prediction_trigger) for p in left] == [
        (p.station_id, p.route, p.prediction_trigger) for p in right
    ]
    assert len(left) == len(right) > 0
    for a, b in zip(left, right):
        assert a.state_confidence == pytest.approx(b.state_confidence, abs=0.0)
        for name in a.features_30:
            av, bv = a.features_30[name], b.features_30[name]
            if pd.isna(av) and pd.isna(bv):
                continue
            assert av == pytest.approx(bv, abs=0.0) if isinstance(av, (int, float)) else av == bv


def test_defect_dark_default_seed_contract_is_run_stable():
    import hashlib
    def expected(run_id: str) -> int:
        return int.from_bytes(hashlib.sha256(run_id.encode("utf-8")).digest()[:4], "big", signed=False)
    assert expected("SEED_RUN") == expected("SEED_RUN")
    assert expected("SEED_RUN") != expected("OTHER_RUN")


def test_retrospective_pf_transition_recovers_dark_history_without_rewinding(tmp_path: Path):
    """Late PF history is accepted now while physical dwell stays retrospective."""
    from types import SimpleNamespace

    pipe, adapter, units = _pipeline(tmp_path, random_seed=2026)
    uid = units[0]

    # Establish S12 at t=1,000 and advance the causal runtime clock to t=2,000.
    pipe.process_record({
        "stream": "station_event", "timestamp_ms": 1_000, "station_id": "S12",
        "unit_id": uid, "event_type": "DARK_ZONE_ENTERED", "event_sequence": 1,
    })
    pipe.process_record({
        "stream": "manual_check", "timestamp_ms": 2_000, "station_id": "S12",
        "unit_id": uid, "check_type": "VISUAL", "result": "PASS",
    })
    assert pipe.features._last_stream_timestamp == 2_000

    # At causal time 3,000 the PF learns that the physical S12->S13 transition
    # most likely occurred at 1,500.  Emit the S13 prediction NOW, never at 1,500,
    # while recovering the 500 ms inferred S12 dwell for the 30-feature history.
    pf_packet = SimpleNamespace(
        route="DARK_CORRIDOR",
        vehicle_id=uid,
        station_id="S13",
        prediction_time_ms=1_500,
        trigger="corridor_checkpoint",
        dashboard_state={"state_confidence": 0.9},
        features_28={"state_confidence": 0.9, "current_occupancy": 1.0},
    )
    arrivals = adapter._packet_arrivals([pf_packet], observed_at_ms=3_000)
    assert len(arrivals) == 1
    assert arrivals[0].timestamp_ms == 3_000
    assert arrivals[0].estimated_transition_time_ms == 1_500

    packets = pipe._packets_from_dark_arrivals(arrivals)
    assert len(packets) == 1
    assert packets[0].prediction_time_ms == 3_000
    assert packets[0].transition_confirmation_lag_ms == 1_500
    assert packets[0].features_30["cycle_history_max"] == pytest.approx(500.0)
    assert pipe.features._last_stream_timestamp == 3_000

    cycles = pipe.features._cycle_history[uid]
    assert cycles[-1] == (1_500, adapter._station_index["S12"], 500.0)
    diag = adapter.diagnostics()
    assert diag["stale_retrospective_transitions_dropped"] == 0
    assert diag["stale_retrospective_transitions_recovered"] >= 1
    assert diag["max_stale_transition_lag_ms"] >= 1_500
    fdiag = pipe.features.diagnostics()
    assert fdiag["dark_cycle_intervals_from_pf_estimates"] >= 1


def test_multiple_late_dark_transitions_are_recovered_in_station_order(tmp_path: Path):
    """One late observation can safely reveal multiple forward station steps."""
    from types import SimpleNamespace

    pipe, adapter, units = _pipeline(tmp_path, random_seed=2026)
    uid = units[0]
    pipe.process_record({
        "stream": "station_event", "timestamp_ms": 1_000, "station_id": "S12",
        "unit_id": uid, "event_type": "DARK_ZONE_ENTERED", "event_sequence": 1,
    })

    # Deliberately reverse packet order to mimic an estimator batch whose newest
    # posterior state appears first. The adapter must recover S13 before S14.
    packets = [
        SimpleNamespace(
            route="DARK_CORRIDOR", vehicle_id=uid, station_id="S14",
            prediction_time_ms=2_200, trigger="corridor_checkpoint",
            dashboard_state={"state_confidence": 0.95},
            features_28={"state_confidence": 0.95, "current_occupancy": 1.0},
        ),
        SimpleNamespace(
            route="DARK_CORRIDOR", vehicle_id=uid, station_id="S13",
            prediction_time_ms=1_500, trigger="corridor_checkpoint",
            dashboard_state={"state_confidence": 0.95},
            features_28={"state_confidence": 0.95, "current_occupancy": 1.0},
        ),
    ]
    arrivals = adapter._transitions_from_packets(packets, observed_at_ms=3_000)
    assert [a.station_id for a in arrivals] == ["S13", "S14"]
    assert [a.timestamp_ms for a in arrivals] == [3_000, 3_000]
    assert [a.estimated_transition_time_ms for a in arrivals] == [1_500, 2_200]

    feature_packets = pipe._packets_from_dark_arrivals(arrivals)
    assert [p.station_id for p in feature_packets] == ["S13", "S14"]
    cycles = pipe.features._cycle_history[uid]
    assert [row[1] for row in cycles[-2:]] == [
        adapter._station_index["S12"], adapter._station_index["S13"]
    ]
    assert [row[2] for row in cycles[-2:]] == pytest.approx([500.0, 700.0])
    assert pipe.features._last_stream_timestamp == 3_000
