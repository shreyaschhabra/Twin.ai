"""
Per-shift scenario scheduling policy (Step 4, Sections N-P).

Design principles, directly from the instructions:
  - not every shift is abnormal;
  - abnormal shifts don't all start at the same time or use the same
    family/station/severity;
  - occasional overlapping scenarios are allowed, not engineered;
  - frequencies here are explicitly SIMULATION DESIGN ASSUMPTIONS chosen
    to produce enough positive examples for later model development,
    never claimed as real occurrence-rate statistics;
  - exactly one family can be configured as "held out" (Section P) so a
    later step can exclude it from supervised training — Step 4 only
    wires the configurability, it does not choose which family.

Scenario scheduling uses its OWN isolated RNG stream per shift
(`shift_schedule::{shift_id}`), completely separate from that shift's
simulation RNG (`shift_sim::{shift_id}`) — deciding "what happens" and
"how the factory stochastically behaves" must never share a stream, or
adding one more scenario family later would silently reshuffle every
shift's arrival/processing timing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from backend.simulation.rng import derive_seed
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily

# Illustrative simulation design assumptions (Section O) — not production
# occurrence-frequency statistics.
PROBABILITY_SHIFT_IS_ABNORMAL = 0.55
N_SCENARIOS_WHEN_ABNORMAL = [1, 1, 2, 2, 3]  # weighted toward 1-2 per abnormal shift
RANDOM_QUALITY_EVENT_ALWAYS_ON_PROBABILITY = 0.015  # background risk present every shift

# Final Step-4 patch: RANDOM_QUALITY_EVENT's per-event magnitude range.
# Empirically tested against the recalibrated QC sigmoid (background=0.0088,
# max=0.8, midpoint=0.0445, steepness=110) — this range maps to individual
# probabilities of ~2.3%-9.2% (mean exposure 0.0165 -> ~4.8% average
# conditional probability), landing "low-single-digit to low-teens" as
# intended. The original (0.02, 0.08) range straddled the sigmoid's steep
# region and mapped to a ~47% average conditional probability — a
# coin-flip-strength hidden failure mode, not the "rare, weak,
# mostly-unobservable" disturbance this family is meant to represent.
RANDOM_QUALITY_EVENT_MIN_MAGNITUDE = 0.008
RANDOM_QUALITY_EVENT_MAX_MAGNITUDE = 0.025

# Which stations are plausible targets for each family on the full line.
# Kept small and specific rather than "any station" so scenario placement
# stays operationally sensible (e.g. degradation only on automated
# equipment, manual variation only on manual stations).
FAMILY_STATION_POOLS: Dict[ScenarioFamily, List[str]] = {
    ScenarioFamily.EQUIPMENT_DEGRADATION: ["S01", "S02", "S03", "S09", "S10", "S27", "S28", "S26"],
    ScenarioFamily.MICRO_STOPS: ["S06", "S07", "S23", "S26", "S31"],
    ScenarioFamily.ENVIRONMENTAL_DRIFT: ["S13", "S14", "S17", "S18", "S19", "S20"],
    ScenarioFamily.SENSOR_DROPOUT: ["S04", "S08", "S12", "S31", "S39"],
    ScenarioFamily.MANUAL_VARIATION: ["S11", "S21", "S22", "S24", "S33", "S34", "S38"],
    ScenarioFamily.BAD_BATCH: ["S05", "S16", "S25", "S27", "S32"],
}
# Families that don't target a specific station
LINE_LEVEL_FAMILIES = [ScenarioFamily.VEHICLE_MIX_OVERLOAD]

# Fixed, explicit draw order for "which family gets scheduled". Must NOT
# be derived from a set or dict-keys union at call time: ScenarioFamily is
# a str Enum, and Python randomizes string hashing per-process by default
# (PYTHONHASHSEED), so `dict.keys() | some_set` silently produces a
# DIFFERENT iteration order on every fresh process invocation — this was
# caught by hand (three consecutive runs of the same seeded dataset
# produced three different defect rates) before it could corrupt the
# frozen dataset. schedule_rng.choice() indexes into this list, so the
# list's own order must be as deterministic as the RNG draw is.
AVAILABLE_FAMILIES_ORDER: List[ScenarioFamily] = list(FAMILY_STATION_POOLS.keys()) + LINE_LEVEL_FAMILIES

BATCH_COHORT_SIZES = {"S05": 6, "S16": 6, "S25": 5, "S27": 10, "S32": 12}

SENSOR_FOR_STATION = {
    "S01": "weld_current", "S02": "weld_current", "S03": "weld_current",
    "S09": "weld_current", "S10": "weld_current",
    "S27": "torque_value", "S28": "torque_value", "S26": "force_sensor",
    "S13": "booth_temperature", "S14": "booth_temperature", "S17": "booth_temperature",
    "S18": "booth_temperature", "S19": "booth_temperature", "S20": "oven_temperature",
    "S04": "laser_scan", "S08": "laser_scan", "S12": "laser_scan",
    "S31": "position_sensor", "S39": "laser_scan",
}


@dataclass
class ShiftScenarioPlan:
    shift_id: str
    scenarios: List[ScenarioDefinition]


def build_shift_schedule(
    dataset_master_seed: int,
    shift_id: str,
    shift_duration_seconds: float,
    mean_interarrival_seconds: float,
    held_out_family: Optional[ScenarioFamily] = None,
) -> ShiftScenarioPlan:
    schedule_rng = random.Random(derive_seed(dataset_master_seed, f"shift_schedule::{shift_id}"))

    scenarios: List[ScenarioDefinition] = []
    scenario_counter = 0

    def next_id(family: ScenarioFamily) -> str:
        nonlocal scenario_counter
        scenario_counter += 1
        return f"{shift_id}::{family.value.lower()}::{scenario_counter}"

    # Background rare-quality-event scenario: present every shift at low
    # probability, healthy or not — this isn't what makes a shift "abnormal".
    scenarios.append(
        ScenarioDefinition(
            scenario_id=next_id(ScenarioFamily.RANDOM_QUALITY_EVENT),
            family=ScenarioFamily.RANDOM_QUALITY_EVENT,
            start_time=0, duration=None, severity=0.2,
            params={
                "per_vehicle_probability": RANDOM_QUALITY_EVENT_ALWAYS_ON_PROBABILITY,
                "min_magnitude": RANDOM_QUALITY_EVENT_MIN_MAGNITUDE,
                "max_magnitude": RANDOM_QUALITY_EVENT_MAX_MAGNITUDE,
            },
        )
    )

    is_abnormal = schedule_rng.random() < PROBABILITY_SHIFT_IS_ABNORMAL
    if not is_abnormal:
        return ShiftScenarioPlan(shift_id=shift_id, scenarios=scenarios)

    available_families = [f for f in AVAILABLE_FAMILIES_ORDER if f != held_out_family]
    n_scenarios = schedule_rng.choice(N_SCENARIOS_WHEN_ABNORMAL)

    for _ in range(n_scenarios):
        family = schedule_rng.choice(available_families)
        severity = schedule_rng.uniform(0.3, 0.9)
        start_time = schedule_rng.uniform(0.05, 0.65) * shift_duration_seconds
        duration = schedule_rng.uniform(0.15, 0.45) * shift_duration_seconds

        if family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
            scenarios.append(_build_mix_overload(next_id(family), start_time, duration, severity, schedule_rng))
        elif family == ScenarioFamily.BAD_BATCH:
            scenarios.append(_build_bad_batch(
                next_id(family), start_time, severity, schedule_rng, mean_interarrival_seconds
            ))
        else:
            station = schedule_rng.choice(FAMILY_STATION_POOLS[family])
            scenarios.append(_build_station_scenario(
                next_id(family), family, station, start_time, duration, severity, schedule_rng
            ))

    return ShiftScenarioPlan(shift_id=shift_id, scenarios=scenarios)


def _build_mix_overload(scenario_id, start_time, duration, severity, rng) -> ScenarioDefinition:
    suv_share = 0.35 + severity * 0.45  # up to ~80% SUV-heavy
    remaining = 1.0 - suv_share
    sedan_share = remaining * rng.uniform(0.5, 0.7)
    ev_share = remaining - sedan_share
    return ScenarioDefinition(
        scenario_id=scenario_id, family=ScenarioFamily.VEHICLE_MIX_OVERLOAD,
        start_time=start_time, duration=duration, severity=severity,
        variant_mix_override={"ICE_SEDAN": sedan_share, "ICE_SUV": suv_share, "EV": ev_share},
    )


def _build_bad_batch(scenario_id, start_time, severity, rng, mean_interarrival_seconds) -> ScenarioDefinition:
    station = rng.choice(list(BATCH_COHORT_SIZES.keys()))
    cohort_size = BATCH_COHORT_SIZES[station]
    # Approximate which batch will be at this station around start_time,
    # given roughly-uniform arrivals: vehicle index -> batch number.
    approx_vehicle_index = max(0, start_time / mean_interarrival_seconds)
    batch_number = 1001 + int(approx_vehicle_index // cohort_size)
    return ScenarioDefinition(
        scenario_id=scenario_id, family=ScenarioFamily.BAD_BATCH,
        station_ids=[station], start_time=0, duration=None, severity=severity,
        affected_batch_id=f"B{batch_number}",
        params={"quality_weight_per_visit": 0.08 + severity * 0.2},
    )


def _build_station_scenario(scenario_id, family, station, start_time, duration, severity, rng) -> ScenarioDefinition:
    if family == ScenarioFamily.EQUIPMENT_DEGRADATION:
        sensor = SENSOR_FOR_STATION.get(station)
        return ScenarioDefinition(
            scenario_id=scenario_id, family=family, station_ids=[station],
            start_time=start_time, duration=duration, severity=severity,
            affected_sensors=[sensor] if sensor else [],
            params={
                "ramp_duration_seconds": duration,
                "max_cycle_time_multiplier": 1.2 + severity * 0.8,
                "max_noise_multiplier": 1.5 + severity * 1.5,
                "max_sensor_mean_shift": -(400 + severity * 800),
                # Final Step-4 patch: modestly strengthened (0.01+sev*0.03 ->
                # 0.02+sev*0.05) to compensate for weakening
                # RANDOM_QUALITY_EVENT, which otherwise dropped the overall
                # defect rate below the 3.5% floor. EQUIPMENT_DEGRADATION was
                # chosen (along with MANUAL_VARIATION) because it already had
                # a large exposed population (659 vehicles) but a weak
                # conditional rate (~4.5%), i.e. room to carry more signal
                # without approaching determinism.
                "quality_weight_per_visit": 0.02 + severity * 0.05,
            },
        )
    if family == ScenarioFamily.MICRO_STOPS:
        return ScenarioDefinition(
            scenario_id=scenario_id, family=family, station_ids=[station],
            start_time=start_time, duration=duration, severity=severity,
            params={
                "stop_probability": 0.15 + severity * 0.45,
                "min_duration_seconds": 8, "max_duration_seconds": 15 + severity * 45,
            },
        )
    if family == ScenarioFamily.ENVIRONMENTAL_DRIFT:
        sensor = SENSOR_FOR_STATION.get(station)
        return ScenarioDefinition(
            scenario_id=scenario_id, family=family, station_ids=[station],
            start_time=start_time, duration=duration, severity=severity,
            affected_sensors=[sensor] if sensor else [],
            params={
                "ramp_duration_seconds": duration,
                "max_sensor_mean_shift": 4 + severity * 10,
                "deviation_threshold_fraction": 0.35,
                "quality_weight_per_visit": 0.05 + severity * 0.15,
            },
        )
    if family == ScenarioFamily.SENSOR_DROPOUT:
        sensor = SENSOR_FOR_STATION.get(station)
        dropout_type = rng.choice(["missing", "missing", "stuck", "noisy"])
        return ScenarioDefinition(
            scenario_id=scenario_id, family=family, station_ids=[station],
            start_time=start_time, duration=duration, severity=severity,
            affected_sensors=[sensor] if sensor else [],
            dropout_type=dropout_type,
            params={"dropout_probability": 0.3 + severity * 0.6},
        )
    if family == ScenarioFamily.MANUAL_VARIATION:
        return ScenarioDefinition(
            scenario_id=scenario_id, family=family, station_ids=[station],
            start_time=start_time, duration=duration, severity=severity,
            params={
                "cycle_time_multiplier": 1.15 + severity * 0.5,
                "variability_multiplier": 1.5 + severity * 2.0,
                # Same rationale as EQUIPMENT_DEGRADATION above, but a much
                # smaller bump: a first attempt at 0.02+sev*0.04 (2x) alone
                # pushed MANUAL_VARIATION's conditional rate from 5.3% to
                # 36.9% and the overall rate to 4.9%, overshooting both —
                # dialed back to a modest ~25% increase instead.
                "quality_weight_per_visit": 0.012 + severity * 0.025,
            },
        )
    raise ValueError(f"no scenario builder for family {family}")
