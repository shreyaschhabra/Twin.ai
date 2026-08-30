"""Observable micro-stop rolling summaries for later precursor design."""

from __future__ import annotations

from backend.simulation.events import EventType


def micro_stop_rolling_quantities(events, station_id: str, observation_time: float, window_seconds: float = 300.0) -> dict:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    current_start = observation_time - window_seconds
    previous_start = observation_time - 2.0 * window_seconds
    current = [
        event for event in events
        if event.event_type == EventType.MICRO_STOP_OCCURRED.value
        and event.station_id == station_id
        and current_start < event.simulation_time <= observation_time
    ]
    previous = [
        event for event in events
        if event.event_type == EventType.MICRO_STOP_OCCURRED.value
        and event.station_id == station_id
        and previous_start < event.simulation_time <= current_start
    ]
    count = len(current)
    seconds = sum(float(event.value or 0.0) for event in current)
    minutes = window_seconds / 60.0
    rate = count / minutes
    previous_rate = len(previous) / minutes
    return {
        "micro_stop_count_recent": count,
        "micro_stop_seconds_recent": seconds,
        "mean_micro_stop_duration": seconds / count if count else 0.0,
        "micro_stop_rate": rate,
        "micro_stop_rate_trend": rate - previous_rate,
    }
