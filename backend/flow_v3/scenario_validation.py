"""Observable, physics-only metrics for pre-pilot targeted validation."""

from __future__ import annotations

import statistics
from collections import defaultdict

from backend.config.schemas import FactoryConfig
from backend.simulation.events import EventType


def _relevant_buffer_ids(config: FactoryConfig, target_station_id: str | None) -> set[str]:
    if target_station_id is None:
        return set(config.buffers)
    return {
        buffer_id
        for buffer_id, buffer in config.buffers.items()
        if buffer.downstream_station == target_station_id
    }


def measure_scenario_run(
    result,
    config: FactoryConfig,
    *,
    mechanism: str,
    target_station_id: str | None,
    severity: str,
    profile: str,
    seed: int,
    scenario_start: float,
    scenario_end: float,
    congestion_observation_end: float | None = None,
) -> dict:
    """Measure actual congestion without using latent scenario identifiers.

    A positive run requires an observable BLOCKED transition during the
    declared disturbance window.  This deliberately refuses to infer a
    positive from a full/small buffer alone.
    """
    relevant_buffers = _relevant_buffer_ids(config, target_station_id)
    observation_end = congestion_observation_end or scenario_end
    events = result.events
    blocking_starts = [
        event for event in events
        if event.event_type == EventType.STATION_STATE_CHANGED.value
        and event.to_state == "BLOCKED"
        and event.buffer_id in relevant_buffers
        and scenario_start <= event.simulation_time <= observation_end
    ]

    changes_by_station: dict[str, list] = defaultdict(list)
    for event in events:
        if event.event_type == EventType.STATION_STATE_CHANGED.value:
            changes_by_station[event.station_id].append(event)

    blocked_seconds = 0.0
    all_released = True
    for start in blocking_starts:
        release = next(
            (event for event in changes_by_station[start.station_id]
             if event.simulation_time > start.simulation_time and event.from_state == "BLOCKED"),
            None,
        )
        if release is None:
            all_released = False
            blocked_seconds += result.summary["simulated_duration_seconds"] - start.simulation_time
        else:
            blocked_seconds += release.simulation_time - start.simulation_time

    occupancy_events = [
        event for event in events
        if event.buffer_id in relevant_buffers
        and event.event_type in {
            EventType.VEHICLE_ENTERED_BUFFER.value,
            EventType.VEHICLE_LEFT_BUFFER.value,
        }
        and event.occupancy is not None
    ]
    active_occupancy = [
        event.occupancy / config.buffers[event.buffer_id].capacity
        for event in occupancy_events
        if scenario_start <= event.simulation_time <= observation_end
    ]
    max_occupancy = max(active_occupancy, default=0.0)

    first = min((event.simulation_time for event in blocking_starts), default=None)
    first_block = min(blocking_starts, key=lambda event: event.simulation_time, default=None)
    first_impacted_station = (
        config.buffers[first_block.buffer_id].downstream_station
        if first_block is not None else None
    )
    impacted_stations = sorted({
        config.buffers[event.buffer_id].downstream_station for event in blocking_starts
    })
    lead_time = first - scenario_start if first is not None else None
    precursor_types = {
        EventType.VEHICLE_ENTERED_BUFFER.value,
        EventType.STATION_PROCESSING_COMPLETED.value,
        EventType.MICRO_STOP_OCCURRED.value,
        EventType.VEHICLE_CREATED.value,
    }
    precursor_exists = False
    if first is not None:
        precursor_exists = any(
            scenario_start <= event.simulation_time < first
            and event.event_type in precursor_types
            and (
                target_station_id is None
                or event.station_id == target_station_id
                or event.buffer_id in relevant_buffers
            )
            for event in events
        )

    post_end_low = any(
        event.simulation_time > scenario_end
        and event.occupancy / config.buffers[event.buffer_id].capacity <= 0.5
        for event in occupancy_events
    )
    recovered = None if first is None else bool(all_released and post_end_low)
    micro_stops = [
        event for event in events
        if event.event_type == EventType.MICRO_STOP_OCCURRED.value
        and (target_station_id is None or event.station_id == target_station_id)
        and scenario_start <= event.simulation_time <= scenario_end
    ]

    return {
        "record_type": "run",
        "mechanism": mechanism,
        "target_station_id": target_station_id or "LINE",
        "severity": severity,
        "profile": profile,
        "seed": seed,
        "scenario_start_seconds": scenario_start,
        "scenario_end_seconds": scenario_end,
        "congestion_observation_end_seconds": observation_end,
        "real_congestion": bool(blocking_starts),
        "blocked_episode_count": len(blocking_starts),
        "blocked_seconds": blocked_seconds,
        "time_scenario_start_to_congestion_seconds": lead_time,
        "first_impacted_station_id": first_impacted_station,
        "impacted_station_ids": ";".join(impacted_stations),
        "max_relevant_buffer_occupancy_ratio": max_occupancy,
        "observable_precursor_before_congestion": precursor_exists,
        "recovered_after_scenario": recovered,
        "buffer_recovered_after_scenario": post_end_low,
        "micro_stop_count": len(micro_stops),
        "micro_stop_seconds": sum(event.value or 0.0 for event in micro_stops),
        "vehicles_completed": result.summary["vehicles_completed"],
        "simulated_duration_seconds": result.summary["simulated_duration_seconds"],
    }


def aggregate_scenario_runs(run_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in run_rows:
        grouped[(row["mechanism"], row["target_station_id"], row["severity"], row["profile"])].append(row)

    aggregates = []
    for key, rows in sorted(grouped.items()):
        positive = [row for row in rows if row["real_congestion"]]
        probability = len(positive) / len(rows)
        if probability == 0:
            outcome = "NEGATIVE"
        elif probability < 0.5:
            outcome = "MOSTLY_NEGATIVE"
        elif probability < 1.0:
            outcome = "MIXED"
        else:
            outcome = "POSITIVE"
        lead_times = [row["time_scenario_start_to_congestion_seconds"] for row in positive]
        aggregates.append({
            "record_type": "condition_aggregate",
            "mechanism": key[0],
            "target_station_id": key[1],
            "severity": key[2],
            "profile": key[3],
            "seed": "",
            "run_count": len(rows),
            "runs_with_real_congestion": len(positive),
            "congestion_probability": probability,
            "outcome_class": outcome,
            "mean_blocked_seconds": statistics.fmean(row["blocked_seconds"] for row in rows),
            "max_blocked_seconds": max(row["blocked_seconds"] for row in rows),
            "mean_time_start_to_congestion_seconds": statistics.fmean(lead_times) if lead_times else None,
            "mean_max_relevant_buffer_occupancy_ratio": statistics.fmean(
                row["max_relevant_buffer_occupancy_ratio"] for row in rows
            ),
            "positive_runs_with_observable_precursor": sum(
                row["observable_precursor_before_congestion"] for row in positive
            ),
            "positive_runs_recovered": sum(row["recovered_after_scenario"] is True for row in positive),
        })
    return aggregates
