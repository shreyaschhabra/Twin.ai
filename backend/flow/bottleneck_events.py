"""
Flow bottleneck-impact event detection (Step 5, Section D/F).

DEFINITION: a bottleneck impact is associated with the DOWNSTREAM station
consuming a buffer that caused an UPSTREAM station to enter BLOCKED.
Given `upstream_station -> buffer -> downstream_station`, when
upstream_station is BLOCKED because that buffer is full, the impact is
attributed to downstream_station — its inadequate effective service rate
is what created the constraint, not the station merely showing BLOCKED.

Uses only observable STATION_STATE_CHANGED events (Step 4 patch 1 added
vehicle_id/buffer_id/occupancy specifically to the BLOCKED transition so
this never needs scenario truth or reconstruction).

GROUPING / RECOVERY RULE: a station's state machine is single-threaded
per station, so its BLOCKED-onset and BLOCKED-release events strictly
alternate (verified by test, not just assumed). Consecutive
(onset, release) sub-episodes on the SAME (blocked_station, buffer) pair
are merged into one impact_event_id if the gap between one sub-episode's
release and the next sub-episode's onset is <= RECOVERY_GAP_SECONDS —
i.e. re-blocking within one Flow window (60s) of resolving is treated as
continuing congestion, not a fresh event. A longer gap means it genuinely
cleared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

RECOVERY_GAP_SECONDS = 60.0


@dataclass
class BottleneckImpactEvent:
    impact_event_id: str
    shift_id: str
    impact_station_id: str
    blocked_station_id: str
    buffer_id: str
    onset_time: float
    end_time: float
    n_sub_episodes: int
    total_blocked_seconds: float

    @property
    def duration(self) -> float:
        return self.end_time - self.onset_time


def detect_bottleneck_events(events_df: pd.DataFrame, config) -> pd.DataFrame:
    """events_df must contain at least: shift_id, event_type, station_id,
    buffer_id, from_state, to_state, simulation_time. Returns a DataFrame
    with one row per detected impact event (columns match
    BottleneckImpactEvent's fields)."""
    buf_downstream = {bid: b.downstream_station for bid, b in config.buffers.items()}

    state = events_df[events_df.event_type == "STATION_STATE_CHANGED"]
    blocked_on = state[state.to_state == "BLOCKED"].sort_values("simulation_time")
    blocked_off = state[state.from_state == "BLOCKED"].sort_values("simulation_time")

    events: List[BottleneckImpactEvent] = []

    for shift_id in blocked_on.shift_id.unique():
        on_shift = blocked_on[blocked_on.shift_id == shift_id]
        off_shift = blocked_off[blocked_off.shift_id == shift_id]

        for station_id in on_shift.station_id.unique():
            on_rows = on_shift[on_shift.station_id == station_id].sort_values("simulation_time")
            off_rows = off_shift[off_shift.station_id == station_id].sort_values("simulation_time")

            onsets = list(zip(on_rows.simulation_time, on_rows.buffer_id))
            releases = list(off_rows.simulation_time)

            # onset/release strictly alternate for a single station's state
            # machine; a trailing unresolved BLOCKED (shift ended while
            # blocked) has no matching release — treat its release as its
            # own onset (zero-duration sub-episode) rather than crashing.
            sub_episodes = []
            for i, (onset, buffer_id) in enumerate(onsets):
                release = releases[i] if i < len(releases) else onset
                sub_episodes.append((onset, release, buffer_id))

            grouped = []
            current = None
            for onset, release, buffer_id in sub_episodes:
                if (
                    current is not None
                    and current["buffer_id"] == buffer_id
                    and onset - current["end_time"] <= RECOVERY_GAP_SECONDS
                ):
                    current["end_time"] = max(current["end_time"], release)
                    current["n_sub"] += 1
                    current["total_blocked"] += release - onset
                else:
                    if current is not None:
                        grouped.append(current)
                    current = {
                        "onset": onset, "end_time": release, "buffer_id": buffer_id,
                        "n_sub": 1, "total_blocked": release - onset,
                    }
            if current is not None:
                grouped.append(current)

            for i, g in enumerate(grouped):
                events.append(BottleneckImpactEvent(
                    impact_event_id=f"{shift_id}::{station_id}::{i + 1}",
                    shift_id=shift_id,
                    impact_station_id=buf_downstream.get(g["buffer_id"]),
                    blocked_station_id=station_id,
                    buffer_id=g["buffer_id"],
                    onset_time=g["onset"],
                    end_time=g["end_time"],
                    n_sub_episodes=g["n_sub"],
                    total_blocked_seconds=g["total_blocked"],
                ))

    if not events:
        return pd.DataFrame(columns=[
            "impact_event_id", "shift_id", "impact_station_id", "blocked_station_id",
            "buffer_id", "onset_time", "end_time", "n_sub_episodes", "total_blocked_seconds",
        ])
    return pd.DataFrame([e.__dict__ for e in events])
