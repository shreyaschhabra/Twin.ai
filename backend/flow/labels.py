"""
Flow target construction (Step 5, Sections G/H).

For a station-minute row (shift_id, station_id, window_end_time=t):
  - ACTIVE: t falls inside [onset_time, end_time] of some impact event for
    this (shift, station) -> excluded from primary training.
  - Otherwise, let lead = (next future onset_time > t) - t.
      lead < 300s            -> IMMINENT/TOO_LATE, excluded from primary
                                 training but retained for audit.
      300s <= lead <= 600s   -> POSITIVE (1).
      lead > 600s or no
        future onset at all  -> NEGATIVE (0).

Uses ONLY the bottleneck-impact-event table (itself built from observable
BLOCKED events — see bottleneck_events.py). Never touches scenario truth.
Implemented via merge_asof (forward/backward) rather than per-row Python
loops for speed and to make the "point-in-time" semantics mechanically
obvious: a forward asof-join can only see rows at or after the join key,
never before — that's the property leakage tests in this project check.
"""

from __future__ import annotations

import pandas as pd

IMMINENT_THRESHOLD_SECONDS = 300.0
HORIZON_SECONDS = 600.0

LABEL_ACTIVE = "ACTIVE"
LABEL_IMMINENT = "IMMINENT"
LABEL_POSITIVE = "POSITIVE"
LABEL_NEGATIVE = "NEGATIVE"


def label_rows(grid: pd.DataFrame, impacts: pd.DataFrame) -> pd.DataFrame:
    """grid: columns [shift_id, station_id, window_end_time] (one row per
    station-minute). impacts: output of detect_bottleneck_events().
    Returns grid with added columns: label (one of the LABEL_* constants),
    target (1/0/NaN — NaN for excluded ACTIVE/IMMINENT rows), lead_time_s
    (NaN if no future event), target_onset_time (for audit only, never a
    feature)."""
    grid = grid.sort_values(["shift_id", "station_id", "window_end_time"]).reset_index(drop=True)

    if impacts.empty:
        out = grid.copy()
        out["label"] = LABEL_NEGATIVE
        out["target"] = 0
        out["lead_time_s"] = float("nan")
        out["target_onset_time"] = float("nan")
        return out

    results = []
    for (shift_id, station_id), rows in grid.groupby(["shift_id", "station_id"], sort=False):
        station_impacts = impacts[
            (impacts.shift_id == shift_id) & (impacts.impact_station_id == station_id)
        ].sort_values("onset_time")

        rows = rows.sort_values("window_end_time").copy()
        if station_impacts.empty:
            rows["label"] = LABEL_NEGATIVE
            rows["target"] = 0
            rows["lead_time_s"] = float("nan")
            rows["target_onset_time"] = float("nan")
            results.append(rows)
            continue

        # ACTIVE: most recent onset <= t whose end_time >= t
        active_join = pd.merge_asof(
            rows[["window_end_time"]], station_impacts[["onset_time", "end_time"]],
            left_on="window_end_time", right_on="onset_time", direction="backward",
        )
        is_active = (active_join.end_time >= rows.window_end_time.values) & active_join.onset_time.notna()

        # next future onset strictly after t
        future_join = pd.merge_asof(
            rows[["window_end_time"]], station_impacts[["onset_time"]],
            left_on="window_end_time", right_on="onset_time",
            direction="forward", allow_exact_matches=False,
        )
        lead = future_join.onset_time.values - rows.window_end_time.values

        label = pd.Series(LABEL_NEGATIVE, index=rows.index)
        target = pd.Series(0, index=rows.index)

        has_future = ~pd.isna(lead)
        imminent_mask = has_future & (lead < IMMINENT_THRESHOLD_SECONDS)
        positive_mask = has_future & (lead >= IMMINENT_THRESHOLD_SECONDS) & (lead <= HORIZON_SECONDS)

        label[imminent_mask] = LABEL_IMMINENT
        target[imminent_mask] = float("nan")
        label[positive_mask] = LABEL_POSITIVE
        target[positive_mask] = 1

        # ACTIVE takes precedence over imminent/positive/negative
        label[is_active.values] = LABEL_ACTIVE
        target[is_active.values] = float("nan")

        rows["label"] = label.values
        rows["target"] = target.values
        rows["lead_time_s"] = lead
        rows["target_onset_time"] = future_join.onset_time.values
        results.append(rows)

    return pd.concat(results, ignore_index=True)
