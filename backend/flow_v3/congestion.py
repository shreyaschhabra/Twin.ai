"""Congestion regimes (Section 16): group raw BLOCKED transitions into one
row per sustained causal congestion condition, plus the raw sub-episodes
that were merged into it.

Reuses the already-tested merge rule from `backend.flow.bottleneck_events`
(same-buffer BLOCKED sub-episodes within RECOVERY_GAP_SECONDS of each other
are one regime; a longer gap means genuine recovery) rather than
reimplementing it, so a `congestion_regime_id` here IS exactly an
`impact_event_id` there. `blocking_subepisode_id` exposes the raw onset/
release pairs that were merged, for cases that want sub-episode detail.
"""

from __future__ import annotations

import pandas as pd

from backend.flow.bottleneck_events import RECOVERY_GAP_SECONDS, detect_bottleneck_events


def detect_congestion_regimes(events_df: pd.DataFrame, config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (regimes, subepisodes).

    regimes: one row per congestion_regime_id (== impact_event_id), columns
        match `detect_bottleneck_events` plus a renamed id column.
    subepisodes: one row per raw onset/release pair, with a
        blocking_subepisode_id and its parent congestion_regime_id.
    """
    regimes = detect_bottleneck_events(events_df, config)
    regimes = regimes.rename(columns={"impact_event_id": "congestion_regime_id"})

    state = events_df[events_df.event_type == "STATION_STATE_CHANGED"]
    blocked_on = state[state.to_state == "BLOCKED"].sort_values("simulation_time")
    blocked_off = state[state.from_state == "BLOCKED"].sort_values("simulation_time")

    sub_rows = []
    for run_id in blocked_on.shift_id.unique():
        on_run = blocked_on[blocked_on.shift_id == run_id]
        off_run = blocked_off[blocked_off.shift_id == run_id]
        run_regimes = regimes[regimes.shift_id == run_id]

        for station_id in on_run.station_id.unique():
            on_rows = on_run[on_run.station_id == station_id].sort_values("simulation_time")
            off_rows = off_run[off_run.station_id == station_id].sort_values("simulation_time")
            onsets = list(zip(on_rows.simulation_time, on_rows.buffer_id))
            releases = list(off_rows.simulation_time)
            station_regimes = run_regimes[run_regimes.blocked_station_id == station_id].sort_values("onset_time")

            for index, (onset, buffer_id) in enumerate(onsets):
                release = releases[index] if index < len(releases) else onset
                parent = station_regimes[
                    (station_regimes.onset_time <= onset + 1e-6) & (station_regimes.end_time >= release - 1e-6)
                ]
                parent_id = parent.congestion_regime_id.iloc[0] if len(parent) else None
                sub_rows.append({
                    "blocking_subepisode_id": f"{run_id}::{station_id}::sub{index + 1}",
                    "congestion_regime_id": parent_id,
                    "shift_id": run_id,
                    "blocked_station_id": station_id,
                    "buffer_id": buffer_id,
                    "onset_time": onset,
                    "release_time": release,
                    "duration_seconds": release - onset,
                })

    columns = [
        "blocking_subepisode_id", "congestion_regime_id", "shift_id", "blocked_station_id",
        "buffer_id", "onset_time", "release_time", "duration_seconds",
    ]
    subepisodes = pd.DataFrame(sub_rows, columns=columns) if sub_rows else pd.DataFrame(columns=columns)
    return regimes, subepisodes


__all__ = ["detect_congestion_regimes", "RECOVERY_GAP_SECONDS"]
