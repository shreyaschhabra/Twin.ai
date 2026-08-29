"""
Coverage-balanced Flow enrichment scheduler (Decision 36, Dataset B;
Decision 37, Dataset C mechanistic calibration).

This module NEVER touches MANUAL_VARIATION's or EQUIPMENT_DEGRADATION's
effect equations, and reuses shift_scheduler.py's `_build_mix_overload`
verbatim for VEHICLE_MIX_OVERLOAD. The ONE exception, introduced in
Decision 37 after a capacity-margin audit proved it mechanically
necessary, is a locally-scoped, recalibrated MICRO_STOPS builder
(`_build_recalibrated_micro_stops`) used ONLY by this enrichment path —
shift_scheduler.py's own MICRO_STOPS branch (used by the unchanged
background scheduler in every shift, including Datasets A and B) is left
completely untouched, so neither existing dataset's reproducibility from
a future commit is affected.

Pipeline boundary, enforced by construction:

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

===========================================================================
DECISION 37 -- CAPACITY-MARGIN AUDIT (done BEFORE Dataset C exists, using
only configs/full_line.yaml, the DEFAULT_VARIANT_MIX, DEFAULT_MEAN_
INTERARRIVAL_SECONDS=115s, and the existing scenario effect equations)
===========================================================================

Model: a single-file serial line with buffers behaves, in steady state,
as a tandem queue where every station sees the SAME long-run average
arrival rate as the line's overall vehicle-release rate
(1 / mean_interarrival_seconds = 1/115 veh/s) -- this is flow
conservation along a lossless tandem queue, not an assumption specific to
any one station. A station's healthy utilization is therefore

    rho_healthy = mix_weighted_mean_cycle_time / mean_interarrival_seconds

where mix_weighted_mean_cycle_time accounts for each station's own
variant_overrides / processing_time_modifiers under DEFAULT_VARIANT_MIX
(45% ICE_SEDAN / 35% ICE_SUV / 20% EV). The multiplier needed to push a
station to rho=1 (the breakeven point past which its inbound buffer
starts filling on average) is

    breakeven_multiplier = mean_interarrival_seconds / mix_weighted_mean_cycle_time

Computed for the original 8 Dataset-B candidates plus S21 (added below
after the audit revealed it, not chosen a priori):

    station  type                      mix_mean(s)  rho_healthy  breakeven_mult  buffer(cap)
    S11      MANUAL_ASSEMBLY           65.00        0.565        1.769           B10 (4)
    S07      ROBOTIC_HANDLING_ASSEMBLY 48.00        0.417        2.396           B06 (4)
    S20      CURING_ENVIRONMENTAL      66.00        0.574        1.742           B19 (4)
    S21      MANUAL_ASSEMBLY           70.00        0.609        1.643           B20 (5)
    S22      MANUAL_ASSEMBLY           90.64        0.788        1.269           B21 (4)
    S24      MANUAL_ASSEMBLY           75.00        0.652        1.533           B23 (4)
    S26      ROBOTIC_HANDLING_ASSEMBLY 77.40        0.673        1.486           B25 (4)
    S33      MANUAL_ASSEMBLY           58.00        0.504        1.983           B32 (4)
    S34      MANUAL_ASSEMBLY           68.00        0.591        1.691           B33 (4)

MANUAL_VARIATION eligibility (equation UNCHANGED per Decision 37 Section
8: cycle_time_multiplier = 1.15 + 0.5*severity, max at severity=0.95 is
1.625): a station is mechanically CAPABLE only if 1.625 >= its
breakeven_multiplier.

    S22: breakeven 1.269, margin +0.356  -> CAPABLE (comfortably)
    S24: breakeven 1.533, margin +0.092  -> capable only at the extreme
         top of SEVERE; Dataset B's own station breakdown (17 of 574
         impact events at S24) is consistent with "rare, not reliable".
    S21: breakeven 1.643, margin -0.018  -> NOT capable in mean terms,
         but the margin is tiny, and S21 was ALREADY in shift_scheduler's
         background MANUAL_VARIATION pool (not Decision-36's enrichment
         candidate list) -- across Datasets A and B combined it is
         empirically the single largest real contributor of blocking
         (114/574 events in A, 647/1464 in B), via the UNCHANGED
         background scheduler alone. The mean-utilization breakeven is a
         first-order approximation; MANUAL_VARIATION's variability_
         multiplier (1.5 + 2.0*severity, up to 3.35x noise) inflates
         processing-time VARIANCE as well as its mean, and with a small
         buffer (capacity 5) a high-variance server can produce real,
         repeated blocking even when its MEAN utilization sits just
         below breakeven -- exactly the mechanism that already explains
         S21's outsized empirical share in both prior, unmodified
         datasets. S21 is added to the MANUAL_VARIATION candidate list on
         this basis (a config+math-derived hypothesis, CONFIRMED by
         already-existing Dataset A/B evidence -- not a Dataset-C label).
    S11, S33, S34: margins -0.144 / -0.358 / -0.066 -> NOT capable, and
         each shows negligible impact-event counts in Datasets A/B.
         DROPPED from the MANUAL_VARIATION candidate list.

    REVISED MANUAL_VARIATION CANDIDATES: {S21, S22} (both final_assembly).
    S24 is deliberately excluded despite a nominally positive margin: at
    only 0.092 above breakeven it produces a negligible conversion rate
    in practice (consistent with Dataset B) and would mostly just add
    opportunity-count noise, not real coverage.

VEHICLE_MIX_OVERLOAD feasibility (Decision 37 Section 5, using the
EXISTING variant multipliers, no changes):

    station  base(s)  multipliers                        100%-slowest mean(s)  rho   breakeven_mult  max_available_mult
    S22      88       SEDAN 1.00 / SUV 1.00 / EV 1.15     101.2                 0.880 1.307           1.15  -> NOT CAPABLE
    S26      72       SEDAN 1.00 / SUV 1.10 / EV 1.20     86.4                  0.751 1.597           1.20  -> NOT CAPABLE
    S36      42       SEDAN 1.00 / SUV 1.05 / EV 1.15     48.3                  0.420 2.738           1.15  -> NOT CAPABLE

Even 100% concentration of the slowest variant (EV, everywhere) leaves
every mix-sensitive station well under its own breakeven multiplier -- by
a wide margin at every station tested. VEHICLE_MIX_OVERLOAD, using the
existing variant-multiplier design, is therefore classified per Decision
37 Section 7 as a CONTEXTUAL HARD-NEGATIVE scenario: it changes real
operating context (arrival composition) but cannot, by itself, physically
create a bottleneck in this factory configuration. It stays in the
corpus for exactly that reason -- "unusual mix without blocking" is a
useful negative example against false alarms -- but its opportunities are
marked `expected_bottleneck_capable=False` and are not counted toward the
family's blocking-capable coverage.

MICRO_STOPS mechanics (Decision 37 Section 2) -- the additive channel is
in backend/simulation/station.py `_maybe_run_micro_stop`:
`total_time = proc_time + micro_stop_duration`, where a stop fires with
probability `params["probability"]` and, if it fires, its duration is
drawn Uniform(min_duration, max_duration). So the EXPECTED extra time
added to one visit's service time is

    E[extra] = stop_probability * (min_duration + max_duration) / 2

OLD equation (shift_scheduler.py, unchanged there): stop_probability =
0.15 + 0.45*severity, max_duration = 15 + 45*severity, min_duration = 8.
At the theoretical maximum severity=1.0 (never even reached -- SEVERE was
capped at 0.95): E[extra] = 0.60 * 34.0 = 20.4s. At the old SEVERE upper
bound (0.95): E[extra] = 18.99s.

Comparing to the gap each candidate station needs to close (mean cycle
time -> mean_interarrival_seconds=115s, i.e. mix_mean subtracted from
115): S26 needs +37.6s, S20 needs +49.0s, S07 needs +67.0s. The OLD
equation's absolute maximum (20.4s) is smaller than EVERY candidate's
gap -- MICRO_STOPS as previously parameterized was mechanically
INCAPABLE of reaching breakeven at any candidate station, at any
severity, full stop. This -- not "scenario windows too short" (shift
duration is many hours, plenty of time) and not "combination of small
effects" -- is the complete, sufficient explanation for its 0/6
conversion rate in Dataset B.

NEW equation (Decision 37 Section 3, LOCAL to this module only --
shift_scheduler.py's own MICRO_STOPS branch, used by the background
scheduler, is untouched): stop_probability = 0.20 + 0.65*severity,
max_duration = 15 + 75*severity, min_duration = 8 (unchanged). Chosen
mechanistically to make S26 (the only candidate whose gap, 37.6s, is
within reach of a plausible "micro-stop" duration/frequency) show:

    stratum    severity range   E[extra]@bound   fraction of S26's 37.6s gap
    MILD       [0.15, 0.35)     5.1s  -> 10.5s    14% -> 28%   comfortably below
    MODERATE   [0.35, 0.65)     10.5s -> 22.3s    28% -> 59%   approaches, usually doesn't cross
    SEVERE     [0.65, 0.95]     22.3s -> 38.5s    59% -> 102%  genuinely possible near the top,
                                                                 NOT a guarantee (severity is a
                                                                 continuous draw across the whole
                                                                 stratum, and E[extra] is a MEAN --
                                                                 the realized per-visit roll still
                                                                 varies around it)

S07 (gap 67.0s) and S20 (gap 49.0s) remain mechanically out of reach even
under this recalibration (max deliverable ~38.5s) and a further increase
was deliberately NOT made -- Decision 37 explicitly warns against
over-strengthening, and pushing stop_probability/duration far enough to
cover a 49-67s gap would stop looking like an intermittent "micro" stop
at all. MICRO_STOPS candidates are therefore narrowed to {S26} only.

MICRO_STOPS Quality isolation (Decision 37 Section 4): `get_micro_stop_
params` is a separate ScenarioManager method from `get_station_effects`
(which is the only place `_record_exposure` / sensor_mean_shift /
cycle_time_multiplier are touched) -- MICRO_STOPS was ALREADY, by
construction, never able to contribute latent Quality exposure or alter
sensor/cycle_time_multiplier effects. See
tests/test_flow_enrichment_schedule.py::test_micro_stops_quality_isolation
for the structural proof (unaffected by the probability/duration
recalibration above, which only changes numeric coefficients, not which
channel MICRO_STOPS writes through).

REVISED CANDIDATE LIST (Section 10) -- all three remaining station-scoped
candidates land in final_assembly; this is NOT a forced choice, it is the
audit's honest conclusion: every body_joining and paint_surface station
in this factory has enough headroom (mix_mean well under the 115s pacing
rate) that no known-family mechanism at a plausible severity can reach
its breakeven. Zone diversity was not forced (per Decision 37 Section
10's explicit instruction not to).

    S21 (final_assembly) -- MANUAL_VARIATION (near-breakeven + variance)
    S22 (final_assembly) -- MANUAL_VARIATION (comfortably capable)
    S26 (final_assembly) -- MICRO_STOPS, recalibrated (only reachable gap)
    VEHICLE_MIX_OVERLOAD -- line-level, hard-negative only (not capable
        anywhere in this configuration); documented expected-context
        stations remain S22/S26/S36 for reporting purposes only.
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

# ---- Decision 37: revised family/station compatibility map ----
STATION_CANDIDATES: Dict[str, dict] = {
    "S21": {"zone": "final_assembly", "family": ScenarioFamily.MANUAL_VARIATION},
    "S22": {"zone": "final_assembly", "family": ScenarioFamily.MANUAL_VARIATION},
    "S26": {"zone": "final_assembly", "family": ScenarioFamily.MICRO_STOPS},
}
# Stations considered in the Decision-36 candidate list and DROPPED after
# the Decision-37 capacity-margin audit showed they are mechanically
# incapable of reaching breakeven under the (unchanged) MANUAL_VARIATION
# equation, or (for S07/S20) under even the recalibrated MICRO_STOPS
# equation. Kept here only as a documented negative result.
REJECTED_CANDIDATES = {
    "S11": "MANUAL_VARIATION margin -0.144 (breakeven 1.769 > max deliverable 1.625)",
    "S24": "MANUAL_VARIATION margin +0.092 -- technically capable but negligible in practice",
    "S33": "MANUAL_VARIATION margin -0.358",
    "S34": "MANUAL_VARIATION margin -0.066",
    "S07": "MICRO_STOPS gap 67.0s vs. max deliverable 38.5s even recalibrated",
    "S20": "MICRO_STOPS gap 49.0s vs. max deliverable 38.5s even recalibrated",
}
# Stations mechanistically expected to be stressed by a line-level
# VEHICLE_MIX_OVERLOAD instance -- documentation only; per the Decision-37
# feasibility audit this family cannot reach breakeven anywhere in this
# configuration, so these are NOT bottleneck-capable, just the most
# context-relevant stations to look at in diagnostics.
MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS = ["S22", "S26", "S36"]

KNOWN_FLOW_FAMILIES = [
    ScenarioFamily.MANUAL_VARIATION,
    ScenarioFamily.MICRO_STOPS,
    ScenarioFamily.VEHICLE_MIX_OVERLOAD,
]
# Decision 37 Section 8: MANUAL_VARIATION must not dominate the way it
# would if it were the sole positive mechanism -- rebalanced toward a
# roughly even three-way split now that MICRO_STOPS is mechanically
# capable (at S26) and VEHICLE_MIX_OVERLOAD is retained as a deliberate
# hard-negative rather than dropped.
FAMILY_OPPORTUNITY_WEIGHTS = {
    ScenarioFamily.MANUAL_VARIATION: 0.35,
    ScenarioFamily.MICRO_STOPS: 0.35,
    ScenarioFamily.VEHICLE_MIX_OVERLOAD: 0.30,
}
# Only MANUAL_VARIATION and MICRO_STOPS were shown capable of reaching
# breakeven anywhere in this configuration (Decision 37 Sections 1-3);
# VEHICLE_MIX_OVERLOAD was shown structurally incapable everywhere
# (Section 5) and is scheduled purely as a contextual hard negative.
BOTTLENECK_CAPABLE_FAMILIES = {ScenarioFamily.MANUAL_VARIATION, ScenarioFamily.MICRO_STOPS}

# Severity strata (unchanged shape from Decision 36 -- see original
# rationale in git history at commit fbd3f9d; still a tercile-like split
# of the effect equations' usable domain, still fixed before any Dataset-C
# outcome exists).
SEVERITY_STRATA = {
    "MILD": (0.15, 0.35),
    "MODERATE": (0.35, 0.65),
    "SEVERE": (0.65, 0.95),
}
SEVERITY_STRATUM_WEIGHTS = {"MILD": 0.35, "MODERATE": 0.35, "SEVERE": 0.30}

# Decision 37 Section 3: MICRO_STOPS recalibration, LOCAL to this module
# (shift_scheduler.py's own MICRO_STOPS branch, used by the unchanged
# background scheduler in every shift including Datasets A and B, is
# untouched). See module docstring for the derivation.
MICRO_STOPS_CALIBRATION = {
    "old": {"stop_probability": "0.15 + 0.45*severity", "max_duration_seconds": "15 + 45*severity", "min_duration_seconds": 8},
    "new": {"stop_probability": "0.20 + 0.65*severity", "max_duration_seconds": "15 + 75*severity", "min_duration_seconds": 8},
}

# Decision 37 Section 13: opportunity-coverage targets increased given the
# observed low, stochastic opportunity->blocking conversion rate. Still
# shift-opportunity counts, NOT positive-label quotas.
FLOW_OPPORTUNITY_RANGE = {"train": (24, 30), "validation": (8, 10), "test": (8, 10)}
# Decision 37 Section 9: EQUIPMENT_DEGRADATION kept completely unchanged,
# same guaranteed-coverage counts as Dataset B.
DEGRADATION_OPPORTUNITY_COUNT = {"train": 6, "validation": 2, "test": 2}
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
    expected_bottleneck_capable: bool = True


def _shift_id(i: int) -> str:
    return f"SHIFT{i:03d}"


def _partition_shift_ids() -> Dict[str, List[str]]:
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
    k = min(k, len(items))
    parts = _thirds(items)
    counts = [k // 3] * 3
    for i in range(k - sum(counts)):
        counts[i] += 1
    chosen: List[str] = []
    for part, c in zip(parts, counts):
        c = min(c, len(part))
        chosen.extend(rng.sample(part, c))
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
    tables above. Reads no events, labels, or simulation output."""
    if n_shifts != 100:
        raise ValueError("the locked 70/15/15 partition assumes exactly 100 shifts")

    plan_rng = random.Random(derive_seed(dataset_master_seed, "flow_enrichment_plan_v2"))
    partitions = _partition_shift_ids()

    opportunities: List[EnrichmentOpportunity] = []

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
                expected_bottleneck_capable=(family in BOTTLENECK_CAPABLE_FAMILIES),
            ))

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
                duration_fraction=dur_frac, expected_bottleneck_capable=False,
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


