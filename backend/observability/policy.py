"""Deterministic internal-to-public event projection.

The simulator remains authoritative internal truth.  This module is the only
supported boundary for deployable consumers: Flow, Quality, Anomaly, and Trust
must consume ``PublicEvent`` objects rather than ``RunResult.events``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Optional

from backend.config.schemas import FactoryConfig, SensorMaturity
from backend.simulation.events import Event, EventType


class ObservabilityClass(str, Enum):
    PUBLIC_DIRECT = "PUBLIC_DIRECT"
    PUBLIC_DERIVED = "PUBLIC_DERIVED"
    CONDITIONALLY_OBSERVABLE = "CONDITIONALLY_OBSERVABLE"
    INTERNAL_ONLY = "INTERNAL_ONLY"


class EvidenceSource(str, Enum):
    MES = "MES"
    PLC_SCADA = "PLC_SCADA"
    SENSOR = "SENSOR"
    QMS = "QMS"
    MANUAL = "MANUAL"


@dataclass(frozen=True, slots=True)
class PublicEvent:
    """A deliberately narrow public schema with no latent/future fields."""

    event_id: int
    simulation_time: float
    event_type: str
    observability_class: str
    evidence_source: str
    confidence: float
    vehicle_id: Optional[str] = None
    vehicle_variant: Optional[str] = None
    station_id: Optional[str] = None
    buffer_id: Optional[str] = None
    route_position: Optional[int] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    value: Optional[float] = None
    occupancy: Optional[int] = None
    sensor_name: Optional[str] = None
    unit: Optional[str] = None
    measurement_status: Optional[str] = None
    batch_id: Optional[str] = None
    batch_key: Optional[str] = None
    qc_result: Optional[str] = None


_COARSE_STATE = {
    "IDLE": "IDLE",
    "STARVED": "WAITING",
    "PROCESSING": "RUNNING",
    "BLOCKED": "FLOW_STOP",
    "DOWN": "EQUIPMENT_STOP",
}


def _base(event: Event, *, cls: ObservabilityClass, source: EvidenceSource, confidence: float) -> PublicEvent:
    # event_id is replaced after filtering so gaps cannot reveal suppressed
    # internal events.
    return PublicEvent(
        event_id=0,
        simulation_time=event.simulation_time,
        event_type=event.event_type,
        observability_class=cls.value,
        evidence_source=source.value,
        confidence=confidence,
        vehicle_id=event.vehicle_id,
        vehicle_variant=event.vehicle_variant,
        station_id=event.station_id,
        route_position=event.route_position,
    )


def _maturity(event: Event, config: FactoryConfig) -> SensorMaturity:
    if event.station_id in config.stations:
        return config.stations[event.station_id].sensor_maturity
    return SensorMaturity.RICH


def _project_one(event: Event, config: FactoryConfig) -> Optional[PublicEvent]:
    event_type = event.event_type
    maturity = _maturity(event, config)

    if event_type in {EventType.VEHICLE_CREATED.value, EventType.VEHICLE_COMPLETED_LINE.value}:
        return _base(event, cls=ObservabilityClass.PUBLIC_DIRECT, source=EvidenceSource.MES, confidence=0.99)

    if event_type == EventType.VEHICLE_ENTERED_STATION.value:
        cls = ObservabilityClass.PUBLIC_DIRECT if maturity != SensorMaturity.POOR else ObservabilityClass.CONDITIONALLY_OBSERVABLE
        confidence = 0.97 if maturity == SensorMaturity.RICH else (0.85 if maturity == SensorMaturity.PARTIAL else 0.65)
        source = EvidenceSource.MES if maturity != SensorMaturity.POOR else EvidenceSource.MANUAL
        return _base(event, cls=cls, source=source, confidence=confidence)

    if event_type in {EventType.VEHICLE_ENTERED_BUFFER.value, EventType.VEHICLE_LEFT_BUFFER.value}:
        if maturity == SensorMaturity.POOR:
            return None
        direct = maturity == SensorMaturity.RICH
        public = _base(
            event,
            cls=ObservabilityClass.PUBLIC_DIRECT if direct else ObservabilityClass.CONDITIONALLY_OBSERVABLE,
            source=EvidenceSource.PLC_SCADA,
            confidence=0.95 if direct else 0.70,
        )
        return replace(
            public,
            buffer_id=event.buffer_id,
            occupancy=event.occupancy if direct else None,
        )

    if event_type == EventType.STATION_PROCESSING_STARTED.value:
        if maturity == SensorMaturity.POOR:
            return None
        # Internal event.value is the simulator's sampled future work time.
        # The start pulse is public; that future duration is never public.
        return _base(
            event,
            cls=ObservabilityClass.PUBLIC_DIRECT if maturity == SensorMaturity.RICH else ObservabilityClass.CONDITIONALLY_OBSERVABLE,
            source=EvidenceSource.PLC_SCADA,
            confidence=0.98 if maturity == SensorMaturity.RICH else 0.72,
        )

    if event_type == EventType.STATION_PROCESSING_COMPLETED.value:
        direct = maturity == SensorMaturity.RICH
        public = _base(
            event,
            cls=ObservabilityClass.PUBLIC_DIRECT if direct else ObservabilityClass.CONDITIONALLY_OBSERVABLE,
            source=EvidenceSource.PLC_SCADA if maturity != SensorMaturity.POOR else EvidenceSource.MES,
            confidence=0.98 if direct else (0.72 if maturity == SensorMaturity.PARTIAL else 0.60),
        )
        return replace(public, value=event.value if direct else None)

    if event_type == EventType.STATION_STATE_CHANGED.value:
        if maturity == SensorMaturity.POOR:
            return None
        if maturity == SensorMaturity.RICH:
            public = _base(event, cls=ObservabilityClass.PUBLIC_DIRECT, source=EvidenceSource.PLC_SCADA, confidence=0.97)
            return replace(
                public,
                from_state=event.from_state,
                to_state=event.to_state,
                buffer_id=event.buffer_id,
                occupancy=event.occupancy,
            )
        public = _base(event, cls=ObservabilityClass.PUBLIC_DERIVED, source=EvidenceSource.PLC_SCADA, confidence=0.68)
        return replace(
            public,
            from_state=_COARSE_STATE.get(event.from_state) if event.from_state else None,
            to_state=_COARSE_STATE.get(event.to_state) if event.to_state else None,
        )

    if event_type == EventType.SENSOR_READING.value:
        if maturity == SensorMaturity.RICH:
            cls, source, confidence = ObservabilityClass.PUBLIC_DIRECT, EvidenceSource.SENSOR, 0.96
        elif maturity == SensorMaturity.PARTIAL:
            cls, source, confidence = ObservabilityClass.CONDITIONALLY_OBSERVABLE, EvidenceSource.SENSOR, 0.72
        else:
            # Poor-station configured signals are sparse manual/checkpoint
            # evidence, not full process telemetry.
            cls, source, confidence = ObservabilityClass.CONDITIONALLY_OBSERVABLE, EvidenceSource.MANUAL, 0.52
        public = _base(event, cls=cls, source=source, confidence=confidence)
        return replace(
            public,
            value=event.value,
            sensor_name=event.sensor_name,
            unit=event.unit,
            measurement_status=event.measurement_status,
        )

    if event_type == EventType.MICRO_STOP_OCCURRED.value:
        if maturity == SensorMaturity.POOR:
            return None
        direct = maturity == SensorMaturity.RICH
        public = _base(
            event,
            cls=ObservabilityClass.PUBLIC_DIRECT if direct else ObservabilityClass.CONDITIONALLY_OBSERVABLE,
            source=EvidenceSource.PLC_SCADA,
            confidence=0.95 if direct else 0.66,
        )
        return replace(public, value=event.value if direct else None)

    if event_type == EventType.MATERIAL_BATCH_ASSIGNED.value:
        cls = ObservabilityClass.PUBLIC_DIRECT if maturity == SensorMaturity.RICH else ObservabilityClass.CONDITIONALLY_OBSERVABLE
        source = EvidenceSource.MES if maturity != SensorMaturity.POOR else EvidenceSource.MANUAL
        public = _base(event, cls=cls, source=source, confidence=0.95 if maturity == SensorMaturity.RICH else 0.68)
        return replace(public, batch_id=event.batch_id, batch_key=event.batch_key)

    if event_type == EventType.QC_RESULT_RECORDED.value:
        public = _base(event, cls=ObservabilityClass.PUBLIC_DIRECT, source=EvidenceSource.QMS, confidence=0.99)
        return replace(public, qc_result=event.qc_result)

    raise ValueError(f"unclassified internal event type {event_type!r}")


def build_public_event_stream(events: Iterable[Event], config: FactoryConfig) -> list[PublicEvent]:
    """Project a chronological internal stream into deployable observations."""
    public: list[PublicEvent] = []
    previous_time = float("-inf")
    for event in events:
        if event.simulation_time < previous_time:
            raise ValueError("internal event stream is not chronological")
        previous_time = event.simulation_time
        projected = _project_one(event, config)
        if projected is not None:
            public.append(replace(projected, event_id=len(public) + 1))
    return public


def public_events_as_of(events: Iterable[PublicEvent], cutoff_time: float) -> list[PublicEvent]:
    """Return only evidence observable at or before a feature timestamp."""
    return [event for event in events if event.simulation_time <= cutoff_time]
