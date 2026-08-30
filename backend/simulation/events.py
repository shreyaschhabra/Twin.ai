"""
The internal master event stream: one canonical, chronological representation
of complete simulator mechanics. Deployable consumers must use
``backend.observability.build_public_event_stream`` rather than consuming this
internal stream directly.

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
- Scenario identity and latent quality truth are physically separate from
  events. Some exact mechanics here are nevertheless INTERNAL_ONLY under the
  observability policy (for example the sampled work duration attached to a
  processing-start event, or exact state transitions at a poor station).
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
    # Step 4 addition. Emitted ONLY at the configured QC station, after
    # that vehicle's processing there completes. Never carries latent
    # exposure/probability/scenario-cause information — see
    # backend/simulation/qc.py and scenarios/latent.py for where that
    # lives instead.
    QC_RESULT_RECORDED = "QC_RESULT_RECORDED"


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
    # Step 4: canonical globally-unique batch identity, since batch_id
    # numbering is per-station (see material_batches.py) — a naked
    # batch_id like "B1002" is NOT globally unique on its own.
    batch_key: Optional[str] = None
    # Step 4 addition, used only by QC_RESULT_RECORDED
    qc_result: Optional[str] = None


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