def _build_recalibrated_micro_stops(scenario_id, station, start_time, duration, severity) -> ScenarioDefinition:
    """Decision 37 Section 3: mechanically recalibrated MICRO_STOPS,
    local to the Flow-enrichment path only. See MICRO_STOPS_CALIBRATION
    and the module docstring for the derivation. shift_scheduler.py's own
    MICRO_STOPS branch (background scheduler) is untouched."""
    return ScenarioDefinition(
        scenario_id=scenario_id, family=ScenarioFamily.MICRO_STOPS, station_ids=[station],
        start_time=start_time, duration=duration, severity=severity,
        params={
            "stop_probability": 0.20 + severity * 0.65,
            "min_duration_seconds": 8, "max_duration_seconds": 15 + severity * 75,
        },
    )


def _opportunity_to_scenario(opp: EnrichmentOpportunity, shift_id: str, shift_duration_seconds: float,
                              scenario_id: str, rng: random.Random) -> ScenarioDefinition:
    start_time = opp.start_time_fraction * shift_duration_seconds
    duration = opp.duration_fraction * shift_duration_seconds
    family = ScenarioFamily(opp.family)

    if family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
        return _build_mix_overload(scenario_id, start_time, duration, opp.severity, rng)
    if family == ScenarioFamily.MICRO_STOPS:
        return _build_recalibrated_micro_stops(scenario_id, opp.station_id, start_time, duration, opp.severity)
    return _build_station_scenario(scenario_id, family, opp.station_id, start_time, duration, opp.severity, rng)


def build_shift_schedule_enriched(
    dataset_master_seed: int,
    shift_id: str,
    shift_duration_seconds: float,
    mean_interarrival_seconds: float,
    plan_by_shift: Dict[str, List[EnrichmentOpportunity]],
    held_out_family=None,
):
    """Baseline (identical to Dataset A/B's build_shift_schedule, same
    RNG stream, same call) PLUS the frozen enrichment opportunities for
    this shift appended on top. Never mutates or reorders the baseline
    scenarios."""
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

    apply_rng = random.Random(derive_seed(dataset_master_seed, f"flow_enrichment_apply_v2::{shift_id}"))
    scenarios = list(baseline.scenarios)
    for i, opp in enumerate(opportunities):
        scenario_id = f"{shift_id}::flow_enrich::{opp.kind}::{i}"
        scenarios.append(_opportunity_to_scenario(opp, shift_id, shift_duration_seconds, scenario_id, apply_rng))

    baseline.scenarios = scenarios
    return baseline
