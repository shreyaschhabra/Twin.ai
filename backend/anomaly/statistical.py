"""
Statistical anomaly layer (Section 25): rolling z-score and EWMA only --
deliberately not a full SPC engine. Operates on the already-computed
Flow point-in-time features (backend/flow/features.py), never on raw
events, so it's trivially leakage-safe (the same point-in-time guarantees
already verified for Flow apply here unchanged).
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

# A handful of features whose deviation is directly interpretable as an
# operational anomaly signal, each with a human-readable label used in
# the final "signals" list.
SIGNAL_FEATURES = {
    "cycle_time_dev_relative": "cycle-time drift",
    "sensor_mean_dev_5m": "sensor deviation",
    "inbound_occupancy_ratio": "buffer occupancy rise",
    "prop_blocked_5m": "blocking exposure",
    "microstop_duration_5m": "micro-stop activity",
}
Z_THRESHOLD = 2.5


def rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    mean = series.rolling(window, min_periods=3).mean()
    std = series.rolling(window, min_periods=3).std().replace(0, np.nan)
    return (series - mean) / std


def ewma_score(series: pd.Series, alpha: float = 0.2) -> pd.Series:
    ewm_mean = series.ewm(alpha=alpha, min_periods=3).mean()
    ewm_std = series.ewm(alpha=alpha, min_periods=3).std().replace(0, np.nan)
    return (series - ewm_mean) / ewm_std


def compute_statistical_anomaly_score(df: pd.DataFrame, group_cols: List[str] = ("shift_id", "station_id")) -> pd.DataFrame:
    """df must be sorted by window_end_time within each group already (or
    will be sorted here). Returns df with a `statistical_anomaly_score`
    column (max absolute combined z/EWMA score across SIGNAL_FEATURES)
    and a `statistical_signals` column (list of human-readable labels for
    features whose |z| or |ewma| exceeds Z_THRESHOLD)."""
    df = df.sort_values(list(group_cols) + ["window_end_time"]).copy()
    scores = pd.DataFrame(index=df.index)
    for feat in SIGNAL_FEATURES:
        if feat not in df.columns:
            continue
        z = df.groupby(list(group_cols))[feat].transform(lambda s: rolling_zscore(s).abs())
        e = df.groupby(list(group_cols))[feat].transform(lambda s: ewma_score(s).abs())
        scores[feat] = np.nanmax(np.vstack([z.fillna(0).to_numpy(), e.fillna(0).to_numpy()]), axis=0)

    if scores.empty:
        df["statistical_anomaly_score"] = 0.0
        df["statistical_signals"] = [[] for _ in range(len(df))]
        return df

    df["statistical_anomaly_score"] = scores.max(axis=1).clip(0, 10) / 10.0  # normalize to ~[0,1]
    df["statistical_signals"] = [
        [SIGNAL_FEATURES[f] for f in scores.columns if row[f] > Z_THRESHOLD]
        for _, row in scores.iterrows()
    ]
    return df
