"""
Flow baselines (Step 5, Sections S/T/U — continuation Sections 16/17).

Baseline 0: always-negative.
Baseline 1: one transparent operational rule, thresholds derived from
            TRAIN only (percentile-based).
Baseline 2: Logistic Regression via sklearn Pipeline/ColumnTransformer,
            preprocessing fit on TRAIN only, class_weight="balanced",
            no SMOTE, no hyperparameter search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC_FEATURES = [
    "last_cycle_time", "cycle_time_mean_1m", "cycle_time_mean_3m", "cycle_time_mean_5m",
    "cycle_time_std_5m", "cycle_time_dev_from_baseline", "cycle_time_dev_relative",
    "cycle_time_slope_5m", "completions_1m", "completions_3m", "completions_5m",
    "microstop_count_5m", "microstop_duration_5m", "time_since_last_microstop",
    "inbound_occupancy_ratio", "inbound_occupancy_max_5m", "inbound_occupancy_mean_5m",
    "inbound_growth_1m", "inbound_growth_3m", "inbound_growth_5m", "inbound_recent_full",
    "outbound_occupancy_ratio", "outbound_growth_3m",
    "arrivals_3m", "arrivals_5m", "arrival_minus_departure_5m", "arrival_rate_trend",
    "mix_ice_sedan_5m", "mix_ice_suv_5m", "mix_ev_5m",
    "sensor_latest_value_dev", "sensor_mean_dev_5m", "sensor_std_5m",
    "sensor_missing_ratio_5m", "sensor_time_since_available",
    "prop_processing_5m", "prop_starved_5m", "prop_blocked_5m", "prop_down_5m",
    "blocked_seconds_5m",
]
CATEGORICAL_FEATURES = ["station_type", "sensor_maturity", "zone"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def build_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    return ColumnTransformer([
        ("num", numeric_pipe, NUMERIC_FEATURES),
        ("cat", categorical_pipe, CATEGORICAL_FEATURES),
    ])


def build_logistic_regression_pipeline() -> Pipeline:
    return Pipeline([
        ("preprocess", build_preprocessor()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
    ])


@dataclass
class RuleThresholds:
    cycle_dev_p75: float
    inbound_ratio_p75: float
    arrival_minus_departure_p75: float


def fit_rule_thresholds(train_df: pd.DataFrame) -> RuleThresholds:
    """Percentile thresholds derived from TRAIN only (Section T: 'if
    percentile-based, must be derived from TRAIN only')."""
    return RuleThresholds(
        cycle_dev_p75=train_df.cycle_time_dev_relative.quantile(0.75),
        inbound_ratio_p75=train_df.inbound_occupancy_ratio.quantile(0.75),
        arrival_minus_departure_p75=train_df.arrival_minus_departure_5m.quantile(0.75),
    )


def apply_rule(df: pd.DataFrame, thresholds: RuleThresholds) -> np.ndarray:
    """Conceptually: cycle-time deviation elevated AND (buffer occupancy
    elevated OR arrivals outpacing departures). Transparent, no tuning
    beyond the three TRAIN-derived percentile thresholds above."""
    cycle_elevated = df.cycle_time_dev_relative.fillna(0) >= thresholds.cycle_dev_p75
    buffer_elevated = df.inbound_occupancy_ratio.fillna(0) >= thresholds.inbound_ratio_p75
    rate_deficit = df.arrival_minus_departure_5m.fillna(0) >= thresholds.arrival_minus_departure_p75
    return (cycle_elevated & (buffer_elevated | rate_deficit)).astype(int).values
