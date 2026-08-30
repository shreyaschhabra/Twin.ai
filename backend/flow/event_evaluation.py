"""
Corrected event-level evaluation (Section 9 of the ML/intelligence build).

The previous evaluator (backend/flow/evaluation.py::event_level_evaluation)
had a semantics gap: it treated every impact event in a partition as
"detectable," even ones with zero valid 5-10-minute-before POSITIVE row
(e.g. an event whose onset falls too early in the shift for a full
300-600s lookback window to exist inside the simulated shift). This
module adds the concept of an ELIGIBLE event -- one that has at least one
valid station-minute POSITIVE row 5-10 minutes before its onset -- and
uses only eligible events as the recall denominator, exactly as directed:

  "An impact event is early-warning eligible only if at least one valid
   station-minute POSITIVE row exists 5-10 minutes before its onset."

All valid lead times are structurally bounded to [300, 600] seconds by
construction (backend/flow/labels.py never assigns a POSITIVE label
outside that window), so this module does not need to separately filter
out 20-30-minute-early alerts -- there is no code path that could produce
one. This module's actual fix is: (1) the eligible-vs-total distinction,
(2) exact impact_event_id-based row-to-event mapping instead of loose
(shift, station, onset_time) matching, (3) same-station enforcement made
explicit rather than implicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

LOOKBACK_LOW_SECONDS = 300.0
LOOKBACK_HIGH_SECONDS = 600.0


@dataclass
class EligibleEventResult:
    total_impact_events: int
    eligible_events: int
    detected_eligible_events: int
    event_recall: float
    missed_events: int
    false_warnings: int
    false_warnings_per_shift: float
    first_valid_lead_times: List[float] = field(default_factory=list)


def evaluate_events(
    rows: pd.DataFrame,
    predictions: np.ndarray,
    impacts: pd.DataFrame,
) -> EligibleEventResult:
    """rows: the labeled+featured station-minute rows for one partition
    (must include shift_id, station_id, window_end_time, target_onset_time,
    label -- only POSITIVE/NEGATIVE rows, as produced by the standard Flow
    pipeline). predictions: aligned 0/1 array. impacts: bottleneck_events
    rows already filtered to this partition's own shifts (the caller is
    responsible for that partition scoping -- see
    scripts/build_flow_pipeline.py's val_impacts/test_impacts pattern)."""
    rows = rows.reset_index(drop=True).copy()
    rows["predicted"] = predictions

    total_impact_events = len(impacts)
    eligible = 0
    detected = 0
    lead_times: List[float] = []
    warned_row_keys = set()

    for ev in impacts.itertuples():
        # exact match: same shift, same station (the actual impact_station_id
        # this event is attributed to -- never a different station), and a
        # row whose lead time to THIS event's onset falls in [300,600]s.
        candidates = rows[
            (rows.shift_id == ev.shift_id)
            & (rows.station_id == ev.impact_station_id)
            & (rows.label == "POSITIVE")
            & (rows.target_onset_time == ev.onset_time)
        ]
        if len(candidates) == 0:
            continue  # not eligible -- no valid 5-10-min-before row exists for this event
        eligible += 1

        # sanity: every candidate's lead time must already be in [300,600]
        lead = ev.onset_time - candidates.window_end_time
        assert ((lead >= LOOKBACK_LOW_SECONDS - 1e-6) & (lead <= LOOKBACK_HIGH_SECONDS + 1e-6)).all(), (
            f"eligible row(s) for event {ev.impact_event_id} fell outside [300,600]s -- labeling bug"
        )

        fired = candidates[candidates.predicted == 1]
        if len(fired) > 0:
            detected += 1
            first_warning_time = fired.window_end_time.max()  # latest = closest to onset = first *valid* warning within the window
            first_valid_lead = ev.onset_time - first_warning_time
            lead_times.append(float(first_valid_lead))
            for _, r in fired.iterrows():
                warned_row_keys.add((r.shift_id, r.station_id, r.target_onset_time))

    missed = eligible - detected

    # false warnings: predicted-positive rows whose (shift, station,
    # target_onset_time) doesn't correspond to any real impact event's
    # onset at all (should not happen given label construction, checked
    # directly rather than assumed).
    real_onsets = set(zip(impacts.shift_id, impacts.impact_station_id, impacts.onset_time))
    predicted_positive = rows[rows.predicted == 1]
    false_warnings = sum(
        1 for r in predicted_positive.itertuples()
        if (r.shift_id, r.station_id, r.target_onset_time) not in real_onsets
    )
    n_shifts = rows.shift_id.nunique()

    return EligibleEventResult(
        total_impact_events=total_impact_events,
        eligible_events=eligible,
        detected_eligible_events=detected,
        event_recall=(detected / eligible) if eligible else float("nan"),
        missed_events=missed,
        false_warnings=false_warnings,
        false_warnings_per_shift=(false_warnings / n_shifts) if n_shifts else float("nan"),
        first_valid_lead_times=lead_times,
    )


def lead_time_report(lead_times: List[float]) -> dict:
    if not lead_times:
        return {"count": 0}
    arr = np.array(lead_times)
    assert ((arr >= LOOKBACK_LOW_SECONDS - 1e-6) & (arr <= LOOKBACK_HIGH_SECONDS + 1e-6)).all(), (
        "a reported lead time fell outside [300,600]s"
    )
    return {
        "count": int(len(arr)),
        "first_valid_lead_time_s": float(arr[0]),
        "median_valid_lead_time_s": float(np.median(arr)),
        "min_lead_time_s": float(arr.min()),
        "max_lead_time_s": float(arr.max()),
        "mean_lead_time_s": float(arr.mean()),
    }
