"""Station model, mirroring the ``factory.json`` station contract.

DARK membership is a property of the factory's ``darkZones``, not of
``sensorCoverage`` -- a DARK station may still emit telemetry, and a LIGHT station may
have none. :meth:`Station.from_factory` keeps them separate for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Station:
    """One station on the configured line."""

    id: int
    name: str
    archetype: str
    mean_cycle_time_ms: int
    cycle_time_cv: float
    buffer_capacity: int
    sensor_coverage: str
    is_source: bool = False
    is_sink: bool = False
    #: True when this station falls inside a configured DARK corridor.
    is_dark: bool = False
    dark_zone_id: str | None = None

    @property
    def zone(self) -> str:
        """`DARK` or `LIGHT`, matching the prediction streams' `zone` field."""
        return "DARK" if self.is_dark else "LIGHT"

    @classmethod
    def from_factory(cls, data: dict[str, Any], dark_zones: list[dict[str, Any]] | None = None) -> Station:
        """Build a station from a ``factory.json`` entry, resolving DARK membership."""
        station_id = int(data["id"])
        zone_id: str | None = None
        for zone in dark_zones or []:
            start, end = zone.get("startStationId"), zone.get("endStationId")
            if isinstance(start, int) and isinstance(end, int) and start <= station_id <= end:
                zone_id = str(zone.get("id")) if zone.get("id") else None
                break
        return cls(
            id=station_id,
            name=str(data.get("name", f"Station {station_id}")),
            archetype=str(data.get("archetype", "AUTOMATED")),
            mean_cycle_time_ms=int(data.get("meanCycleTimeMs", 0)),
            cycle_time_cv=float(data.get("cycleTimeCV", 0.0)),
            buffer_capacity=int(data.get("bufferCapacity", 0)),
            sensor_coverage=str(data.get("sensorCoverage", "NONE")),
            is_source=data.get("source") is True,
            is_sink=data.get("sink") is True,
            is_dark=zone_id is not None,
            dark_zone_id=zone_id,
        )

    @classmethod
    def all_from_factory(cls, factory: dict[str, Any]) -> list[Station]:
        """Build every station from a validated factory payload, in line order."""
        zones = factory.get("darkZones") or []
        stations = [
            cls.from_factory(entry, zones)
            for entry in factory.get("stations", [])
            if isinstance(entry, dict)
        ]
        return sorted(stations, key=lambda station: station.id)
