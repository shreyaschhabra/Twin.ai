"""
Assessment Trust (Section 33): HIGH / MEDIUM / LOW via a transparent,
DETERMINISTIC rule -- never presented as a calibrated probability. Risk
(bottleneck_risk, quality_risk, anomaly_score) and Trust are different
axes: a HIGH-risk alert can carry LOW trust (heavily inferred data) and a
LOW-risk read can carry HIGH trust (fully live, fresh evidence).

Exact rule (documented here, not just in code):
  HIGH   : live_fraction >= 0.8 AND unknown_fraction == 0 AND freshness OK
           AND (no virtual-sensor error info, or it's below tolerance)
  LOW    : unknown_fraction >= 0.3 OR freshness stale OR
           (virtual-sensor error known and above tolerance) OR
           n_supporting_signals < MIN_SIGNALS_FOR_HIGH_OR_MEDIUM
  MEDIUM : everything else (some inference present, still enough
           coverage to be usable)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

HIGH_LIVE_FRACTION_THRESHOLD = 0.80
LOW_UNKNOWN_FRACTION_THRESHOLD = 0.30
STALE_FRESHNESS_SECONDS = 600.0
VIRTUAL_SENSOR_ERROR_TOLERANCE = 2.0  # standardized-deviation units
MIN_SIGNALS_FOR_USABLE_TRUST = 1


@dataclass
class TrustAssessment:
    trust_level: str
    reasons: list


def compute_trust_level(
    live_fraction: float,
    inferred_fraction: float,
    unknown_fraction: float,
    freshness_seconds: Optional[float] = None,
    virtual_sensor_error: Optional[float] = None,
    n_supporting_signals: int = 1,
    calibration_ok: Optional[bool] = None,
) -> TrustAssessment:
    reasons = []

    if n_supporting_signals < MIN_SIGNALS_FOR_USABLE_TRUST:
        reasons.append(f"only {n_supporting_signals} supporting signal(s)")
        return TrustAssessment("LOW", reasons)

    if unknown_fraction >= LOW_UNKNOWN_FRACTION_THRESHOLD:
        reasons.append(f"unknown_fraction={unknown_fraction:.2f} >= {LOW_UNKNOWN_FRACTION_THRESHOLD}")
        return TrustAssessment("LOW", reasons)

    if freshness_seconds is not None and freshness_seconds > STALE_FRESHNESS_SECONDS:
        reasons.append(f"stale evidence ({freshness_seconds:.0f}s > {STALE_FRESHNESS_SECONDS:.0f}s)")
        return TrustAssessment("LOW", reasons)

    if virtual_sensor_error is not None and virtual_sensor_error > VIRTUAL_SENSOR_ERROR_TOLERANCE:
        reasons.append(f"virtual-sensor error {virtual_sensor_error:.2f} exceeds tolerance {VIRTUAL_SENSOR_ERROR_TOLERANCE}")
        return TrustAssessment("LOW", reasons)

    if calibration_ok is False:
        reasons.append("model calibration status flagged not-ok")
        return TrustAssessment("LOW", reasons)

    if live_fraction >= HIGH_LIVE_FRACTION_THRESHOLD and unknown_fraction == 0.0:
        reasons.append(f"live_fraction={live_fraction:.2f} >= {HIGH_LIVE_FRACTION_THRESHOLD}, no unknown inputs")
        return TrustAssessment("HIGH", reasons)

    reasons.append("some inferred evidence, coverage still sufficient")
    return TrustAssessment("MEDIUM", reasons)
