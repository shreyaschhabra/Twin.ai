"""
Flow evaluation (Step 5 Sections W-Y, continuation 18-19). Row-level,
event-level, and lead-time metrics — no alert-threshold finalization
(Step 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class RowMetrics:
    precision: float
    recall: float
    f1: float
    pr_auc: float
    roc_auc: float
    prevalence: float
    confusion: np.ndarray


def row_level_metrics(y_true: np.ndarray, y_score: np.ndarray, threshold: float = 0.5) -> RowMetrics:
    y_pred = (y_score >= threshold).astype(int)
    return RowMetrics(
        precision=precision_score(y_true, y_pred, zero_division=0),
        recall=recall_score(y_true, y_pred, zero_division=0),
        f1=f1_score(y_true, y_pred, zero_division=0),
        pr_auc=average_precision_score(y_true, y_score) if len(set(y_true)) > 1 else float("nan"),
        roc_auc=roc_auc_score(y_true, y_score) if len(set(y_true)) > 1 else float("nan"),
        prevalence=y_true.mean(),
        confusion=confusion_matrix(y_true, y_pred),
    )


@dataclass
class EventLevelResult:
    total_events: int
    detected_events: int
    event_recall: float
    missed_events: int
    warnings_per_event: Dict[str, int]
    false_warnings_not_associated_with_event: int
    false_warnings_per_shift: float
    lead_times: list


def event_level_evaluation(
    rows: pd.DataFrame,
    predictions: np.ndarray,
    impacts: pd.DataFrame,
) -> EventLevelResult:
    """rows must include shift_id, station_id, window_end_time,
    target_onset_time, label (only POSITIVE/NEGATIVE rows should be
    passed in — imminent/active/holdout already excluded upstream).
    An impact event counts as "detected" if at least one row whose
    target_onset_time matches that event's onset predicted positive."""
    rows = rows.copy()
    rows["predicted"] = predictions

    warned_onsets = set(
        zip(rows.loc[rows.predicted == 1, "shift_id"], rows.loc[rows.predicted == 1, "station_id"],
            rows.loc[rows.predicted == 1, "target_onset_time"])
    )

    detected = 0
    lead_times = []
    warnings_per_event = {}
    for _, ev in impacts.iterrows():
        key_matches = rows[
            (rows.shift_id == ev.shift_id) & (rows.station_id == ev.impact_station_id)
            & (rows.target_onset_time == ev.onset_time) & (rows.predicted == 1)
        ]
        n_warn = len(key_matches)
        warnings_per_event[ev.impact_event_id] = n_warn
        if n_warn > 0:
            detected += 1
            first_warning_time = key_matches.window_end_time.min()
            lead_times.append(ev.onset_time - first_warning_time)

    total_events = len(impacts)
    missed = total_events - detected

    # false warnings: positive predictions whose target_onset_time does not
    # correspond to ANY real impact event onset (shouldn't happen given
    # target construction, but check directly rather than assume)
    real_onsets = set(zip(impacts.shift_id, impacts.impact_station_id, impacts.onset_time))
    predicted_positive = rows[rows.predicted == 1]
    false_warnings = sum(
        1 for _, r in predicted_positive.iterrows()
        if (r.shift_id, r.station_id, r.target_onset_time) not in real_onsets
    )
    n_shifts = rows.shift_id.nunique()

    return EventLevelResult(
        total_events=total_events,
        detected_events=detected,
        event_recall=detected / total_events if total_events else float("nan"),
        missed_events=missed,
        warnings_per_event=warnings_per_event,
        false_warnings_not_associated_with_event=false_warnings,
        false_warnings_per_shift=false_warnings / n_shifts if n_shifts else float("nan"),
        lead_times=lead_times,
    )


def lead_time_summary(lead_times: list) -> dict:
    if not lead_times:
        return {"count": 0}
    arr = np.array(lead_times)
    return {
        "count": len(arr),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "fraction_in_5_10min_band": float(((arr >= 300) & (arr <= 600)).mean()),
    }
