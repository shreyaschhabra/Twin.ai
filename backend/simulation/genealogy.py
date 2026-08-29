"""
Vehicle genealogy, reconstructed from the master event stream — never
maintained as a second, independently-mutated structure during simulation,
so it cannot disagree with the event log by construction.

Relies on one convention from events.py: a VEHICLE_ENTERED_BUFFER event's
`station_id` always names the station the vehicle is now queued FOR (its
upcoming station), whether that buffer is the initial entry queue or an
ordinary inter-station buffer. That gives a uniform definition of
`entry_time` for every station a vehicle visits, including its first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from backend.simulation.events import Event, EventType


@dataclass
class StationVisitRecord:
    station_id: str
    entry_time: float
    processing_start_time: float
    processing_completion_time: float
    exit_time: float
    waiting_time: float
    processing_time: float
    blocked_time: float


def build_genealogy(events: List[Event]) -> Dict[str, List[StationVisitRecord]]:
    """Single chronological pass over the event stream. For each vehicle,
    keeps at most one "open" visit (the station it's currently at) and
    closes it out — computing waiting/processing/blocked time — the moment
    either a VEHICLE_ENTERED_BUFFER for its *next* station or a
    VEHICLE_COMPLETED_LINE event confirms it has left."""

    genealogy: Dict[str, List[StationVisitRecord]] = {}
    pending_entry: Dict[Tuple[str, str], float] = {}
    open_visit: Dict[str, Tuple[str, dict]] = {}  # vehicle_id -> (station_id, partial record)

    for event in events:
        vid = event.vehicle_id
        if vid is None:
            continue

        if event.event_type == EventType.VEHICLE_ENTERED_BUFFER.value:
            if vid in open_visit:
                station_id, record = open_visit[vid]
                if station_id != event.station_id:
                    open_visit.pop(vid)
                    _close_and_store(genealogy, vid, station_id, record, event.simulation_time)
            pending_entry[(vid, event.station_id)] = event.simulation_time

        elif event.event_type == EventType.VEHICLE_ENTERED_STATION.value:
            entry_time = pending_entry.pop((vid, event.station_id), event.simulation_time)
            open_visit[vid] = (event.station_id, {"entry_time": entry_time})

        elif event.event_type == EventType.STATION_PROCESSING_STARTED.value:
            _, record = open_visit[vid]
            record["processing_start_time"] = event.simulation_time

        elif event.event_type == EventType.STATION_PROCESSING_COMPLETED.value:
            _, record = open_visit[vid]
            record["processing_completion_time"] = event.simulation_time
            record["processing_time"] = event.value

        elif event.event_type == EventType.VEHICLE_COMPLETED_LINE.value:
            station_id, record = open_visit.pop(vid)
            _close_and_store(genealogy, vid, station_id, record, event.simulation_time)

    return genealogy


def _close_and_store(genealogy, vehicle_id, station_id, record, exit_time) -> None:
    record["exit_time"] = exit_time
    record["waiting_time"] = record["processing_start_time"] - record["entry_time"]
    record["blocked_time"] = exit_time - record["processing_completion_time"]
    visit = StationVisitRecord(
        station_id=station_id,
        entry_time=record["entry_time"],
        processing_start_time=record["processing_start_time"],
        processing_completion_time=record["processing_completion_time"],
        exit_time=record["exit_time"],
        waiting_time=record["waiting_time"],
        processing_time=record["processing_time"],
        blocked_time=record["blocked_time"],
    )
    genealogy.setdefault(vehicle_id, []).append(visit)
