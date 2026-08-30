"""Healthy-run metrics for the Flow-v3 nominal line-balance sweep."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Iterable

from backend.config.schemas import FactoryConfig
from backend.flow_v3.capacity_audit import build_capacity_audit
from backend.simulation.events import EventType


def _weighted_quantile(values: list[tuple[float, float]], quantile: float) -> float:
    weighted = sorted((value, weight) for value, weight in values if weight > 0)
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        return 0.0
    threshold = total * quantile
    cumulative = 0.0
    for value, weight in weighted:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return weighted[-1][0]


def _time_weighted_buffer_metrics(events, config: FactoryConfig, sim_end: float) -> tuple[float, float, float, float]:
    occupancy = {buffer_id: 0 for buffer_id in config.buffers}
    last_time = {buffer_id: 0.0 for buffer_id in config.buffers}
    ratio_time = 0.0
    weighted_ratios: list[tuple[float, float]] = []
    weighted_by_buffer: dict[str, list[tuple[float, float]]] = defaultdict(list)
    event_ratios: list[float] = []

    for event in events:
        buffer_id = event.buffer_id
        if buffer_id not in occupancy:
            continue
        if event.event_type not in {
            EventType.VEHICLE_ENTERED_BUFFER.value,
            EventType.VEHICLE_LEFT_BUFFER.value,
        }:
            continue
        elapsed = event.simulation_time - last_time[buffer_id]
        ratio = occupancy[buffer_id] / config.buffers[buffer_id].capacity
        ratio_time += ratio * elapsed
        weighted_ratios.append((ratio, elapsed))
        weighted_by_buffer[buffer_id].append((ratio, elapsed))
        if event.event_type == EventType.VEHICLE_ENTERED_BUFFER.value:
            occupancy[buffer_id] += 1
        else:
            occupancy[buffer_id] -= 1
        event_ratios.append(occupancy[buffer_id] / config.buffers[buffer_id].capacity)
        last_time[buffer_id] = event.simulation_time

    for buffer_id in occupancy:
        elapsed = sim_end - last_time[buffer_id]
        ratio = occupancy[buffer_id] / config.buffers[buffer_id].capacity
        ratio_time += ratio * elapsed
        weighted_ratios.append((ratio, elapsed))
        weighted_by_buffer[buffer_id].append((ratio, elapsed))
    denominator = sim_end * len(config.buffers)
    event_ratios.sort()
    event_p95_index = max(0, math.ceil(0.95 * len(event_ratios)) - 1)
    event_p95 = event_ratios[event_p95_index] if event_ratios else 0.0
    max_buffer_p95 = max((_weighted_quantile(values, 0.95) for values in weighted_by_buffer.values()), default=0.0)
    return (
        ratio_time / denominator if denominator else 0.0,
        _weighted_quantile(weighted_ratios, 0.95),
        max_buffer_p95,
        event_p95,
    )


def _time_weighted_wip(events, sim_end: float) -> float:
    wip = 0
    last_time = 0.0
    area = 0.0
    for event in events:
        if event.event_type not in {EventType.VEHICLE_CREATED.value, EventType.VEHICLE_COMPLETED_LINE.value}:
            continue
        area += wip * (event.simulation_time - last_time)
        wip += 1 if event.event_type == EventType.VEHICLE_CREATED.value else -1
        last_time = event.simulation_time
    area += wip * (sim_end - last_time)
    return area / sim_end if sim_end else 0.0


def measure_healthy_run(result, config: FactoryConfig, *, headway_seconds: float, seed: int) -> dict:
    events = result.events
    sim_end = result.summary["simulated_duration_seconds"]
    blocked_episodes = sum(
        event.event_type == EventType.STATION_STATE_CHANGED.value and event.to_state == "BLOCKED"
        for event in events
    )
    total_blocked = sum(result.summary["blocked_time_per_station"].values())
    total_starved = sum(result.summary["starved_time_per_station"].values())
    queue_mean, queue_p95, max_buffer_queue_p95, event_queue_p95 = _time_weighted_buffer_metrics(events, config, sim_end)
    mean_wip = _time_weighted_wip(events, sim_end)

    completions = sorted(
        event.simulation_time for event in events
        if event.event_type == EventType.VEHICLE_COMPLETED_LINE.value
    )
    warmup = max(1, int(len(completions) * 0.20))
    steady = completions[warmup:]
    intervals = [b - a for a, b in zip(steady, steady[1:])]
    interval_mean = statistics.fmean(intervals) if intervals else float("nan")
    interval_cv = (
        statistics.pstdev(intervals) / interval_mean
        if len(intervals) > 1 and interval_mean > 0 else float("nan")
    )

    physical = build_capacity_audit(config, mean_interarrival_seconds=headway_seconds)
    rhos = [row["nominal_utilization_rho"] for row in physical]
    constraint = max(physical, key=lambda row: row["nominal_utilization_rho"])
    max_buffer_ratio = max(
        result.summary["max_buffer_occupancy"][buffer_id] / buffer.capacity
        for buffer_id, buffer in config.buffers.items()
    )
    return {
        "record_type": "run",
        "headway_seconds": headway_seconds,
        "seed": seed,
        "vehicles_completed": result.summary["vehicles_completed"],
        "simulated_duration_seconds": sim_end,
        "throughput_vehicles_per_hour_full_run": result.summary["throughput_vehicles_per_hour"],
        "throughput_vehicles_per_hour_steady": 3600.0 / interval_mean if interval_mean > 0 else float("nan"),
        "completion_headway_cv_steady": interval_cv,
        "blocked_episode_count": blocked_episodes,
        "total_blocked_seconds": total_blocked,
        "blocked_fraction_of_station_time": total_blocked / (sim_end * len(config.stations)) if sim_end else 0.0,
        "total_starved_seconds": total_starved,
        "starved_fraction_of_station_time": total_starved / (sim_end * len(config.stations)) if sim_end else 0.0,
        "mean_buffer_occupancy_ratio_time_weighted": queue_mean,
        "p95_buffer_occupancy_ratio_time_weighted": queue_p95,
        "max_single_buffer_p95_occupancy_ratio_time_weighted": max_buffer_queue_p95,
        "p95_buffer_occupancy_ratio_at_state_changes": event_queue_p95,
        "max_buffer_occupancy_ratio": max_buffer_ratio,
        "mean_line_wip_time_weighted": mean_wip,
        "physical_rho_max": max(rhos),
        "throughput_constraint_station_id": constraint["station_id"],
        "physical_headroom_station_count_lt_65pct": sum(rho < 0.65 for rho in rhos),
        "physical_moderate_station_count_65_75pct": sum(0.65 <= rho < 0.75 for rho in rhos),
        "physical_sensitive_station_count_75_95pct": sum(0.75 <= rho < 0.95 for rho in rhos),
        "physical_overloaded_station_count_ge_95pct": sum(rho >= 0.95 for rho in rhos),
    }


def aggregate_runs(run_rows: Iterable[dict]) -> list[dict]:
    groups: dict[float, list[dict]] = defaultdict(list)
    for row in run_rows:
        groups[float(row["headway_seconds"])].append(row)
    aggregates = []
    metric_fields = [
        "throughput_vehicles_per_hour_full_run",
        "throughput_vehicles_per_hour_steady",
        "completion_headway_cv_steady",
        "blocked_episode_count",
        "total_blocked_seconds",
        "blocked_fraction_of_station_time",
        "total_starved_seconds",
        "starved_fraction_of_station_time",
        "mean_buffer_occupancy_ratio_time_weighted",
        "p95_buffer_occupancy_ratio_time_weighted",
        "max_single_buffer_p95_occupancy_ratio_time_weighted",
        "p95_buffer_occupancy_ratio_at_state_changes",
        "max_buffer_occupancy_ratio",
        "mean_line_wip_time_weighted",
    ]
    for headway, rows in sorted(groups.items(), reverse=True):
        aggregate = {
            "record_type": "aggregate",
            "headway_seconds": headway,
            "seed": "",
            "run_count": len(rows),
            "healthy_runs_with_any_blocking": sum(row["blocked_episode_count"] > 0 for row in rows),
            "max_blocked_seconds_one_run": max(row["total_blocked_seconds"] for row in rows),
        }
        for field in metric_fields:
            values = [float(row[field]) for row in rows if not math.isnan(float(row[field]))]
            aggregate[f"mean_{field}"] = statistics.fmean(values) if values else float("nan")
            aggregate[f"std_{field}"] = statistics.pstdev(values) if len(values) > 1 else 0.0
        for field in [
            "physical_rho_max",
            "physical_headroom_station_count_lt_65pct",
            "physical_moderate_station_count_65_75pct",
            "physical_sensitive_station_count_75_95pct",
            "physical_overloaded_station_count_ge_95pct",
            "throughput_constraint_station_id",
        ]:
            aggregate[field] = rows[0][field]
        aggregates.append(aggregate)
    return aggregates
