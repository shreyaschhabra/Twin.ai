"""
Independent re-derivation check (Step 5 rigor pass), borrowed directly
from the reference project's causal_validation.py idea: rather than only
testing a synthetic future-mutation on one sample shift
(tests/test_flow_leakage.py), re-derive the bottleneck impact events
using a DIFFERENT algorithm and cross-check against
backend.flow.bottleneck_events.detect_bottleneck_events on the FULL
dataset. If the production detector's "onset/release strictly alternate"
assumption were ever violated, this would very likely diverge from it,
since this version never assumes alternation -- it walks the ordered
transition stream directly and tracks current BLOCKED state, rather than
extracting two separate onset/release lists and pairing them positionally.
"""

from __future__ import annotations

import pandas as pd

RECOVERY_GAP_SECONDS = 60.0


def detect_impact_intervals_independent(events_df: pd.DataFrame, config) -> pd.DataFrame:
    """Algorithmically independent of detect_bottleneck_events: a direct
    chronological state-machine walk per (shift, station) over the full
    ordered STATION_STATE_CHANGED stream, tracking "currently blocked
    since X" rather than pre-splitting into onset/release lists and
    zipping them by position. Same recovery-gap merge rule, re-implemented
    from scratch rather than shared code."""
    buf_downstream = {bid: b.downstream_station for bid, b in config.buffers.items()}

    state = events_df[events_df.event_type == "STATION_STATE_CHANGED"]
    state = state[["shift_id", "station_id", "simulation_time", "event_id", "from_state", "to_state", "buffer_id"]]
    state = state.sort_values(["shift_id", "station_id", "simulation_time", "event_id"])

    results = []
    for (shift_id, station_id), grp in state.groupby(["shift_id", "station_id"], sort=False):
        blocked_since = None
        blocked_buffer_id = None
        sub_episodes = []
        for row in grp.itertuples():
            if row.to_state == "BLOCKED":
                blocked_since = row.simulation_time
                blocked_buffer_id = row.buffer_id
            elif row.from_state == "BLOCKED" and blocked_since is not None:
                sub_episodes.append((blocked_since, row.simulation_time, blocked_buffer_id))
                blocked_since = None
                blocked_buffer_id = None
        if blocked_since is not None:
            # shift ended while still blocked -- zero-duration trailing episode
            sub_episodes.append((blocked_since, blocked_since, blocked_buffer_id))

        merged = []
        current = None
        for onset, release, buffer_id in sub_episodes:
            if current is not None and current["buffer_id"] == buffer_id and onset - current["end_time"] <= RECOVERY_GAP_SECONDS:
                current["end_time"] = max(current["end_time"], release)
            else:
                if current is not None:
                    merged.append(current)
                current = {"onset_time": onset, "end_time": release, "buffer_id": buffer_id}
        if current is not None:
            merged.append(current)

        for i, m in enumerate(merged):
            results.append({
                "impact_event_id": f"{shift_id}::{station_id}::{i + 1}",
                "shift_id": shift_id,
                "blocked_station_id": station_id,
                "impact_station_id": buf_downstream.get(m["buffer_id"]),
                "buffer_id": m["buffer_id"],
                "onset_time": m["onset_time"],
                "end_time": m["end_time"],
            })

    if not results:
        return pd.DataFrame(columns=[
            "impact_event_id", "shift_id", "blocked_station_id", "impact_station_id",
            "buffer_id", "onset_time", "end_time",
        ])
    return pd.DataFrame(results)


def label_rows_independent(grid: pd.DataFrame, intervals: pd.DataFrame,
                            imminent_threshold_seconds: float = 300.0,
                            horizon_seconds: float = 600.0) -> pd.DataFrame:
    """Independent re-derivation of label_rows()'s ACTIVE/IMMINENT/
    POSITIVE/NEGATIVE assignment, using direct per-(shift,station) interval
    scans instead of labels.py's merge_asof-based approach. Deliberately
    simple/slow (there are only ~1-2 thousand impact events total, so a
    direct scan is tractable) -- correctness by inspection matters more
    than speed here."""
    out_labels = []
    out_lead = []

    grouped_intervals = {
        key: sorted(zip(g.onset_time, g.end_time))
        for key, g in intervals.groupby(["shift_id", "impact_station_id"])
    }

    for row in grid.itertuples():
        key = (row.shift_id, row.station_id)
        ivals = grouped_intervals.get(key, [])
        t = row.window_end_time

        active = any(onset <= t <= end for onset, end in ivals)
        if active:
            out_labels.append("ACTIVE")
            out_lead.append(float("nan"))
            continue

        future_onsets = [onset for onset, _ in ivals if onset > t]
        if not future_onsets:
            out_labels.append("NEGATIVE")
            out_lead.append(float("nan"))
            continue

        next_onset = min(future_onsets)
        lead = next_onset - t
        if lead < imminent_threshold_seconds:
            out_labels.append("IMMINENT")
            out_lead.append(float("nan"))
        elif lead <= horizon_seconds:
            out_labels.append("POSITIVE")
            out_lead.append(lead)
        else:
            out_labels.append("NEGATIVE")
            out_lead.append(float("nan"))

    result = grid.copy()
    result["label"] = out_labels
    result["lead_time_s"] = out_lead
    return result
