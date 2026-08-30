"""
Lightweight Flow onset estimate (Section 35). No Monte Carlo engine: a
simple deterministic queue projection from current buffer occupancy and
recent arrival/departure rates. Returns null (None) rather than
fabricating precision when there isn't enough information to project.
"""

from __future__ import annotations

from typing import Optional, Tuple


def estimate_onset_window(
    current_occupancy: float,
    buffer_capacity: float,
    arrivals_per_min: float,
    departures_per_min: float,
    uncertainty_band: float = 0.25,
) -> Tuple[Optional[float], Optional[float]]:
    """Deterministic linear queue projection: time-to-full = remaining
    capacity / net fill rate, converted to minutes. Returns
    (predicted_onset_min, predicted_onset_max) as a band around that
    point estimate, or (None, None) if the queue isn't net growing (net
    fill rate <= 0) or there isn't enough rate information."""
    if buffer_capacity <= 0 or current_occupancy >= buffer_capacity:
        return None, None
    net_fill_rate = arrivals_per_min - departures_per_min
    if net_fill_rate <= 1e-6:
        return None, None

    remaining = buffer_capacity - current_occupancy
    point_estimate_min = remaining / net_fill_rate
    return (
        round(point_estimate_min * (1 - uncertainty_band), 2),
        round(point_estimate_min * (1 + uncertainty_band), 2),
    )
