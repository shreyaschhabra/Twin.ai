"""
Coverage-balanced Flow enrichment scheduler (Decision 36, Dataset B).

This module NEVER touches scenario effect equations. It reuses the exact
builder functions from backend.historical.shift_scheduler
(`_build_station_scenario`, `_build_mix_overload`) — the same code that
already computes cycle_time_multiplier, stop_probability, etc. from a
severity value. All this module changes is WHICH shifts get a
Flow-capable scenario opportunity, at WHICH station, at WHAT severity
stratum — i.e. the scheduling POLICY, not the physics.

Pipeline boundary (Section 21), enforced by construction:

    build_flow_enrichment_plan(seed, n_shifts)   <- pure function of
        |                                           (seed, n_shifts) and
        |                                           static config-derived
        |                                           candidate tables below.
        v                                           Never touches events,
    flow_enriched_schedule.json (frozen)             labels, or scenario
        |                                             outcomes.
        v
    build_shift_schedule_enriched(shift_id, ...)  <- turns one shift's
        |                                           frozen opportunities
        |                                           into ScenarioDefinitions
        v                                           (deterministic, no
    SimPy simulation                                 new RNG decisions
        |                                             about WHAT happens).
        v
    observable events -> Flow labels (downstream, unaffected by this module)

SECTION 8 — CANDIDATE STATION SELECTION (done BEFORE looking at any Flow
label/outcome from this dataset; based only on the static, already-frozen
factory config in configs/full_line.yaml):

For each station, "bottleneck-proneness" was read off two static
properties: (a) baseline_cycle_time_seconds relative to the immediately
preceding station on the shared route (a large ratio means the station is
a natural pace-setter that the line backs up behind), and (b) the
capacity of the buffer feeding it (small capacity means backpressure
propagates upstream fast once the station falls behind). Sensor maturity,
configured cycle_time_variability, and variant_overrides were used to
decide which MECHANISM (manual variation vs. micro-stop vs. mix-driven
load) is physically plausible at that station — never to decide station
identity was chosen for label-distribution reasons.

    S11 (Body Finishing / Manual Inspection, zone body_joining):
        baseline 65s vs. upstream S10's 44s (1.48x); MANUAL_ASSEMBLY,
        cycle_time_variability=0.22 (among the highest on the line),
        sensor_maturity=poor. A manual station whose pace is inherently
        susceptible to real operator-driven slowdowns -> MANUAL_VARIATION.

    S07 (Closure Panel Fitting, zone body_joining):
        baseline 48s vs. upstream S06's 30s (1.60x); ROBOTIC_HANDLING_
        ASSEMBLY described in config notes as an "older robotic cell";
        sensor_maturity=partial (no force-sensor retrofit). A legacy
        automated cell where intermittent stoppage is physically
        plausible -> MICRO_STOPS.

    S20 (Paint Cure + Paint Inspection, zone paint_surface):
        baseline 66s vs. upstream S19's 48s (1.375x); the paint zone's
        highest cycle time and its exit gate; CURING_ENVIRONMENTAL, whose
        station-type template lists belt_speed_drift as a plausible
        degradation mode -- i.e. a conveyor/oven asset that already
        acknowledges mechanical intermittency; small feeding buffer B19
        (capacity 4). The only physically plausible enrichment mechanism
        for an automated cure/conveyor asset is MICRO_STOPS -- it is not a
        manual station, and EQUIPMENT_DEGRADATION remains held out.

    S22 (Wiring Harness Installation, zone final_assembly):
        baseline 88s -- the single slowest station on the entire 45-station
        line; cycle_time_variability=0.24 (the line's highest);
        sensor_maturity=poor; small feeding buffer B21 (capacity 4); also
        the one MANUAL_ASSEMBLY station with an explicit EV cycle-time
        multiplier (1.15x, vehicle_variants.EV.processing_time_modifiers)
        -> MANUAL_VARIATION, and also the station most likely to be
        stressed by a VEHICLE_MIX_OVERLOAD instance even though that
        family targets no specific station (see note below).

    S24 (HVAC / Interior Module Installation, zone final_assembly):
        baseline 75s vs. upstream S23's 40s (1.875x); MANUAL_ASSEMBLY,
        cycle_time_variability=0.20, sensor_maturity=poor, small feeding
        buffer B23 (capacity 4) -> MANUAL_VARIATION.

    S26 (Powertrain / Battery Pack Marriage, zone final_assembly):
        baseline 72s vs. upstream S25's 36s (2.0x); ROBOTIC_HANDLING_
        ASSEMBLY performing a high-force insertion (target_insertion_
        force_n=1850) -- a physically plausible site for a robotic
        micro-stop; ALSO the station with the line's largest documented
        variant_overrides cycle-time spread (EV 1.20x, ICE_SUV 1.10x vs.
        ICE_SEDAN baseline) -> MICRO_STOPS as a station-scoped mechanism,
        and the primary station a line-level VEHICLE_MIX_OVERLOAD
        instance is mechanistically expected to stress.

    S33 (Door / Closure Finishing, zone final_assembly):
        baseline 58s vs. upstream S32's 16s (3.6x, the sharpest cycle-time
        cliff on the line); MANUAL_ASSEMBLY, cycle_time_variability=0.20,
        sensor_maturity=poor -> MANUAL_VARIATION.

    S34 (Electrical Connection / System Check, zone final_assembly):
        baseline 68s vs. upstream S33's 58s (1.17x, on top of S33's own
        cliff -- two slow manual stations back to back); MANUAL_ASSEMBLY,
        cycle_time_variability=0.16, sensor_maturity=partial ->
        MANUAL_VARIATION.

No TORQUE_FASTENING station was selected (Section 8's "one fastening ...
if appropriate" is explicitly conditional): every TORQUE_FASTENING
station's baseline cycle time is well BELOW its upstream neighbor's
(S27/S26=0.31x, S28/S27=1.18x, S30/S29=0.33x, S32/S31=0.80x) and their
configured variability is low (0.08-0.10) -- none is a config-plausible
pace-setter, so none was forced in. S26 (a marriage station) and S07 (a
"moderately loaded automated process") already satisfy that soft
requirement.

VEHICLE_MIX_OVERLOAD remains a LINE-LEVEL family exactly as in
shift_scheduler.py (it overrides the whole line's incoming variant mix,
not one station's parameters) -- this module schedules it as a
line-level opportunity with no station_id, consistent with its existing
semantics; S22 and S26 are documented above only as the stations it is
mechanistically expected to stress, not as targets the scenario itself
carries.

SECTION 9 — COMPATIBILITY MAP is exactly STATION_CANDIDATES below:
MANUAL_VARIATION only at MANUAL_ASSEMBLY stations; MICRO_STOPS only at
automated/robotic or legacy-mechanical stations; VEHICLE_MIX_OVERLOAD is
line-level and carries no station compatibility constraint.

SECTION 10 — SEVERITY STRATA were derived mechanistically from the
EXISTING effect equations in shift_scheduler.py's _build_station_scenario
/ _build_mix_overload (unchanged), by inspecting how each equation maps
severity in [0,1] to its physical parameter, BEFORE generating or
inspecting any Dataset-B outcome:

    MANUAL_VARIATION cycle_time_multiplier = 1.15 + severity*0.5
    MICRO_STOPS       stop_probability      = 0.15 + severity*0.45
    VEHICLE_MIX_OVERLOAD suv_share           = 0.35 + severity*0.45

Strata boundaries [0.15, 0.35, 0.65, 0.95] were chosen as a simple
tercile-like split of the effect equations' usable domain, avoiding the
bottom decile (severity<0.15 barely perturbs any equation above) and the
top of the range (severity>0.95, to avoid degenerate maxima) -- not
chosen to hit any target positive-label count in this dataset, since no
Dataset-B label has been computed at the time these boundaries were
fixed.

    MILD:     severity in [0.15, 0.35) -> e.g. MANUAL_VARIATION multiplier
              in [1.1925, 1.2275); MICRO_STOPS stop_probability in
              [0.2175, 0.3075); mix suv_share in [0.4175, 0.5075).
    MODERATE: severity in [0.35, 0.65) -> multiplier in [1.3275, 1.475);
              stop_probability in [0.3075, 0.4425); suv_share in
              [0.5075, 0.6425).
    SEVERE:   severity in [0.65, 0.95] -> multiplier in [1.4475, 1.625];
              stop_probability in [0.4425, 0.5775]; suv_share in
              [0.6425, 0.7775].

Section 11 is enforced structurally: nothing in this module ever reads a
bottleneck outcome, a buffer occupancy, or a label to decide anything.
Every field below is a deterministic function of (dataset_master_seed,
n_shifts) alone.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from backend.historical.shift_scheduler import (
    FAMILY_STATION_POOLS,
    _build_mix_overload,
    _build_station_scenario,
    build_shift_schedule,
)
from backend.simulation.rng import derive_seed
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily

# ---- Section 9: explicit scenario-family / station compatibility map ----
# (rationale for each entry is documented in the module docstring above)
STATION_CANDIDATES: Dict[str, dict] = {
    "S11": {"zone": "body_joining", "family": ScenarioFamily.MANUAL_VARIATION},
    "S07": {"zone": "body_joining", "family": ScenarioFamily.MICRO_STOPS},
    "S20": {"zone": "paint_surface", "family": ScenarioFamily.MICRO_STOPS},
    "S22": {"zone": "final_assembly", "family": ScenarioFamily.MANUAL_VARIATION},
    "S24": {"zone": "final_assembly", "family": ScenarioFamily.MANUAL_VARIATION},
    "S26": {"zone": "final_assembly", "family": ScenarioFamily.MICRO_STOPS},
    "S33": {"zone": "final_assembly", "family": ScenarioFamily.MANUAL_VARIATION},
    "S34": {"zone": "final_assembly", "family": ScenarioFamily.MANUAL_VARIATION},
}
# Stations mechanistically expected to be stressed by a line-level
# VEHICLE_MIX_OVERLOAD instance (documentation only -- the scenario itself
# carries no station_id, matching shift_scheduler.py's existing semantics).
MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS = ["S22", "S26", "S36"]

KNOWN_FLOW_FAMILIES = [
    ScenarioFamily.MANUAL_VARIATION,
    ScenarioFamily.MICRO_STOPS,
    ScenarioFamily.VEHICLE_MIX_OVERLOAD,
]
FAMILY_OPPORTUNITY_WEIGHTS = {
    ScenarioFamily.MANUAL_VARIATION: 0.40,
    ScenarioFamily.MICRO_STOPS: 0.35,
    ScenarioFamily.VEHICLE_MIX_OVERLOAD: 0.25,
}

# Section 10 (see module docstring for derivation)
SEVERITY_STRATA = {
    "MILD": (0.15, 0.35),
    "MODERATE": (0.35, 0.65),
    "SEVERE": (0.65, 0.95),
}
SEVERITY_STRATUM_WEIGHTS = {"MILD": 0.35, "MODERATE": 0.35, "SEVERE": 0.30}

# Section 12: opportunity-coverage targets (shift counts, NOT positive-label
# quotas), drawn per locked partition.
FLOW_OPPORTUNITY_RANGE = {"train": (18, 22), "validation": (4, 5), "test": (4, 5)}
# Section 19: guaranteed EQUIPMENT_DEGRADATION opportunities on top of
# whatever the unchanged background scheduler already produces, spread
# across the timeline (not counted toward any Flow viability gate).
DEGRADATION_OPPORTUNITY_COUNT = {"train": 6, "validation": 2, "test": 2}
# Same numeric severity range as the existing background scheduler
# (shift_scheduler.PROBABILITY_SHIFT_IS_ABNORMAL branch) -- deliberately
# NOT stratified, since EQUIPMENT_DEGRADATION's effect equations and
# severity distribution must stay exactly as in Dataset A.
DEGRADATION_SEVERITY_RANGE = (0.3, 0.9)

START_TIME_FRACTION_RANGE = (0.05, 0.65)
DURATION_FRACTION_RANGE = (0.15, 0.45)


@dataclass
class EnrichmentOpportunity:
    shift_id: str
    partition: str  # "train" | "validation" | "test"
    kind: str  # "known_flow_enrichment" | "unseen_degradation_opportunity"
    family: str  # ScenarioFamily.value
    station_id: Optional[str]
    severity_stratum: Optional[str]
    severity: float
    start_time_fraction: float
    duration_fraction: float


def _shift_id(i: int) -> str:
    return f"SHIFT{i:03d}"


def _partition_shift_ids() -> Dict[str, List[str]]:
    # Locked boundaries (Decision 34/36, Section 4) -- imported nowhere
    # from backend.flow to keep this module free of any dependency on
    # Flow label/event code; the numbers are simply restated here and
    # cross-checked against backend.flow.split by a dedicated test.
    return {
        "train": [_shift_id(i) for i in range(1, 71)],
        "validation": [_shift_id(i) for i in range(71, 86)],
        "test": [_shift_id(i) for i in range(86, 101)],
    }


def _thirds(items: List[str]) -> List[List[str]]:
    n = len(items)
    a, b = n // 3, 2 * n // 3
    return [items[:a], items[a:b], items[b:]]


def _spread_sample(rng: random.Random, items: List[str], k: int) -> List[str]:
    """Pick k items spread across early/mid/late thirds of `items`
    (Section 13), without replacement."""
    k = min(k, len(items))
    parts = _thirds(items)
    counts = [k // 3] * 3
    for i in range(k - sum(counts)):
        counts[i] += 1
    chosen: List[str] = []
    for part, c in zip(parts, counts):
        c = min(c, len(part))
        chosen.extend(rng.sample(part, c))
    # top up from the whole partition if a third ran short
    remaining = [x for x in items if x not in chosen]
    while len(chosen) < k and remaining:
        pick = rng.choice(remaining)
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


def _draw_severity(rng: random.Random, stratum: str) -> float:
    lo, hi = SEVERITY_STRATA[stratum]
    return lo + rng.random() * (hi - lo)


def build_flow_enrichment_plan(dataset_master_seed: int, n_shifts: int = 100) -> List[EnrichmentOpportunity]:
    """Pure function of (dataset_master_seed, n_shifts) plus the static
    tables above. Reads no events, labels, or simulation output -- see
    tests/test_flow_enrichment_schedule.py::test_plan_has_no_flow_label_dependency."""
    if n_shifts != 100:
        raise ValueError("the locked 70/15/15 partition assumes exactly 100 shifts")

    plan_rng = random.Random(derive_seed(dataset_master_seed, "flow_enrichment_plan"))
    partitions = _partition_shift_ids()

    opportunities: List[EnrichmentOpportunity] = []

    # ---- Section 12/13/14/15: known Flow-capable opportunities ----
    for partition_name in ["train", "validation", "test"]:
        low, high = FLOW_OPPORTUNITY_RANGE[partition_name]
        count = plan_rng.randint(low, high)
        chosen_shifts = _spread_sample(plan_rng, partitions[partition_name], count)
        for shift_id in chosen_shifts:
            family = plan_rng.choices(
                KNOWN_FLOW_FAMILIES,
                weights=[FAMILY_OPPORTUNITY_WEIGHTS[f] for f in KNOWN_FLOW_FAMILIES],
                k=1,
            )[0]
            stratum = plan_rng.choices(
                list(SEVERITY_STRATUM_WEIGHTS), weights=list(SEVERITY_STRATUM_WEIGHTS.values()), k=1
            )[0]
            severity = _draw_severity(plan_rng, stratum)
            start_frac = plan_rng.uniform(*START_TIME_FRACTION_RANGE)
            dur_frac = plan_rng.uniform(*DURATION_FRACTION_RANGE)

            if family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
                station_id = None
            else:
                candidates = [s for s, info in STATION_CANDIDATES.items() if info["family"] == family]
                station_id = plan_rng.choice(candidates)

            opportunities.append(EnrichmentOpportunity(
                shift_id=shift_id, partition=partition_name, kind="known_flow_enrichment",
                family=family.value, station_id=station_id, severity_stratum=stratum,
                severity=severity, start_time_fraction=start_frac, duration_fraction=dur_frac,
            ))

    # ---- Section 19: guaranteed EQUIPMENT_DEGRADATION opportunities ----
    degradation_pool = FAMILY_STATION_POOLS[ScenarioFamily.EQUIPMENT_DEGRADATION]
    for partition_name in ["train", "validation", "test"]:
        count = DEGRADATION_OPPORTUNITY_COUNT[partition_name]
        chosen_shifts = _spread_sample(plan_rng, partitions[partition_name], count)
        for shift_id in chosen_shifts:
            station_id = plan_rng.choice(degradation_pool)
            severity = plan_rng.uniform(*DEGRADATION_SEVERITY_RANGE)
            start_frac = plan_rng.uniform(*START_TIME_FRACTION_RANGE)
            dur_frac = plan_rng.uniform(*DURATION_FRACTION_RANGE)
            opportunities.append(EnrichmentOpportunity(
                shift_id=shift_id, partition=partition_name, kind="unseen_degradation_opportunity",
                family=ScenarioFamily.EQUIPMENT_DEGRADATION.value, station_id=station_id,
                severity_stratum=None, severity=severity, start_time_fraction=start_frac,
                duration_fraction=dur_frac,
            ))

    return opportunities


def plan_by_shift(plan: List[EnrichmentOpportunity]) -> Dict[str, List[EnrichmentOpportunity]]:
    out: Dict[str, List[EnrichmentOpportunity]] = {}
    for opp in plan:
        out.setdefault(opp.shift_id, []).append(opp)
    return out


def save_plan(plan: List[EnrichmentOpportunity], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump([asdict(o) for o in plan], f, indent=2)


def _opportunity_to_scenario(opp: EnrichmentOpportunity, shift_id: str, shift_duration_seconds: float,
                              scenario_id: str, rng: random.Random) -> ScenarioDefinition:
    """Translates one frozen opportunity into a ScenarioDefinition using
    the UNCHANGED builder functions from shift_scheduler.py -- this
    function makes no decision about effect magnitude itself, only reads
    already-frozen plan fields."""
    start_time = opp.start_time_fraction * shift_duration_seconds
    duration = opp.duration_fraction * shift_duration_seconds
    family = ScenarioFamily(opp.family)

    if family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
        return _build_mix_overload(scenario_id, start_time, duration, opp.severity, rng)
    return _build_station_scenario(scenario_id, family, opp.station_id, start_time, duration, opp.severity, rng)


def build_shift_schedule_enriched(
    dataset_master_seed: int,
    shift_id: str,
    shift_duration_seconds: float,
    mean_interarrival_seconds: float,
    plan_by_shift: Dict[str, List[EnrichmentOpportunity]],
    held_out_family=None,
):
    """Baseline (identical to Dataset A's build_shift_schedule, same RNG
    stream, same call) PLUS the frozen enrichment opportunities for this
    shift appended on top. Never mutates or reorders the baseline
    scenarios -- see
    tests/test_flow_enrichment_schedule.py::test_enriched_schedule_is_additive_only."""
    baseline = build_shift_schedule(
        dataset_master_seed=dataset_master_seed,
        shift_id=shift_id,
        shift_duration_seconds=shift_duration_seconds,
        mean_interarrival_seconds=mean_interarrival_seconds,
        held_out_family=held_out_family,
    )

    opportunities = plan_by_shift.get(shift_id, [])
    if not opportunities:
        return baseline

    apply_rng = random.Random(derive_seed(dataset_master_seed, f"flow_enrichment_apply::{shift_id}"))
    scenarios = list(baseline.scenarios)
    for i, opp in enumerate(opportunities):
        scenario_id = f"{shift_id}::flow_enrich::{opp.kind}::{i}"
        scenarios.append(_opportunity_to_scenario(opp, shift_id, shift_duration_seconds, scenario_id, apply_rng))

    baseline.scenarios = scenarios
    return baseline
