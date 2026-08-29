"""
Runtime vehicle object. Deliberately minimal: routing/position bookkeeping
only. No defect information, no scenario labels, no future-outcome fields —
those belong to a later step (see PRD Section 26 / ASSUMPTIONS.md).

Genealogy (per-station timing history) is NOT stored here. It is derived
after the fact from the master event stream (see genealogy.py) so there is
exactly one source of truth and no risk of the two disagreeing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Vehicle:
    vehicle_id: str
    variant_id: str
    route: List[str]
    created_at: float
    position: int = 0
    current_station: Optional[str] = None
    completed: bool = False
    completed_at: Optional[float] = None

    def current_station_id(self) -> str:
        return self.route[self.position]

    def is_last_station(self) -> bool:
        return self.position == len(self.route) - 1

    def next_station_id(self) -> Optional[str]:
        if self.is_last_station():
            return None
        return self.route[self.position + 1]
