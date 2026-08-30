"""Section 19: interpretable dimensionality reduction -- constants,
near-constants, duplicates, then TRAIN-only correlation filtering
preferring the more causal/interpretable feature. No PCA."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.flow_v3.feature_selection import select_features


def _train_df(n=200, seed=1):
    rng = np.random.RandomState(seed)
    base = rng.normal(size=n)
    return pd.DataFrame({
        "baseline_cycle_time_seconds": np.full(n, 72.0),  # constant
        "rare_flag": np.where(rng.random(n) < 0.005, 1.0, 0.0),  # near-constant
        "svc_cycle_time_ratio_to_baseline": base,
        "svc_cycle_time_trend_seconds": base * 2.0 + rng.normal(scale=0.001, size=n),  # ~duplicate of base (highly correlated)
        "duplicate_of_ratio": base.copy(),  # exact duplicate values
        "ms_rate_per_minute": rng.normal(size=n),
        "station_type": rng.choice(["A", "B"], size=n),
    })


def test_constant_and_near_constant_dropped():
    df = _train_df()
    report = select_features(df, list(df.columns))
    assert "baseline_cycle_time_seconds" in report.dropped_constant
    assert "rare_flag" in report.dropped_near_constant


def test_exact_duplicate_dropped():
    df = _train_df()
    report = select_features(df, list(df.columns))
    assert "duplicate_of_ratio" in report.dropped_duplicate


def test_highly_correlated_pair_drops_the_less_causal_one():
    df = _train_df()
    report = select_features(df, list(df.columns))
    # svc_cycle_time_trend_seconds is ~perfectly correlated with the
    # interpretable ratio feature and carries lower causal priority
    # ("trend" suffix) -- it should be the one dropped, not the ratio.
    assert "svc_cycle_time_trend_seconds" in [d for d, _, _ in report.dropped_correlated]
    assert "svc_cycle_time_ratio_to_baseline" in report.kept_features


def test_counts_are_monotonically_non_increasing_and_categorical_survives():
    df = _train_df()
    report = select_features(df, list(df.columns))
    assert report.raw_count >= report.after_basic_filter >= report.after_correlation_filter
    assert "station_type" in report.kept_features


def test_report_is_json_serializable_dict():
    df = _train_df()
    report = select_features(df, list(df.columns))
    as_dict = report.as_dict()
    assert as_dict["final_count"] == len(report.kept_features)
    assert isinstance(as_dict["dropped_correlated"], list)
