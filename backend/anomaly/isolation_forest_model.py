"""
Isolation Forest anomaly layer (Section 25): unsupervised, trained on
nominal/low-risk operational samples only. No neural networks, no
autoencoders.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

DEFAULT_ANOMALY_FEATURES = [
    "cycle_time_dev_relative", "cycle_time_std_5m", "inbound_occupancy_ratio",
    "inbound_growth_5m", "prop_blocked_5m", "prop_down_5m", "microstop_duration_5m",
    "sensor_mean_dev_5m", "sensor_std_5m", "arrival_minus_departure_5m",
]


def train_isolation_forest(nominal_df: pd.DataFrame, features: List[str] = None, seed: int = 20240002) -> Pipeline:
    """nominal_df should already be filtered to low-risk/negative-label
    operational rows (never fit on EQUIPMENT_DEGRADATION holdout rows --
    that partition is reserved entirely for post-hoc evaluation, see
    Section 27)."""
    features = features or [f for f in DEFAULT_ANOMALY_FEATURES if f in nominal_df.columns]
    pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("iforest", IsolationForest(n_estimators=200, contamination="auto", random_state=seed, n_jobs=-1)),
    ])
    pipe.fit(nominal_df[features])
    return pipe, features


def isolation_forest_anomaly_score(pipe: Pipeline, features: List[str], df: pd.DataFrame) -> np.ndarray:
    """Higher = more anomalous, normalized to roughly [0,1] via a sigmoid
    on the raw (negated) decision_function score."""
    raw = -pipe.named_steps["iforest"].decision_function(pipe.named_steps["impute"].transform(df[features]))
    return 1.0 / (1.0 + np.exp(-raw * 3.0))
