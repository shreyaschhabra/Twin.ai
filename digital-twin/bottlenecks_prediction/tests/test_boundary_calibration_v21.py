from pathlib import Path

import pandas as pd

from factory_models import build_dark_calibration_files


def _write_units(run: Path, unit: str = "U1") -> None:
    pd.DataFrame([{"unit_id": unit, "vehicle_model": "MODEL_A"}]).to_csv(run / "units.csv", index=False)


def _configured(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_boundary_only_corridor_allocates_total_across_all_dark_stations(tmp_path: Path) -> None:
    configured = _configured(tmp_path / "configured.csv", [
        {"station_id":"S02","base_cycle_time_ms":30000,"cycle_time_std_ms":3000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
        {"station_id":"S03","base_cycle_time_ms":40000,"cycle_time_std_ms":4000,"buffer_capacity":4,"sensor_coverage":"NONE"},
        {"station_id":"S04","base_cycle_time_ms":80000,"cycle_time_std_ms":8000,"buffer_capacity":4,"sensor_coverage":"NONE"},
        {"station_id":"S05","base_cycle_time_ms":30000,"cycle_time_std_ms":3000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
    ])
    run = tmp_path / "run_new"; run.mkdir(); _write_units(run)
    pd.DataFrame([
        {"timestamp_ms":1000,"event_type":"DARK_ZONE_ENTERED","station_id":"S03","unit_id":"U1"},
        {"timestamp_ms":121000,"event_type":"DARK_ZONE_EXITED","station_id":"S05","unit_id":"U1"},
    ]).to_csv(run / "station_events.csv", index=False)

    dwell, residence, meta = build_dark_calibration_files(
        [run], configured, tmp_path / "out", dark_station_ids={"S03","S04"}
    )
    assert dwell and residence
    d = pd.read_csv(dwell)
    assert set(d.station_id) == {"S03", "S04"}
    durations = {
        r.station_id: (pd.Timestamp(r.exit_ts) - pd.Timestamp(r.entry_ts)).total_seconds()
        for r in d.itertuples(index=False)
    }
    assert abs(durations["S03"] - 40.0) < 1e-6
    assert abs(durations["S04"] - 80.0) < 1e-6
    assert abs(sum(durations.values()) - 120.0) < 1e-6
    assert meta["source"] == "simulator_dark_boundaries"
    assert meta["corridors"][0]["allocation"] == "configured_cycle_proportional"


def test_boundary_only_single_dark_station_calibrates_from_public_boundaries(tmp_path: Path) -> None:
    configured = _configured(tmp_path / "configured.csv", [
        {"station_id":"S02","base_cycle_time_ms":30000,"cycle_time_std_ms":3000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
        {"station_id":"S03","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NONE"},
        {"station_id":"S04","base_cycle_time_ms":30000,"cycle_time_std_ms":3000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
    ])
    run = tmp_path / "run_single"; run.mkdir(); _write_units(run)
    pd.DataFrame([
        {"timestamp_ms":5000,"event_type":"DARK_ZONE_ENTERED","station_id":"S03","unit_id":"U1"},
        {"timestamp_ms":70000,"event_type":"DARK_ZONE_EXITED","station_id":"S04","unit_id":"U1"},
    ]).to_csv(run / "station_events.csv", index=False)

    dwell, residence, meta = build_dark_calibration_files(
        [run], configured, tmp_path / "out_single", dark_station_ids={"S03"}
    )
    assert dwell is not None
    assert residence is None
    d = pd.read_csv(dwell)
    assert list(d.station_id) == ["S03"]
    duration = (pd.Timestamp(d.iloc[0].exit_ts) - pd.Timestamp(d.iloc[0].entry_ts)).total_seconds()
    assert abs(duration - 65.0) < 1e-6
    assert meta["source"] == "simulator_dark_boundaries"


def test_mixed_old_and_new_history_keeps_both_sources(tmp_path: Path) -> None:
    configured = _configured(tmp_path / "configured.csv", [
        {"station_id":"S02","base_cycle_time_ms":30000,"cycle_time_std_ms":3000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
        {"station_id":"S03","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NONE"},
        {"station_id":"S04","base_cycle_time_ms":30000,"cycle_time_std_ms":3000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
    ])
    old = tmp_path / "run_old"; old.mkdir(); _write_units(old, "UOLD")
    pd.DataFrame([
        {"timestamp_ms":1000,"event_type":"PROCESSING_STARTED","station_id":"S03","unit_id":"UOLD"},
        {"timestamp_ms":61000,"event_type":"PROCESSING_COMPLETED","station_id":"S03","unit_id":"UOLD"},
    ]).to_csv(old / "station_events.csv", index=False)
    new = tmp_path / "run_new"; new.mkdir(); _write_units(new, "UNEW")
    pd.DataFrame([
        {"timestamp_ms":1000,"event_type":"DARK_ZONE_ENTERED","station_id":"S03","unit_id":"UNEW"},
        {"timestamp_ms":71000,"event_type":"DARK_ZONE_EXITED","station_id":"S04","unit_id":"UNEW"},
    ]).to_csv(new / "station_events.csv", index=False)

    dwell, _, meta = build_dark_calibration_files(
        [old, new], configured, tmp_path / "out_mixed", dark_station_ids={"S03"}
    )
    d = pd.read_csv(dwell)
    assert set(d.source_run.astype(str)) == {"run_old", "run_new"}
    assert meta["source"] == "mixed_internal_and_simulator_boundaries"
