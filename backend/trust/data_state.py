"""
Product-facing data state (Sections 28-31): exactly LIVE / INFERRED /
UNKNOWN, no extra states.

LIVE: evidence directly observed and fresh enough to trust as-is.
INFERRED: no fresh direct observation, but a reasonable fallback estimate
    exists via validated same-station or same-station-type evidence, and its estimated error is
    within a documented tolerance.
UNKNOWN: neither of the above -- direct data is unavailable, no reliable
    inference exists, or evidence is too stale. UNKNOWN is a valid,
    intentional answer; INFERRED must never be forced when the fallback
    itself has no real basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Freshness budget: matches the shortest real sensor sampling cadence in
# this factory design (rich-tier stations, ~10-30s per earlier sensor
# generation notes are per-visit, but the practical Flow/Quality lookback
# granularity is 60s) -- direct evidence older than this is not "live"
# even if it's the most recent reading we have.
LIVE_FRESHNESS_SECONDS = 120.0
# Beyond this, even an INFERRED fallback is considered too stale to trust
# at all -- falls through to UNKNOWN.
INFERRED_STALENESS_CEILING_SECONDS = 900.0


@dataclass
class DataStateResult:
    data_state: str  # "LIVE" | "INFERRED" | "UNKNOWN"
    inference_method: Optional[str] = None  # set only when data_state == "INFERRED"
    evidence_age_seconds: Optional[float] = None


def classify_data_state(
    has_direct_reading: bool,
    evidence_age_seconds: Optional[float],
    inference_available: bool,
    inference_method: Optional[str] = None,
    inference_reliable: bool = True,
) -> DataStateResult:
    if has_direct_reading and evidence_age_seconds is not None and evidence_age_seconds <= LIVE_FRESHNESS_SECONDS:
        return DataStateResult("LIVE", evidence_age_seconds=evidence_age_seconds)

    if inference_available and inference_reliable and (
        evidence_age_seconds is None or evidence_age_seconds <= INFERRED_STALENESS_CEILING_SECONDS
    ):
        return DataStateResult("INFERRED", inference_method=inference_method, evidence_age_seconds=evidence_age_seconds)

    return DataStateResult("UNKNOWN", evidence_age_seconds=evidence_age_seconds)
