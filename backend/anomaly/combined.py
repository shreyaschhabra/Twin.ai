"""Unified anomaly output (Section 26): combines the statistical and
Isolation Forest scores into one canonical object. Anomaly != defect --
this layer never claims a quality or Flow outcome, only "this looks
operationally unusual"."""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

HIGH_THRESHOLD = 0.70
MEDIUM_THRESHOLD = 0.40


def anomaly_level(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def build_anomaly_output(station_id: str, statistical_score: float, iforest_score: float, signals: List[str]) -> dict:
    combined = float(0.5 * statistical_score + 0.5 * iforest_score)
    return {
        "station_id": station_id,
        "anomaly_score": round(combined, 4),
        "anomaly_level": anomaly_level(combined),
        "signals": signals,
    }


def combine_scores_frame(df: pd.DataFrame, statistical_col: str = "statistical_anomaly_score",
                          iforest_col: str = "iforest_anomaly_score") -> pd.DataFrame:
    df = df.copy()
    df["anomaly_score"] = (0.5 * df[statistical_col] + 0.5 * df[iforest_col]).round(4)
    df["anomaly_level"] = df.anomaly_score.apply(anomaly_level)
    return df
