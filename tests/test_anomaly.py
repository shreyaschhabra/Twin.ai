"""Tests for the lightweight anomaly layer (Section 49): nominal vs.
abnormal separation, and degradation-holdout isolation from fitting."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from backend.anomaly.combined import anomaly_level, build_anomaly_output
from backend.anomaly.isolation_forest_model import (
    DEFAULT_ANOMALY_FEATURES, isolation_forest_anomaly_score, train_isolation_forest,
)
from backend.anomaly.statistical import ewma_score, rolling_zscore


def _synthetic_frame(n=500, seed=0):
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({
        "cycle_time_dev_relative": rng.normal(0, 0.05, n),
        "cycle_time_std_5m": rng.normal(1.0, 0.1, n),
        "inbound_occupancy_ratio": rng.uniform(0, 0.3, n),
        "inbound_growth_5m": rng.normal(0, 0.05, n),
        "prop_blocked_5m": np.zeros(n),
        "prop_down_5m": rng.uniform(0, 0.05, n),
        "microstop_duration_5m": rng.uniform(0, 5, n),
        "sensor_mean_dev_5m": rng.normal(0, 1.0, n),
        "sensor_std_5m": rng.normal(1.0, 0.1, n),
        "arrival_minus_departure_5m": rng.normal(0, 0.5, n),
    })
    return df


def test_isolation_forest_nominal_vs_abnormal():
    nominal = _synthetic_frame(1000, seed=1)
    pipe, features = train_isolation_forest(nominal)

    nominal_test = _synthetic_frame(200, seed=2)
    abnormal_test = _synthetic_frame(200, seed=3)
    abnormal_test["cycle_time_dev_relative"] += 2.0
    abnormal_test["inbound_occupancy_ratio"] = 0.95
    abnormal_test["prop_blocked_5m"] = 0.8

    nominal_scores = isolation_forest_anomaly_score(pipe, features, nominal_test)
    abnormal_scores = isolation_forest_anomaly_score(pipe, features, abnormal_test)

    assert abnormal_scores.mean() > nominal_scores.mean(), (
        "controlled abnormal input should score higher on average than nominal data"
    )


def test_anomaly_level_thresholds():
    assert anomaly_level(0.1) == "LOW"
    assert anomaly_level(0.5) == "MEDIUM"
    assert anomaly_level(0.9) == "HIGH"


def test_build_anomaly_output_schema():
    out = build_anomaly_output("S26", statistical_score=0.8, iforest_score=0.7, signals=["cycle-time drift"])
    assert out["station_id"] == "S26"
    assert 0 <= out["anomaly_score"] <= 1
    assert out["anomaly_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert out["signals"] == ["cycle-time drift"]


def test_rolling_zscore_flags_a_spike():
    series = pd.Series([1.0] * 30 + [10.0])
    z = rolling_zscore(series, window=20)
    assert abs(z.iloc[-1]) > 3


def test_ewma_score_flags_a_spike():
    series = pd.Series([1.0] * 30 + [10.0])
    e = ewma_score(series)
    assert abs(e.iloc[-1]) > 1.5  # EWMA smooths more than rolling z-score by design


def test_degradation_holdout_unseen_during_fitting():
    import json
    artifact_dir = Path(__file__).resolve().parent.parent / "artifacts" / "anomaly"
    metadata_path = artifact_dir / "metadata.json"
    if not metadata_path.exists():
        import pytest
        pytest.skip("anomaly artifact not built yet")
    with metadata_path.open() as f:
        meta = json.load(f)
    flow_dir = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v2"
    train = pd.read_parquet(flow_dir / "train.parquet")
    n_negative_train = int((train.target == 0).sum())
    assert meta["n_fit_rows"] == n_negative_train, (
        "Isolation Forest fit-row count must equal TRAIN negatives only -- "
        "the degradation holdout must never be included in fitting"
    )
    assert meta["degradation_holdout_diagnostic"]["n_during_rows"] > 0, (
        "the degradation holdout must still be evaluated, just not fit on"
    )
