"""
Episode-level evaluation (Section 25): the actual bottleneck episode
(impact_event_id) -- not the row -- is the primary operational unit.
For each real episode: did at least one alert fire before onset, what was
the first-warning lead time, and separately, did a warning fall in the
0-5 minute band vs. the 5-10 minute band. This replaces forcing the
training target itself into a narrow 5-10 minute window (flow_v1) with a
richer, more honest post-hoc breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd


@dataclass
class EpisodeEvalResult:
    total_episodes: int
    any_warning_detected: int
    any_warning_recall: float
    band_5_10_min_detected: int
    band_5_10_min_recall: float
    band_0_5_min_detected: int
    band_0_5_min_recall: float
    missed_episodes: int
    false_warnings: int
    false_warnings_per_shift: float
    first_warning_lead_times: List[float] = field(default_factory=list)
    warnings_per_episode: dict = field(default_factory=dict)


def evaluate_episodes(rows: pd.DataFrame, predictions: np.ndarray, impacts: pd.DataFrame) -> EpisodeEvalResult:
    """rows: labeled+featured rows for one partition (must include
    shift_id, station_id, impact_event_id, time_to_impact_seconds,
    label==POSITIVE/NEGATIVE only). predictions: aligned 0/1 array.
    impacts: bottleneck_events rows already scoped to this partition's
    own shifts."""
    rows = rows.reset_index(drop=True).copy()
    rows["predicted"] = predictions

    fired = rows[rows.predicted == 1]
    any_detected, band_5_10_detected, band_0_5_detected = 0, 0, 0
    lead_times = []
    warnings_per_episode = {}

    for ev in impacts.itertuples():
        matches = fired[fired.impact_event_id == ev.impact_event_id]
        n_warn = len(matches)
        warnings_per_episode[ev.impact_event_id] = n_warn
        if n_warn == 0:
            continue
        any_detected += 1
        lead = matches.time_to_impact_seconds
        lead_times.append(float(lead.max()))  # earliest fired alert = largest time-to-impact
        if ((lead >= 300) & (lead <= 600)).any():
            band_5_10_detected += 1
        if ((lead > 0) & (lead < 300)).any():
            band_0_5_detected += 1

    total = len(impacts)
    missed = total - any_detected

    real_event_ids = set(impacts.impact_event_id)
    false_warnings = int((fired.impact_event_id.isna() | ~fired.impact_event_id.isin(real_event_ids)).sum())
    n_shifts = rows.shift_id.nunique()

    return EpisodeEvalResult(
        total_episodes=total,
        any_warning_detected=any_detected,
        any_warning_recall=(any_detected / total) if total else float("nan"),
        band_5_10_min_detected=band_5_10_detected,
        band_5_10_min_recall=(band_5_10_detected / total) if total else float("nan"),
        band_0_5_min_detected=band_0_5_detected,
        band_0_5_min_recall=(band_0_5_detected / total) if total else float("nan"),
        missed_episodes=missed,
        false_warnings=false_warnings,
        false_warnings_per_shift=(false_warnings / n_shifts) if n_shifts else float("nan"),
        first_warning_lead_times=lead_times,
        warnings_per_episode=warnings_per_episode,
    )
