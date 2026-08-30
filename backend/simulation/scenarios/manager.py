"""
ScenarioManager: the single mediator between "what scenarios are
configured" and "what effect does that have right now, here". Station code
never branches on station_id or scenario family — it asks the manager for
an effect bundle and applies whatever comes back generically.

Design: querying station effects (get_station_effects) is deterministic
GIVEN a vehicle/time/station — no RNG lives inside this class. Anything
genuinely random (whether a micro-stop actually fires this visit, its
exact duration, whether a rare background quality event fires for this
vehicle) is rolled by the CALLER using its own isolated RNG stream; the
manager only supplies the parameters (probabilities, ranges) that govern
that roll. This keeps the manager pure/testable and keeps every random
draw traceable to one named, isolated stream (see rng.py).

Material/component batches are NOT assigned here (see Step 3 patch 2):
that is a baseline production concern that must happen for every vehicle
at a batch-relevant station regardless of whether any scenario exists —
see backend/simulation/material_batches.py. This manager's only batch-
related job is check_batch_exposure(): given an already-assigned,
already-observable batch_id, decide whether a BAD_BATCH scenario has
latently marked that specific id as quality-degraded. The batch_id itself
never depends on scenario configuration, which is exactly what makes the
matched baseline/bad-batch observable-schedule comparison valid.

COMPOSITION SEMANTICS (Step 3 patch 3) — when more than one scenario
targets the same station, effects combine by simple, fixed rules rather
than a conflict solver:
  - cycle_time_multiplier: multiplied across all active scenarios
  - variability_multiplier: multiplied across all active scenarios
  - sensor_mean_shift: summed per sensor across all active scenarios
  - sensor_noise_multiplier: multiplied per sensor
  - sensor dropout: NOT composed — if more than one SENSOR_DROPOUT
    scenario targets the same sensor, the last one encountered in
    `scenarios` list order wins. This is a deliberate, documented
    simplification (no dropout "severity stacking"), not an oversight.
  - latent quality exposure: every contributing scenario records its own
    QualityExposureRecord independently; a vehicle's total exposure is
    just the sum (see LatentTruthLog.total_exposure_by_vehicle).
Multiplicative fields are clamped (see _MAX_MULTIPLIER below) so stacking
several scenarios on one station can't silently produce an unbounded or
physically nonsensical cycle time — this is a safety clamp, not a
negotiated interaction between families.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily
from backend.simulation.scenarios.effects import StationEffectBundle
from backend.simulation.scenarios.latent import (
    LatentTruthLog,
    QualityExposureRecord,
    ScenarioTruthRecord,
)

# Safety clamp on composed multiplicative effects (patch 3): prevents
# several stacked scenarios on the same station from producing an
# unbounded/impossible cycle time. Not a claim about any real physical
# limit — just a sanity ceiling.
_MAX_MULTIPLIER = 5.0


class ScenarioManager:
    def __init__(self, scenarios: List[ScenarioDefinition], latent_log: LatentTruthLog):
        self.scenarios = scenarios
        self.latent_log = latent_log
        for s in scenarios:
            latent_log.record_scenario(
                ScenarioTruthRecord(
                    scenario_id=s.scenario_id,
                    family=s.family.value,
                    station_ids=list(s.station_ids),
                    start_time=s.start_time,
                    end_time=(s.start_time + s.duration) if s.duration is not None else None,
                    severity=s.severity,
                    params=dict(s.params),
                    affected_batch_id=s.affected_batch_id,
                )
            )

    def _active(self, sim_time: float, families: set, station_id: Optional[str] = None):
        for s in self.scenarios:
            if s.family not in families:
                continue
            if not s.is_active_at(sim_time):
                continue
            if station_id is not None and s.station_ids and station_id not in s.station_ids:
                continue
            yield s

    # ---- deterministic effects, queried once per vehicle-station visit ----

    def get_station_effects(self, sim_time: float, station_id: str, vehicle_id: str) -> StationEffectBundle:
        bundle = StationEffectBundle()

        for s in self._active(sim_time, {ScenarioFamily.EQUIPMENT_DEGRADATION}, station_id):
            ramp = s.params.get("ramp_duration_seconds", 3600.0)
            frac = (
                s.elapsed_fraction(sim_time, ramp)
                if s.temporal_profile is None
                else s.profile_fraction(sim_time, default_profile="GRADUAL")
            )
            max_cycle_mult = s.params.get("max_cycle_time_multiplier", 1.0)
            max_noise_mult = s.params.get("max_noise_multiplier", 1.0)
            max_sensor_shift = s.params.get("max_sensor_mean_shift", 0.0)
            quality_weight = s.params.get("quality_weight_per_visit", 0.0)

            bundle.cycle_time_multiplier *= 1 + frac * (max_cycle_mult - 1)
            bundle.variability_multiplier *= 1 + frac * (max_noise_mult - 1)
            for sensor in s.affected_sensors:
                bundle.sensor_mean_shift[sensor] = bundle.sensor_mean_shift.get(sensor, 0.0) + frac * max_sensor_shift
                bundle.sensor_noise_multiplier[sensor] = bundle.sensor_noise_multiplier.get(sensor, 1.0) * (
                    1 + frac * (max_noise_mult - 1)
                )
            bundle.active_scenario_ids.append(s.scenario_id)

            if quality_weight > 0 and frac > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, frac * quality_weight, "equipment_degradation")

        for s in self._active(sim_time, {ScenarioFamily.MANUAL_VARIATION}, station_id):
            frac = s.profile_fraction(sim_time, default_profile="STEP")
            max_cycle = s.params.get("cycle_time_multiplier", 1.0)
            max_variability = s.params.get("variability_multiplier", 1.0)
            bundle.cycle_time_multiplier *= 1.0 + frac * (max_cycle - 1.0)
            bundle.variability_multiplier *= 1.0 + frac * (max_variability - 1.0)
            bundle.active_scenario_ids.append(s.scenario_id)

            quality_weight = s.params.get("quality_weight_per_visit", 0.0)
            if quality_weight > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, quality_weight, "manual_variation")

        for s in self._active(sim_time, {ScenarioFamily.ENVIRONMENTAL_DRIFT}, station_id):
            ramp = s.params.get("ramp_duration_seconds", 3600.0)
            frac = s.elapsed_fraction(sim_time, ramp)
            max_sensor_shift = s.params.get("max_sensor_mean_shift", 0.0)
            deviation_threshold = s.params.get("deviation_threshold_fraction", 0.3)
            quality_weight = s.params.get("quality_weight_per_visit", 0.0)

            for sensor in s.affected_sensors:
                bundle.sensor_mean_shift[sensor] = bundle.sensor_mean_shift.get(sensor, 0.0) + frac * max_sensor_shift
            bundle.active_scenario_ids.append(s.scenario_id)

            excess = max(0.0, frac - deviation_threshold)
            if quality_weight > 0 and excess > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, excess * quality_weight, "environmental_drift")

        for s in self._active(sim_time, {ScenarioFamily.SENSOR_DROPOUT}, station_id):
            sensors = s.affected_sensors or ["__all__"]
            dropout_prob = s.params.get("dropout_probability", 1.0)
            for sensor in sensors:
                bundle.sensor_dropout_type[sensor] = s.dropout_type or "missing"
                bundle.sensor_dropout_probability[sensor] = dropout_prob
            bundle.active_scenario_ids.append(s.scenario_id)

        bundle.cycle_time_multiplier = min(bundle.cycle_time_multiplier, _MAX_MULTIPLIER)
        bundle.variability_multiplier = min(bundle.variability_multiplier, _MAX_MULTIPLIER)
        for sensor in bundle.sensor_noise_multiplier:
            bundle.sensor_noise_multiplier[sensor] = min(bundle.sensor_noise_multiplier[sensor], _MAX_MULTIPLIER)

        return bundle

    def check_batch_exposure(self, vehicle_id: str, sim_time: float, station_id: str, batch_id: str) -> None:
        """batch_id is already-assigned, already-observable (see
        material_batches.py) — this only decides whether it's latently
        marked bad, and if so records exposure. Never returns or creates
        an observable batch_id itself."""
        for s in self._active(sim_time, {ScenarioFamily.BAD_BATCH}, station_id):
            if s.affected_batch_id != batch_id:
                continue
            quality_weight = s.params.get("quality_weight_per_visit", 0.0)
            if quality_weight > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, quality_weight, "bad_batch")

    def get_variant_mix_override(self, sim_time: float) -> Optional[Dict[str, float]]:
        for s in self._active(sim_time, {ScenarioFamily.VEHICLE_MIX_OVERLOAD}):
            if s.variant_mix_override:
                return dict(s.variant_mix_override)
        return None

    def get_micro_stop_params(self, sim_time: float, station_id: str) -> Optional[dict]:
        for s in self._active(sim_time, {ScenarioFamily.MICRO_STOPS}, station_id):
            if "rate_per_processing_minute" in s.params:
                return {
                    "scenario_id": s.scenario_id,
                    "mode": "rate_process",
                    "rate_per_processing_minute": (
                        s.params["rate_per_processing_minute"]
                        * s.profile_fraction(sim_time, default_profile="STEP")
                    ),
                    "min_duration": s.params.get("min_duration_seconds", 3.0),
                    "max_duration": s.params.get("max_duration_seconds", 15.0),
                }
            return {
                "scenario_id": s.scenario_id,
                "mode": "legacy_per_visit",
                "probability": s.params.get("stop_probability", 0.0),
                "min_duration": s.params.get("min_duration_seconds", 5.0),
                "max_duration": s.params.get("max_duration_seconds", 30.0),
            }
        return None

    def get_arrival_headway_multiplier(self, sim_time: float) -> float:
        multiplier = 1.0
        for s in self._active(sim_time, {ScenarioFamily.ARRIVAL_BURST}):
            target = s.params.get("headway_multiplier", 1.0)
            fraction = s.profile_fraction(sim_time, default_profile="STEP_BURST")
            multiplier *= 1.0 - fraction * (1.0 - target)
        return max(0.40, min(1.0, multiplier))

    # ---- randomized, caller-supplies-the-stream ----

    def roll_random_quality_event(self, vehicle_id: str, sim_time: float, rng: random.Random) -> None:
        for s in self._active(sim_time, {ScenarioFamily.RANDOM_QUALITY_EVENT}):
            prob = s.params.get("per_vehicle_probability", 0.01)
            if rng.random() < prob:
                magnitude = rng.uniform(
                    s.params.get("min_magnitude", 0.02), s.params.get("max_magnitude", 0.1)
                )
                self._record_exposure(vehicle_id, sim_time, s, None, magnitude, "random_quality_event")

    def _record_exposure(self, vehicle_id, sim_time, scenario: ScenarioDefinition, station_id, contribution, reason):
        self.latent_log.record_exposure(
            QualityExposureRecord(
                vehicle_id=vehicle_id,
                simulation_time=sim_time,
                scenario_id=scenario.scenario_id,
                family=scenario.family.value,
                station_id=station_id,
                contribution=contribution,
                reason=reason,
            )
        )


def empty_manager() -> ScenarioManager:
    """A no-op manager: every query returns the identity/None. Used
    whenever a run has no scenarios configured, so station code never
    needs a None-check — it always has a manager to ask."""
    return ScenarioManager(scenarios=[], latent_log=LatentTruthLog())
