"""Digital-twin queue projection (Section 21): the ONLY layer allowed to
read current buffer occupancy/capacity. Combines that physics state with
the ML precursor's predicted future service rate to project time-to-
blocking. This is deterministic queueing arithmetic plus a small (~20-draw)
Monte Carlo over recent service-rate variability -- not a calibrated
probability model.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

N_STOCHASTIC_PROJECTIONS = 20
CRITICAL_MINUTES = 5.0
HIGH_MINUTES = 15.0
WATCH_MINUTES = 30.0


@dataclass
class QueueProjection:
    risk_level: str  # NORMAL | WATCH | HIGH | CRITICAL
    arrival_rate_vph: float
    predicted_service_rate_vph: float
    service_deficit_vph: float
    time_to_blocking_minutes: Optional[float]
    predicted_onset_min: Optional[float]
    predicted_onset_max: Optional[float]
    current_occupancy: int
    buffer_capacity: int

    def as_dict(self) -> dict:
        return {
            "riskLevel": self.risk_level,
            "arrivalRate": round(self.arrival_rate_vph, 3),
            "predictedServiceRate": round(self.predicted_service_rate_vph, 3),
            "serviceDeficit": round(self.service_deficit_vph, 3),
            "predictedOnsetMin": None if self.predicted_onset_min is None else round(self.predicted_onset_min, 1),
            "predictedOnsetMax": None if self.predicted_onset_max is None else round(self.predicted_onset_max, 1),
            "bufferOccupancy": self.current_occupancy,
            "bufferCapacity": self.buffer_capacity,
        }


def _risk_from_minutes(minutes: Optional[float], already_full: bool) -> str:
    if already_full:
        return "CRITICAL"
    if minutes is None:
        return "NORMAL"
    if minutes <= CRITICAL_MINUTES:
        return "CRITICAL"
    if minutes <= HIGH_MINUTES:
        return "HIGH"
    if minutes <= WATCH_MINUTES:
        return "WATCH"
    return "NORMAL"


def project_queue_risk(
    *,
    current_occupancy: int,
    buffer_capacity: int,
    arrival_rate_vph: float,
    predicted_service_rate_vph: float,
    service_rate_std_vph: float = 0.0,
    seed: int = 0,
) -> QueueProjection:
    """Deterministic core: service_deficit = arrival - predicted_service.

    deficit <= 0 -> no finite projected fill (Section 21).
    deficit > 0  -> queue accumulates; time_to_blocking is how long until
    the remaining headroom (capacity - current_occupancy) is consumed at
    the deficit rate.

    When service_rate_std_vph > 0, ~20 short stochastic draws perturb the
    predicted service rate by recent variability and each yields its own
    (possibly infinite) time-to-blocking; predictedOnsetMin/Max are the
    25th/75th percentile of the FINITE draws, an uncertainty interval, not
    a calibrated probability.
    """
    headroom = max(0, buffer_capacity - current_occupancy)
    already_full = current_occupancy >= buffer_capacity
    deficit = arrival_rate_vph - predicted_service_rate_vph

    def _minutes_for(service_rate: float) -> Optional[float]:
        local_deficit = arrival_rate_vph - service_rate
        if local_deficit <= 0:
            return None
        if headroom == 0:
            return 0.0
        return headroom / local_deficit * 60.0

    point_minutes = _minutes_for(predicted_service_rate_vph)

    onset_min = onset_max = None
    if service_rate_std_vph > 0 and point_minutes is not None:
        rng = random.Random(seed)
        draws = [
            _minutes_for(max(1e-6, rng.gauss(predicted_service_rate_vph, service_rate_std_vph)))
            for _ in range(N_STOCHASTIC_PROJECTIONS)
        ]
        finite = sorted(m for m in draws if m is not None)
        if finite:
            onset_min = finite[max(0, int(0.25 * (len(finite) - 1)))]
            onset_max = finite[max(0, int(0.75 * (len(finite) - 1)))]
    elif point_minutes is not None:
        # No variability estimate available: report the deterministic
        # point projection as a degenerate interval rather than fabricating
        # spread (Section 21: "deterministic projection + uncertainty
        # interval" is the accepted fallback).
        onset_min = onset_max = point_minutes

    risk_level = _risk_from_minutes(point_minutes, already_full)

    return QueueProjection(
        risk_level=risk_level,
        arrival_rate_vph=arrival_rate_vph,
        predicted_service_rate_vph=predicted_service_rate_vph,
        service_deficit_vph=deficit,
        time_to_blocking_minutes=point_minutes,
        predicted_onset_min=onset_min,
        predicted_onset_max=onset_max,
        current_occupancy=current_occupancy,
        buffer_capacity=buffer_capacity,
    )
