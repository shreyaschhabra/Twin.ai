from __future__ import annotations

import math
import numpy as np
import pandas as pd

from dark_zone_feature_reconstructor import (
    DarkZoneFeatureReconstructor,
    StationFeatureState,
    FEATURES_28,
)


def _stations():
    return pd.DataFrame([
        {"station_id":"S1","archetype":"MANUAL","base_cycle_time_ms":60000,"cycle_time_std_ms":5000,"buffer_capacity":4},
        {"station_id":"S2","archetype":"AUTO","base_cycle_time_ms":50000,"cycle_time_std_ms":4000,"buffer_capacity":3},
        {"station_id":"S10","archetype":"AUTO","base_cycle_time_ms":70000,"cycle_time_std_ms":6000,"buffer_capacity":5},
    ])


def test_frozen_schema_and_station_index():
    r = DarkZoneFeatureReconstructor(_stations())
    assert len(FEATURES_28) == 28
    assert r.static("S1")["station_index"] == 0
    assert r.static("S2")["station_index"] == 1
    assert r.static("S10")["station_index"] == 9  # numeric station number - 1, not row order


def test_light_zone_queue_window_semantics():
    r = DarkZoneFeatureReconstructor(_stations())
    t = 2_000_000
    hist = [
        {"timestamp_ms": t - 900_000, "queue": 2.0},  # previous 10m
        {"timestamp_ms": t - 500_000, "queue": 4.0},
        {"timestamp_ms": t - 250_000, "queue": 6.0},
        {"timestamp_ms": t, "queue": 8.0},
    ]
    q = r.queue_stats(hist, t, current_occupancy=8.0)
    assert math.isclose(q["recent_mean"], 6.0)
    assert math.isclose(q["recent_std"], 2.0)  # sample std, ddof=1
    assert math.isclose(q["recent_max"], 8.0)
    assert math.isclose(q["previous_mean"], 2.0)
    assert math.isclose(q["delta"], 4.0)
    assert math.isclose(q["slope"], 8e-6, rel_tol=1e-10)
    assert abs(q["slope_std"]) < 1e-15


def test_rate_and_uncertainty_units_match_training():
    r = DarkZoneFeatureReconstructor(_stations())
    t = 2_000_000
    state = StationFeatureState(
        current_occupancy=2.0,
        queue_history=[],
        arrival_times_ms=[t - 500_000, t - 100_000, t - 800_000],
        service_times_ms=[t - 300_000, t - 900_000],
        cycle_history=[],
        occupancy_std=0.5,
        state_confidence=0.8,
    )
    counts = r.rate_counts(state, t)
    assert counts == {"arrivals10": 2, "arrivals_prev": 1, "services10": 1, "services_prev": 1}

    q = {"slope": 8e-6, "slope_std": 0.0}
    conf, progress_std, eta_std = r._model_uncertainty(q, headroom=2.0, state=state)
    assert math.isclose(conf, 0.8)
    assert math.isclose(progress_std, 0.5)  # queue units, not vehicle-progress fraction
    assert math.isclose(eta_std, 62_500.0)  # ms: 0.5 / (8e-6 queue/ms)


def test_eta_std_near_zero_slope_is_missing_not_huge():
    r = DarkZoneFeatureReconstructor(_stations())
    state = StationFeatureState(
        current_occupancy=2.0,
        queue_history=[], arrival_times_ms=[], service_times_ms=[], cycle_history=[],
        occupancy_std=0.5, state_confidence=0.8,
    )
    # Positive but effectively-flat slope: implied time-to-capacity is far
    # beyond the 1-hour guard horizon. This must not emit an enormous finite value.
    q = {"slope": 1e-12, "slope_std": 1e-13}
    conf, progress_std, eta_std = r._model_uncertainty(q, headroom=2.0, state=state)
    assert math.isclose(conf, 0.8)
    assert math.isclose(progress_std, 0.5)
    assert np.isnan(eta_std)


if __name__ == "__main__":
    test_frozen_schema_and_station_index()
    test_light_zone_queue_window_semantics()
    test_rate_and_uncertainty_units_match_training()
    test_eta_std_near_zero_slope_is_missing_not_huge()
    print("All reconstructor contract tests passed.")
