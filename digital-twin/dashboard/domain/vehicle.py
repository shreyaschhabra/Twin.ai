"""Vehicle (production unit) model.

Placeholder for later per-vehicle views. Defect risk is a vehicle-quality signal and is
kept distinct from station-level bottleneck risk; the two are never combined.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Vehicle:
    """One production unit as identified in the defect prediction stream."""

    unit_id: str
    #: Last station the unit was observed or inferred at.
    station_id: str | None = None
    #: `LIGHT` or `DARK_INFERRED`, per the defect prediction contract.
    route: str | None = None
