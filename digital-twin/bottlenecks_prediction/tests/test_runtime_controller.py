from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from light_zone.light_zone_runtime import BOTTLENECK_FEATURES
from runtime.runtime_controller import DigitalTwinRuntimeController, derive_dark_topology


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DARK_ZONE_DIR = PROJECT_ROOT / "dark_zone"


def _base_station(station_id: str, coverage: str) -> dict:
    return {
        "station_id": station_id,
        "archetype": "AUTOMATED",
        "base_cycle_time_ms": 60_000,
        "cycle_time_std_ms": 6_000,
        "buffer_capacity": 6,
        "sensor_coverage": coverage,
    }


def _write_units(path: Path) -> None:
    pd.DataFrame([{"unit_id": "U1", "vehicle_model": "A"}]).to_csv(path, index=False)


def _write_historical_dwell(path: Path, station_ids: list[str]) -> None:
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    for station_index, station_id in enumerate(station_ids):
        for i in range(40):
            entry = base + pd.Timedelta(minutes=5 * i + station_index)
            seconds = 55 + station_index * 5 + (i % 5)
            rows.append(
                {
                    "station_id": station_id,
                    "variant": "A",
                    "entry_ts": entry,
                    "exit_ts": entry + pd.Timedelta(seconds=seconds),
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def _event(ts: int, typ: str, station: str, queue=0, cycle=None) -> dict:
    return {
        "event_id": f"E-{ts}-{station}-{typ}",
        "timestamp_ms": ts,
        "event_type": typ,
        "station_id": station,
        "unit_id": "U1",
        "queue_length_after": queue,
        "previous_state": None,
        "new_state": None,
        "cycle_time_ms": cycle,
    }


def test_dark_topology_detects_single_and_corridor() -> None:
    stations = pd.DataFrame(
        [
            _base_station("S02", "NONE"),
            _base_station("S03", "NORMAL"),
            _base_station("S04", "NONE"),
            _base_station("S05", "NONE"),
            _base_station("S06", "NORMAL"),
        ]
    )
    singles, corridors = derive_dark_topology(stations)
    assert singles == {"S02"}
    assert list(corridors) == ["DZ_S04_S05"]
    corridor = corridors["DZ_S04_S05"]
    assert corridor.sequence == ("S04", "S05")
    assert corridor.downstream_light_station == "S06"


def test_isolated_dark_station_keeps_pf_alive_and_emits_28_features(tmp_path: Path) -> None:
    stations_csv = tmp_path / "stations.csv"
    units_csv = tmp_path / "units.csv"
    hist_csv = tmp_path / "historical_dwell.csv"
    pd.DataFrame([
        _base_station("S02", "NONE"),
        _base_station("S03", "NORMAL"),
    ]).to_csv(stations_csv, index=False)
    _write_units(units_csv)
    _write_historical_dwell(hist_csv, ["S02"])

    controller = DigitalTwinRuntimeController(
        configured_stations_csv=stations_csv,
        units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR,
        historical_dwell_csv=hist_csv,
        prediction_interval_s=60.0,
        corridor_particles=100,
        run_id="TEST_SINGLE",
    )

    assert controller.process_event(_event(0, "UNIT_ARRIVED", "S02", queue=2)) == []
    entry_packets = controller.process_event(_event(10_000, "PROCESSING_STARTED", "S02", queue=99))
    assert entry_packets
    assert all(p.route == "DARK_SINGLE" for p in entry_packets)
    assert all(list(p.features_28) == BOTTLENECK_FEATURES for p in entry_packets)

    # The PF remains alive long enough for a scheduled heartbeat.
    heartbeat_packets = controller.advance_time(70_000)
    assert heartbeat_packets
    assert all(p.route == "DARK_SINGLE" for p in heartbeat_packets)

    exit_packets = controller.process_event(
        _event(90_000, "PROCESSING_COMPLETED", "S02", queue=123, cycle=999_999)
    )
    assert exit_packets
    assert all(list(p.features_28) == BOTTLENECK_FEATURES for p in exit_packets)


def test_contiguous_dark_corridor_ignores_internal_hidden_events(tmp_path: Path) -> None:
    stations_csv = tmp_path / "stations.csv"
    units_csv = tmp_path / "units.csv"
    hist_csv = tmp_path / "historical_dwell.csv"
    pd.DataFrame([
        _base_station("S02", "NONE"),
        _base_station("S03", "NONE"),
        _base_station("S04", "NORMAL"),
    ]).to_csv(stations_csv, index=False)
    _write_units(units_csv)
    _write_historical_dwell(hist_csv, ["S02", "S03"])

    controller = DigitalTwinRuntimeController(
        configured_stations_csv=stations_csv,
        units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR,
        historical_dwell_csv=hist_csv,
        prediction_interval_s=10_000.0,  # avoid periodic ticks inside this short test
        corridor_particles=100,
        run_id="TEST_CORRIDOR",
    )

    entry = controller.process_event(_event(0, "PROCESSING_STARTED", "S02", queue=999))
    assert entry
    assert all(p.route == "DARK_CORRIDOR" for p in entry)

    # S03 is internal to the dark corridor. These simulator-truth events must not
    # generate model packets or be treated as observable queue/cycle truth.
    assert controller.process_event(_event(20_000, "UNIT_ARRIVED", "S03", queue=999)) == []
    assert controller.process_event(_event(30_000, "PROCESSING_STARTED", "S03", queue=999)) == []

    exit_packets = controller.process_event(
        _event(120_000, "PROCESSING_COMPLETED", "S03", queue=999, cycle=999_999)
    )
    assert exit_packets
    assert all(p.route == "DARK_CORRIDOR" for p in exit_packets)
    assert all(list(p.features_28) == BOTTLENECK_FEATURES for p in exit_packets)


def test_zero_buffer_station_is_not_emitted_to_model(tmp_path: Path) -> None:
    stations_csv = tmp_path / "stations.csv"
    units_csv = tmp_path / "units.csv"
    pd.DataFrame([
        {**_base_station("S01", "NORMAL"), "buffer_capacity": 0},
        _base_station("S02", "NORMAL"),
    ]).to_csv(stations_csv, index=False)
    _write_units(units_csv)

    controller = DigitalTwinRuntimeController(
        configured_stations_csv=stations_csv,
        units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR,
        run_id="TEST_ZERO_BUFFER",
    )

    assert controller.process_event(_event(0, "UNIT_ARRIVED", "S01", queue=0)) == []
    assert "S01" in controller.topology_summary()["model_ineligible_stations"]

    packets = controller.process_event(_event(1_000, "UNIT_ARRIVED", "S02", queue=1))
    assert len(packets) == 1
    assert packets[0].station_id == "S02"

def test_corridor_enters_from_upstream_light_completion_and_does_not_double_enter(tmp_path: Path) -> None:
    stations_csv = tmp_path / "stations.csv"
    units_csv = tmp_path / "units.csv"
    hist_csv = tmp_path / "historical_dwell.csv"
    pd.DataFrame([
        _base_station("S02", "NORMAL"),
        _base_station("S03", "NONE"),
        _base_station("S04", "NONE"),
        _base_station("S05", "NORMAL"),
    ]).to_csv(stations_csv, index=False)
    pd.DataFrame([
        {"unit_id": "U1", "vehicle_model": "A"},
        {"unit_id": "U2", "vehicle_model": "A"},
    ]).to_csv(units_csv, index=False)
    _write_historical_dwell(hist_csv, ["S03", "S04"])

    controller = DigitalTwinRuntimeController(
        configured_stations_csv=stations_csv,
        units_csv=units_csv,
        dark_zone_dir=DARK_ZONE_DIR,
        historical_dwell_csv=hist_csv,
        prediction_interval_s=10_000.0,
        corridor_particles=100,
        run_id="TEST_UPSTREAM_BOUNDARY",
    )

    corridor = controller.corridor_defs["DZ_S03_S04"]
    assert corridor.upstream_light_station == "S02"

    first = controller.process_event(_event(0, "PROCESSING_COMPLETED", "S02", queue=0, cycle=60_000))
    assert any(p.route == "DARK_CORRIDOR" and p.trigger == "corridor_entry" for p in first)
    assert "U1" in controller.corridor_bridge.active

    # The old boundary must no longer create a second corridor entry.
    assert controller.process_event(_event(5_000, "PROCESSING_STARTED", "S03", queue=999)) == []
    assert len(controller.corridor_bridge.active) == 1

    # A second upstream completion is visible before S03 processing begins, so
    # the first DARK station now has a non-zero inferred waiting population.
    second_event = _event(6_000, "PROCESSING_COMPLETED", "S02", queue=0, cycle=60_000)
    second_event["unit_id"] = "U2"
    second = controller.process_event(second_event)
    dark_entry = next(p for p in second if p.route == "DARK_CORRIDOR")
    assert dark_entry.station_id == "S03"
    assert float(dark_entry.features_28["current_occupancy"]) > 0.5
