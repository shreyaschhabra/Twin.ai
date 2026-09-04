from pathlib import Path
import pandas as pd

from config.configure_stations import configure_from_dz, dark_stations_from_dz


def test_dz_is_authoritative_over_sensor_coverage(tmp_path: Path) -> None:
    stations = pd.DataFrame([
        {"station_id": "S11", "sensor_coverage": "NONE"},
        {"station_id": "S12", "sensor_coverage": "HIGH"},
        {"station_id": "S13", "sensor_coverage": "NONE"},
        {"station_id": "S14", "sensor_coverage": "PARTIAL"},
        {"station_id": "S15", "sensor_coverage": "HIGH"},
        {"station_id": "S16", "sensor_coverage": "NONE"},
    ])
    stations_csv = tmp_path / "stations.csv"
    dz_csv = tmp_path / "dz.csv"
    stations.to_csv(stations_csv, index=False)
    pd.DataFrame([{"dark_zone_id":"DZ1","start_station_id":"S12","end_station_id":"S15"}]).to_csv(dz_csv, index=False)

    assert dark_stations_from_dz(stations, dz_csv) == {"S12","S13","S14","S15"}
    configured, dark = configure_from_dz(stations_csv, dz_csv)
    assert dark == {"S12","S13","S14","S15"}
    got = dict(zip(configured.station_id, configured.sensor_coverage))
    assert got["S11"] == "NORMAL"
    assert got["S12"] == "NONE"
    assert got["S15"] == "NONE"
    assert got["S16"] == "NORMAL"


def test_factory_runtime_contract_rejects_different_dark_topology(tmp_path: Path) -> None:
    from config.configure_stations import validate_runtime_topology_match

    stations = pd.DataFrame([
        {"station_id":"S01","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":0,"sensor_coverage":"HIGH"},
        {"station_id":"S02","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"HIGH"},
        {"station_id":"S03","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"HIGH"},
    ])
    stations_csv = tmp_path / "stations.csv"
    stations.to_csv(stations_csv, index=False)

    expected = stations.copy()
    expected["sensor_coverage"] = ["NORMAL", "NONE", "NORMAL"]
    expected_csv = tmp_path / "expected.csv"
    expected.to_csv(expected_csv, index=False)

    dz_csv = tmp_path / "dz.csv"
    pd.DataFrame([{"dark_zone_id":"DZ1","start_station_id":"S03","end_station_id":"S03"}]).to_csv(dz_csv, index=False)

    import pytest
    with pytest.raises(ValueError, match="selected factory model contract"):
        validate_runtime_topology_match(expected_csv, stations_csv, dz_csv)


def test_factory_runtime_contract_accepts_matching_static_and_dark_topology(tmp_path: Path) -> None:
    from config.configure_stations import validate_runtime_topology_match

    stations = pd.DataFrame([
        {"station_id":"S01","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":0,"sensor_coverage":"HIGH"},
        {"station_id":"S02","archetype":"AUTOMATED","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"PARTIAL"},
        {"station_id":"S03","archetype":"MANUAL","base_cycle_time_ms":80000,"cycle_time_std_ms":8000,"buffer_capacity":4,"sensor_coverage":"HIGH"},
    ])
    stations_csv = tmp_path / "stations.csv"
    stations.to_csv(stations_csv, index=False)
    dz_csv = tmp_path / "dz.csv"
    pd.DataFrame([{"dark_zone_id":"DZ1","start_station_id":"S02","end_station_id":"S03"}]).to_csv(dz_csv, index=False)

    expected, _ = configure_from_dz(stations_csv, dz_csv)
    expected_csv = tmp_path / "expected.csv"
    expected.to_csv(expected_csv, index=False)

    current, dark = validate_runtime_topology_match(expected_csv, stations_csv, dz_csv)
    assert dark == {"S02", "S03"}
    assert set(current.loc[current.sensor_coverage.eq("NONE"), "station_id"]) == dark
