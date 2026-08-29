"""
EQUIPMENT_DEGRADATION unseen-scenario holdout (Step 5, Section J / locked
Decision 35). Uses latent scenario truth ONLY to build a row-level
exclusion mask — never as a model feature, never to change the label.

A row (shift_id, station_id, window_end_time=t) is excluded if its
feature-history window [t-300, t] OR its target horizon [t, t+600]
overlaps any EQUIPMENT_DEGRADATION scenario interval at that station,
i.e. if [t-300, t+600] overlaps [start_time, end_time + RECOVERY_GUARD].

RECOVERY GUARD: degradation's cycle-time/sensor effects switch off
mechanically the instant the scenario's own window ends (ScenarioManager
returns no effect once `is_active_at` is false — there is no modeled
gradual decay). However a queue/buffer backlog built up during the
degradation can plausibly take real time to drain afterward, which would
still be an observable trace of the held-out scenario. RECOVERY_GUARD_SECONDS
= 300s (matching the 5-minute feature lookback already used everywhere
else in this pipeline) is used as a conservative default protecting
against that lingering-backlog case; see ASSUMPTIONS.md / the Step 5
report for the empirical check of how long affected-station buffer
occupancy actually took to normalize after real degradation scenarios in
the generated dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

import pandas as pd

RECOVERY_GUARD_SECONDS = 300.0
FEATURE_LOOKBACK_SECONDS = 300.0
TARGET_HORIZON_SECONDS = 600.0

ROBUSTNESS_LABEL = "UNSEEN_EQUIPMENT_DEGRADATION_ROBUSTNESS"


@dataclass(frozen=True)
class DegradationInterval:
    shift_id: str
    station_id: str
    start_time: float
    guarded_end_time: float


def extract_degradation_intervals(scenario_truth: pd.DataFrame) -> List[DegradationInterval]:
    degradation = scenario_truth[scenario_truth.family == "EQUIPMENT_DEGRADATION"]
    intervals = []
    for _, row in degradation.iterrows():
        station_ids = json.loads(row.station_ids) if isinstance(row.station_ids, str) else row.station_ids
        end = row.end_time if pd.notna(row.end_time) else float("inf")
        guarded_end = end + RECOVERY_GUARD_SECONDS if end != float("inf") else end
        for station_id in station_ids:
            intervals.append(DegradationInterval(
                shift_id=row.shift_id, station_id=station_id,
                start_time=row.start_time, guarded_end_time=guarded_end,
            ))
    return intervals


def compute_holdout_mask(rows: pd.DataFrame, scenario_truth: pd.DataFrame) -> pd.Series:
    """rows: any DataFrame with [shift_id, station_id, window_end_time].
    Returns a boolean Series, True = must be excluded from supervised
    train/validation/test and placed in the robustness partition."""
    intervals = extract_degradation_intervals(scenario_truth)
    mask = pd.Series(False, index=rows.index)
    if not intervals:
        return mask

    by_key: dict = {}
    for iv in intervals:
        by_key.setdefault((iv.shift_id, iv.station_id), []).append(iv)

    for (shift_id, station_id), group_intervals in by_key.items():
        sel = (rows.shift_id == shift_id) & (rows.station_id == station_id)
        if not sel.any():
            continue
        t = rows.loc[sel, "window_end_time"]
        window_lo = t - FEATURE_LOOKBACK_SECONDS
        window_hi = t + TARGET_HORIZON_SECONDS
        row_mask = pd.Series(False, index=t.index)
        for iv in group_intervals:
            overlap = (window_lo <= iv.guarded_end_time) & (window_hi >= iv.start_time)
            row_mask = row_mask | overlap
        mask.loc[sel] = row_mask.values

    return mask


def split_holdout(labeled: pd.DataFrame, scenario_truth: pd.DataFrame) -> dict:
    mask = compute_holdout_mask(labeled, scenario_truth)
    return {
        "supervised": labeled.loc[~mask].copy(),
        "unseen_equipment_degradation": labeled.loc[mask].copy(),
    }
