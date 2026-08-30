"""
Flow v2 consequence-based labeling (Sections 3/4/6). The label question
changes from "will the first onset occur specifically 5-10 minutes from
now" to "will this station's buffer reach a genuine blocking-impact
consequence at ANY point in the next 10 minutes" -- the 5-10 minute band
becomes an EVALUATION metric (see backend/flow_v2/episode_evaluation.py),
not a training-label restriction.

Reuses backend.flow.bottleneck_events.detect_bottleneck_events UNCHANGED
-- only the labeling WINDOW changes, never how a bottleneck impact itself
is detected. Never reads scenario truth to build the label.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZON_SECONDS = 600.0
ALREADY_FULL_OCCUPANCY_THRESHOLD = 0.999


def label_rows_v2(grid: pd.DataFrame, impacts: pd.DataFrame, events_df: pd.DataFrame) -> pd.DataFrame:
    """grid: [shift_id, station_id, window_end_time]. impacts: output of
    detect_bottleneck_events (unchanged). events_df: raw shift events,
    used only to determine each shift's real end time (horizon-
    completeness check) -- never to read scenario truth.

    Returns grid with: label in {"POSITIVE","NEGATIVE","ACTIVE_EXCLUDED",
    "HORIZON_INCOMPLETE_EXCLUDED"}, target (1/0/NaN), impact_event_id
    (metadata only, POSITIVE rows only), time_to_impact_seconds (metadata
    only, POSITIVE rows only -- never a model feature)."""
    shift_end_time = events_df.groupby("shift_id").simulation_time.max()

    impacts_by_station = {
        key: g.sort_values("onset_time")[["impact_event_id", "onset_time", "end_time"]].reset_index(drop=True)
        for key, g in impacts.groupby(["shift_id", "impact_station_id"])
    }

    labels, targets, event_ids, times_to_impact = [], [], [], []
    for row in grid.itertuples():
        t = row.window_end_time
        key = (row.shift_id, row.station_id)
        ivals = impacts_by_station.get(key)
        end_of_shift = shift_end_time.get(row.shift_id, np.inf)

        active = False
        if ivals is not None:
            active = bool(((ivals.onset_time <= t) & (t <= ivals.end_time)).any())
        if active:
            labels.append("ACTIVE_EXCLUDED")
            targets.append(np.nan)
            event_ids.append(None)
            times_to_impact.append(np.nan)
            continue

        horizon_available = (end_of_shift - t) >= HORIZON_SECONDS
        if not horizon_available:
            labels.append("HORIZON_INCOMPLETE_EXCLUDED")
            targets.append(np.nan)
            event_ids.append(None)
            times_to_impact.append(np.nan)
            continue

        if ivals is not None:
            future = ivals[(ivals.onset_time > t) & (ivals.onset_time - t <= HORIZON_SECONDS)]
        else:
            future = ivals

        if future is not None and len(future):
            nearest = future.iloc[0]  # ivals sorted by onset_time -> first future row is nearest
            labels.append("POSITIVE")
            targets.append(1)
            event_ids.append(nearest.impact_event_id)
            times_to_impact.append(float(nearest.onset_time - t))
        else:
            labels.append("NEGATIVE")
            targets.append(0)
            event_ids.append(None)
            times_to_impact.append(np.nan)

    result = grid.copy()
    result["label"] = labels
    result["target"] = targets
    result["impact_event_id"] = event_ids
    result["time_to_impact_seconds"] = times_to_impact
    return result


def apply_already_full_exclusion(labeled: pd.DataFrame, occupancy_col: str = "inbound_occupancy_ratio") -> pd.DataFrame:
    """Second-pass exclusion (Section 4): a row whose relevant inbound
    buffer is already essentially at capacity at t is excluded even if the
    impact-event detector hasn't yet registered a formal BLOCKED
    transition for it (a timing-granularity edge case, not a new
    mechanism) -- applied AFTER features are merged in, since occupancy
    is a feature, not label-detector output. Uses only the observable
    occupancy feature, never scenario truth."""
    labeled = labeled.copy()
    already_full = (labeled[occupancy_col] >= ALREADY_FULL_OCCUPANCY_THRESHOLD) & labeled.label.isin(["POSITIVE", "NEGATIVE"])
    labeled.loc[already_full, "label"] = "ALREADY_FULL_EXCLUDED"
    labeled.loc[already_full, "target"] = np.nan
    labeled.loc[already_full, "impact_event_id"] = None
    labeled.loc[already_full, "time_to_impact_seconds"] = np.nan
    return labeled
