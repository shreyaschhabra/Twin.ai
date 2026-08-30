from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.flow_v3.headway_sweep import aggregate_runs, measure_healthy_run
from backend.simulation.engine import run_simulation

ROOT = Path(__file__).resolve().parent.parent


def test_healthy_run_metrics_are_deterministic_and_physically_bounded():
    config = load_factory_config(ROOT / "configs" / "station_types.yaml", ROOT / "configs" / "full_line.yaml")
    kwargs = dict(
        config=config,
        n_vehicles=30,
        seed=991,
        mean_interarrival_seconds=115.0,
        std_interarrival_seconds=15.0,
    )
    first = measure_healthy_run(run_simulation(**kwargs), config, headway_seconds=115.0, seed=991)
    second = measure_healthy_run(run_simulation(**kwargs), config, headway_seconds=115.0, seed=991)
    assert first == second
    assert first["vehicles_completed"] == 30
    assert 0 <= first["mean_buffer_occupancy_ratio_time_weighted"] <= 1
    assert 0 <= first["p95_buffer_occupancy_ratio_time_weighted"] <= 1
    assert 0 <= first["max_single_buffer_p95_occupancy_ratio_time_weighted"] <= 1
    assert 0 <= first["p95_buffer_occupancy_ratio_at_state_changes"] <= 1
    assert 0 <= first["max_buffer_occupancy_ratio"] <= 1
    assert first["throughput_constraint_station_id"] == "S22"
    assert first["physical_rho_max"] == pytest.approx(90.64 / 115.0)


def test_aggregate_preserves_independent_run_count():
    rows = [
        {
            "headway_seconds": 115.0,
            "blocked_episode_count": 0,
            "total_blocked_seconds": 0.0,
            "throughput_vehicles_per_hour_full_run": 20.0,
            "throughput_vehicles_per_hour_steady": 30.0,
            "completion_headway_cv_steady": 0.1,
            "blocked_fraction_of_station_time": 0.0,
            "total_starved_seconds": 100.0,
            "starved_fraction_of_station_time": 0.8,
            "mean_buffer_occupancy_ratio_time_weighted": 0.01,
            "p95_buffer_occupancy_ratio_time_weighted": 0.0,
            "max_single_buffer_p95_occupancy_ratio_time_weighted": 0.25,
            "p95_buffer_occupancy_ratio_at_state_changes": 0.25,
            "max_buffer_occupancy_ratio": 0.5,
            "mean_line_wip_time_weighted": 20.0,
            "physical_rho_max": 0.8,
            "throughput_constraint_station_id": "S22",
            "physical_headroom_station_count_lt_65pct": 42,
            "physical_moderate_station_count_65_75pct": 2,
            "physical_sensitive_station_count_75_95pct": 1,
            "physical_overloaded_station_count_ge_95pct": 0,
        }
        for _ in range(5)
    ]
    aggregate = aggregate_runs(rows)[0]
    assert aggregate["run_count"] == 5
    assert aggregate["healthy_runs_with_any_blocking"] == 0
    assert aggregate["mean_throughput_vehicles_per_hour_steady"] == 30.0
