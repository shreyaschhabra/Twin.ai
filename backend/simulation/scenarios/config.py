"""
Scenario definitions: configuration-driven, loaded from YAML (e.g.
configs/development_scenarios.yaml), physically separate from the factory
topology config (Step 1) and never merged into observable data.

This IS simulator truth. A scenario_id/family here must never be injected
into the master event stream — see backend/simulation/scenarios/latent.py.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field


class ScenarioFamily(str, Enum):
    EQUIPMENT_DEGRADATION = "EQUIPMENT_DEGRADATION"
    MICRO_STOPS = "MICRO_STOPS"
    VEHICLE_MIX_OVERLOAD = "VEHICLE_MIX_OVERLOAD"
    BAD_BATCH = "BAD_BATCH"
    ENVIRONMENTAL_DRIFT = "ENVIRONMENTAL_DRIFT"
    SENSOR_DROPOUT = "SENSOR_DROPOUT"
    MANUAL_VARIATION = "MANUAL_VARIATION"
    RANDOM_QUALITY_EVENT = "RANDOM_QUALITY_EVENT"
    ARRIVAL_BURST = "ARRIVAL_BURST"


class ScenarioDefinition(BaseModel):
    scenario_id: str
    family: ScenarioFamily
    station_ids: List[str] = Field(default_factory=list)
    start_time: float = 0.0
    duration: Optional[float] = None  # None = active through end of run
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    affected_sensors: List[str] = Field(default_factory=list)
    params: Dict[str, float] = Field(default_factory=dict)
    affected_batch_id: Optional[str] = None
    variant_mix_override: Optional[Dict[str, float]] = None
    dropout_type: Optional[str] = None  # "missing" | "stuck" | "noisy"
    temporal_profile: Optional[str] = None

    def is_active_at(self, sim_time: float) -> bool:
        if sim_time < self.start_time:
            return False
        if self.duration is None:
            return True
        return sim_time <= self.start_time + self.duration

    def elapsed_fraction(self, sim_time: float, ramp_duration: float) -> float:
        """0..1 progress through a ramp of the given duration, starting at
        this scenario's start_time. Used by families that must develop
        gradually rather than switch on abruptly."""
        if ramp_duration <= 0:
            return 1.0 if sim_time >= self.start_time else 0.0
        elapsed = sim_time - self.start_time
        return max(0.0, min(1.0, elapsed / ramp_duration))

    def profile_fraction(self, sim_time: float, default_profile: str = "STEP") -> float:
        """Return deterministic 0..1 effect strength for a temporal profile."""
        if not self.is_active_at(sim_time):
            return 0.0
        profile = (self.temporal_profile or default_profile).upper()
        if profile in {"STEP", "STEP_BURST"} or self.duration is None:
            return 1.0
        progress = self.elapsed_fraction(sim_time, self.duration)
        if profile == "GRADUAL":
            # Develop during the first half, then persist at full strength.
            # A ramp that only reaches its maximum as the scenario ends has
            # no sustained disturbed state and is not operationally useful.
            return min(1.0, progress / 0.5)
        if profile == "ACCELERATING":
            return progress * progress
        if profile == "RECOVERING":
            if progress < 0.25:
                return progress / 0.25
            if progress <= 0.65:
                return 1.0
            return max(0.0, (1.0 - progress) / 0.35)
        if profile == "RAMP_BURST":
            return min(1.0, progress / 0.25)
        if profile == "INTERMITTENT":
            period = max(60.0, self.params.get("intermittent_period_seconds", 600.0))
            duty = max(0.05, min(0.95, self.params.get("intermittent_duty_cycle", 0.5)))
            phase = ((sim_time - self.start_time) % period) / period
            return 1.0 if phase < duty else 0.0
        raise ValueError(f"unsupported temporal profile {profile!r}")


def load_scenarios(path: Union[str, Path]) -> List[ScenarioDefinition]:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Scenario config file not found: {resolved}")
    with resolved.open("r") as f:
        data = yaml.safe_load(f) or {}
    return [
        ScenarioDefinition(scenario_id=scenario_id, **fields)
        for scenario_id, fields in data.get("scenarios", {}).items()
    ]
