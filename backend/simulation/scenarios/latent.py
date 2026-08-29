"""
Simulator-only latent truth. Physically separate from backend.simulation.events
— nothing in this module is ever written into an Event or the master event
stream. It exists purely so we can generate realistic outcomes, evaluate
the system later, and debug synthetic data.

Two record types:
  - ScenarioTruthRecord: metadata about one scenario instance that was
    active during a run (what it was, where, when, how severe).
  - QualityExposureRecord: one chronological contribution to a vehicle's
    accumulated latent quality exposure, with enough provenance (which
    scenario, which station) to debug/evaluate, but never anything that
    looks like an ML-ready "defect risk" — that conversion is explicitly
    deferred to Step 4.

LatentTruthLog collects both across a run and is exported separately from
observable data (see scripts/run_scenario_demos.py — written under
data/generated/latent/, never alongside the observable events table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ScenarioTruthRecord:
    scenario_id: str
    family: str
    station_ids: List[str]
    start_time: float
    end_time: Optional[float]
    severity: float
    params: Dict[str, float] = field(default_factory=dict)
    affected_batch_id: Optional[str] = None


@dataclass
class QualityExposureRecord:
    vehicle_id: str
    simulation_time: float
    scenario_id: Optional[str]
    family: str
    station_id: Optional[str]
    contribution: float
    reason: str


class LatentTruthLog:
    def __init__(self) -> None:
        self.scenario_truth: List[ScenarioTruthRecord] = []
        self.quality_exposure: List[QualityExposureRecord] = []

    def record_scenario(self, record: ScenarioTruthRecord) -> None:
        self.scenario_truth.append(record)

    def record_exposure(self, record: QualityExposureRecord) -> None:
        self.quality_exposure.append(record)

    def total_exposure_by_vehicle(self) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for rec in self.quality_exposure:
            totals[rec.vehicle_id] = totals.get(rec.vehicle_id, 0.0) + rec.contribution
        return totals


# Fields that must NEVER appear on an observable Event. Used by tests (and
# available to any future export code) as the single source of truth for
# the prohibited-field leakage check, rather than relying on code review.
PROHIBITED_OBSERVABLE_FIELDS = {
    "scenario_type",
    "scenario_id",
    "scenario_severity",
    "scenario_family",
    "hidden_degradation_state",
    "latent_quality_exposure",
    "quality_exposure",
    "future_defect",
    "will_defect",
    "bad_batch_truth",
    "batch_is_bad",
    "is_bad_batch",
    "true_degradation_state",
}
