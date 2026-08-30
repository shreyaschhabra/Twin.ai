"""
Manager analytics aggregations (Section 45): reusable Python functions
over already-materialized data (events, Flow/Quality processed datasets,
model artifacts) -- no API, just dicts/DataFrames ready for JSON export.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def throughput_by_shift(events_df: pd.DataFrame) -> Dict[str, int]:
    completed = events_df[events_df.event_type == "VEHICLE_COMPLETED_LINE"]
    return completed.groupby("shift_id").size().to_dict()


def bottleneck_events_by_station(impacts_df: pd.DataFrame) -> Dict[str, int]:
    return impacts_df.impact_station_id.value_counts().to_dict()


def average_cycle_deviation_by_station(flow_rows: pd.DataFrame) -> Dict[str, float]:
    return flow_rows.groupby("station_id").cycle_time_dev_relative.mean().round(4).to_dict()


def warning_lead_time_stats(lead_times: list) -> Dict[str, float]:
    if not lead_times:
        return {"count": 0}
    arr = np.array(lead_times)
    return {"count": int(len(arr)), "mean": float(arr.mean()), "median": float(np.median(arr)),
            "min": float(arr.min()), "max": float(arr.max())}


def quality_risk_trend_by_stage(quality_rows: pd.DataFrame, risk_scores: np.ndarray) -> Dict[int, float]:
    df = quality_rows.copy()
    df["risk"] = risk_scores
    return df.groupby("production_stage").risk.mean().round(4).to_dict()


def final_qc_defect_trend_by_shift(qc_events: pd.DataFrame) -> Dict[str, float]:
    qc_events = qc_events.copy()
    qc_events["is_defect"] = (qc_events.qc_result == "DEFECT").astype(int)
    return qc_events.groupby("shift_id").is_defect.mean().round(4).to_dict()


def sensor_coverage_by_maturity(events_df: pd.DataFrame, config) -> Dict[str, float]:
    sr = events_df[events_df.event_type == "SENSOR_READING"]
    maturity = {sid: s.sensor_maturity.value for sid, s in config.stations.items()}
    sr = sr.copy()
    sr["maturity"] = sr.station_id.map(maturity)
    return (sr.groupby("maturity").apply(lambda g: (g.measurement_status == "available").mean(), include_groups=False)
            .round(4).to_dict())


def data_state_distribution(data_states: list) -> Dict[str, float]:
    s = pd.Series(data_states)
    return (s.value_counts(normalize=True).round(4)).to_dict()


def build_manager_analytics_summary(
    events_df: pd.DataFrame, impacts_df: pd.DataFrame, flow_rows: pd.DataFrame,
    quality_rows: pd.DataFrame, quality_risk_scores: np.ndarray, lead_times: list,
    config, data_states: list = None,
) -> Dict:
    return {
        "throughput_by_shift": throughput_by_shift(events_df),
        "bottleneck_events_by_station": bottleneck_events_by_station(impacts_df),
        "average_cycle_deviation_by_station": average_cycle_deviation_by_station(flow_rows),
        "warning_lead_time_stats": warning_lead_time_stats(lead_times),
        "quality_risk_trend_by_stage": quality_risk_trend_by_stage(quality_rows, quality_risk_scores),
        "final_qc_defect_trend_by_shift": final_qc_defect_trend_by_shift(
            events_df[events_df.event_type == "QC_RESULT_RECORDED"]
        ),
        "sensor_coverage_by_maturity": sensor_coverage_by_maturity(events_df, config),
        "data_state_distribution": data_state_distribution(data_states) if data_states else {},
    }
