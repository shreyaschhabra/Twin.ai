"""
The master event stream: one canonical, chronological event representation
that Flow and Quality feature tables will both eventually be derived from
(see PRD Section 14).

Design decisions worth documenting:

- No separate FINAL_QC_ENTERED / FINAL_QC_COMPLETED event types. Whichever
  station is last in a vehicle's route already emits
  VEHICLE_ENTERED_STATION / STATION_PROCESSING_STARTED /
  STATION_PROCESSING_COMPLETED / VEHICLE_COMPLETED_LINE with that station's
  id — a separate QC-specific event pair would duplicate the exact same
  timestamp/vehicle/station information under a different name. A QC-type
  station is identified by joining station_id back to station_type in the
  config (station_type == INSPECTION_EOL_TESTING), not by a redundant event.
- VEHICLE_ENTERED_BUFFER.station_id always means "the station this buffer
  feeds into" (i.e. the vehicle's upcoming station), for both the initial
  entry buffer and every ordinary inter-station buffer. This one consistent
  convention is what genealogy.py relies on to reconstruct per-station
  waiting time.
- No hidden future-outcome fields (no defect label, no scenario id, no
  "will be blocked" flag) are ever attached to an event. Every field is
  something that would be observable in real plant telemetry at the moment
  the event occurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class EventType(str, Enum):
    VEHICLE_CREATED = "VEHICLE_CREATED"
    VEHICLE_ENTERED_BUFFER = "VEHICLE_ENTERED_BUFFER"
    VEHICLE_LEFT_BUFFER = "VEHICLE_LEFT_BUFFER"
    VEHICLE_ENTERED_STATION = "VEHICLE_ENTERED_STATION"
    STATION_PROCESSING_STARTED = "STATION_PROCESSING_STARTED"
    STATION_PROCESSING_COMPLETED = "STATION_PROCESSING_COMPLETED"
    STATION_STATE_CHANGED = "STATION_STATE_CHANGED"
    VEHICLE_COMPLETED_LINE = "VEHICLE_COMPLETED_LINE"
    # Step 3 additions — all observable (a real plant could plausibly
    # produce every field on these). See scenarios/latent.py for the
    # physically separate latent-truth representation these must never
    # be confused with.
    SENSOR_READING = "SENSOR_READING"
    MICRO_STOP_OCCURRED = "MICRO_STOP_OCCURRED"
    MATERIAL_BATCH_ASSIGNED = "MATERIAL_BATCH_ASSIGNED"


@dataclass
class Event:
    event_id: int
    simulation_time: float
    event_type: str
    vehicle_id: Optional[str] = None
    vehicle_variant: Optional[str] = None
    station_id: Optional[str] = None
    buffer_id: Optional[str] = None
    route_position: Optional[int] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    value: Optional[float] = None
    occupancy: Optional[int] = None
    # Step 3 additions, used only by SENSOR_READING / MATERIAL_BATCH_ASSIGNED
    sensor_name: Optional[str] = None
    unit: Optional[str] = None
    measurement_status: Optional[str] = None
    batch_id: Optional[str] = None


class EventLog:
    """Append-only, auto-numbered, chronologically-enforced event collector."""

    def __init__(self) -> None:
        self._events: List[Event] = []
        self._next_id = 1
        self._last_time = float("-inf")

    def record(self, event_type: EventType, simulation_time: float, **fields) -> Event:
        if simulation_time < self._last_time:
            raise RuntimeError(
                f"non-chronological event: {event_type} at {simulation_time} "
                f"after previously recorded event at {self._last_time}"
            )
        event = Event(
            event_id=self._next_id,
            simulation_time=simulation_time,
            event_type=event_type.value,
            **fields,
        )
        self._next_id += 1
        self._last_time = simulation_time
        self._events.append(event)
        return event

    @property
    def events(self) -> List[Event]:
        return self._events
