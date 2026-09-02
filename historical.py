from __future__ import annotations

# ---- merged from backend/historical/the base shift scheduler ----
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
import random
from dataclasses import dataclass
from typing import Dict, List, Optional
from models import derive_seed
from scenarios import ScenarioDefinition, ScenarioFamily
PROBABILITY_SHIFT_IS_ABNORMAL = 0.55
N_SCENARIOS_WHEN_ABNORMAL = [1, 1, 2, 2, 3]
RANDOM_QUALITY_EVENT_ALWAYS_ON_PROBABILITY = 0.015
RANDOM_QUALITY_EVENT_MIN_MAGNITUDE = 0.008
RANDOM_QUALITY_EVENT_MAX_MAGNITUDE = 0.025
FAMILY_STATION_POOLS: Dict[ScenarioFamily, List[str]] = {ScenarioFamily.EQUIPMENT_DEGRADATION: ['S01', 'S02', 'S03', 'S09', 'S10', 'S27', 'S28', 'S26'], ScenarioFamily.MICRO_STOPS: ['S06', 'S07', 'S23', 'S26', 'S31'], ScenarioFamily.ENVIRONMENTAL_DRIFT: ['S13', 'S14', 'S17', 'S18', 'S19', 'S20'], ScenarioFamily.SENSOR_DROPOUT: ['S04', 'S08', 'S12', 'S31', 'S39'], ScenarioFamily.MANUAL_VARIATION: ['S11', 'S21', 'S22', 'S24', 'S33', 'S34', 'S38'], ScenarioFamily.BAD_BATCH: ['S05', 'S16', 'S25', 'S27', 'S32']}
LINE_LEVEL_FAMILIES = [ScenarioFamily.VEHICLE_MIX_OVERLOAD]
AVAILABLE_FAMILIES_ORDER: List[ScenarioFamily] = list(FAMILY_STATION_POOLS.keys()) + LINE_LEVEL_FAMILIES
BATCH_COHORT_SIZES = {'S05': 6, 'S16': 6, 'S25': 5, 'S27': 10, 'S32': 12}
SENSOR_FOR_STATION = {'S01': 'weld_current', 'S02': 'weld_current', 'S03': 'weld_current', 'S09': 'weld_current', 'S10': 'weld_current', 'S27': 'torque_value', 'S28': 'torque_value', 'S26': 'force_sensor', 'S13': 'booth_temperature', 'S14': 'booth_temperature', 'S17': 'booth_temperature', 'S18': 'booth_temperature', 'S19': 'booth_temperature', 'S20': 'oven_temperature', 'S04': 'laser_scan', 'S08': 'laser_scan', 'S12': 'laser_scan', 'S31': 'position_sensor', 'S39': 'laser_scan'}

@dataclass
class ShiftScenarioPlan:
    shift_id: str
    scenarios: List[ScenarioDefinition]

def build_shift_schedule(dataset_master_seed: int, shift_id: str, shift_duration_seconds: float, mean_interarrival_seconds: float, held_out_family: Optional[ScenarioFamily]=None) -> ShiftScenarioPlan:
    schedule_rng = random.Random(derive_seed(dataset_master_seed, f'shift_schedule::{shift_id}'))
    scenarios: List[ScenarioDefinition] = []
    scenario_counter = 0

    def next_id(family: ScenarioFamily) -> str:
        nonlocal scenario_counter
        scenario_counter += 1
        return f'{shift_id}::{family.value.lower()}::{scenario_counter}'
    scenarios.append(ScenarioDefinition(scenario_id=next_id(ScenarioFamily.RANDOM_QUALITY_EVENT), family=ScenarioFamily.RANDOM_QUALITY_EVENT, start_time=0, duration=None, severity=0.2, params={'per_vehicle_probability': RANDOM_QUALITY_EVENT_ALWAYS_ON_PROBABILITY, 'min_magnitude': RANDOM_QUALITY_EVENT_MIN_MAGNITUDE, 'max_magnitude': RANDOM_QUALITY_EVENT_MAX_MAGNITUDE}))
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
            scenarios.append(_build_bad_batch(next_id(family), start_time, severity, schedule_rng, mean_interarrival_seconds))
        else:
            station = schedule_rng.choice(FAMILY_STATION_POOLS[family])
            scenarios.append(_build_station_scenario(next_id(family), family, station, start_time, duration, severity, schedule_rng))
    return ShiftScenarioPlan(shift_id=shift_id, scenarios=scenarios)

def _build_mix_overload(scenario_id, start_time, duration, severity, rng) -> ScenarioDefinition:
    suv_share = 0.35 + severity * 0.45
    remaining = 1.0 - suv_share
    sedan_share = remaining * rng.uniform(0.5, 0.7)
    ev_share = remaining - sedan_share
    return ScenarioDefinition(scenario_id=scenario_id, family=ScenarioFamily.VEHICLE_MIX_OVERLOAD, start_time=start_time, duration=duration, severity=severity, variant_mix_override={'ICE_SEDAN': sedan_share, 'ICE_SUV': suv_share, 'EV': ev_share})

def _build_bad_batch(scenario_id, start_time, severity, rng, mean_interarrival_seconds) -> ScenarioDefinition:
    station = rng.choice(list(BATCH_COHORT_SIZES.keys()))
    cohort_size = BATCH_COHORT_SIZES[station]
    approx_vehicle_index = max(0, start_time / mean_interarrival_seconds)
    batch_number = 1001 + int(approx_vehicle_index // cohort_size)
    return ScenarioDefinition(scenario_id=scenario_id, family=ScenarioFamily.BAD_BATCH, station_ids=[station], start_time=0, duration=None, severity=severity, affected_batch_id=f'B{batch_number}', params={'quality_weight_per_visit': 0.08 + severity * 0.2})

def _build_station_scenario(scenario_id, family, station, start_time, duration, severity, rng) -> ScenarioDefinition:
    if family == ScenarioFamily.EQUIPMENT_DEGRADATION:
        sensor = SENSOR_FOR_STATION.get(station)
        return ScenarioDefinition(scenario_id=scenario_id, family=family, station_ids=[station], start_time=start_time, duration=duration, severity=severity, affected_sensors=[sensor] if sensor else [], params={'ramp_duration_seconds': duration, 'max_cycle_time_multiplier': 1.2 + severity * 0.8, 'max_noise_multiplier': 1.5 + severity * 1.5, 'max_sensor_mean_shift': -(400 + severity * 800), 'quality_weight_per_visit': 0.02 + severity * 0.05})
    if family == ScenarioFamily.MICRO_STOPS:
        return ScenarioDefinition(scenario_id=scenario_id, family=family, station_ids=[station], start_time=start_time, duration=duration, severity=severity, params={'stop_probability': 0.15 + severity * 0.45, 'min_duration_seconds': 8, 'max_duration_seconds': 15 + severity * 45})
    if family == ScenarioFamily.ENVIRONMENTAL_DRIFT:
        sensor = SENSOR_FOR_STATION.get(station)
        return ScenarioDefinition(scenario_id=scenario_id, family=family, station_ids=[station], start_time=start_time, duration=duration, severity=severity, affected_sensors=[sensor] if sensor else [], params={'ramp_duration_seconds': duration, 'max_sensor_mean_shift': 4 + severity * 10, 'deviation_threshold_fraction': 0.35, 'quality_weight_per_visit': 0.05 + severity * 0.15})
    if family == ScenarioFamily.SENSOR_DROPOUT:
        sensor = SENSOR_FOR_STATION.get(station)
        dropout_type = rng.choice(['missing', 'missing', 'stuck', 'noisy'])
        return ScenarioDefinition(scenario_id=scenario_id, family=family, station_ids=[station], start_time=start_time, duration=duration, severity=severity, affected_sensors=[sensor] if sensor else [], dropout_type=dropout_type, params={'dropout_probability': 0.3 + severity * 0.6})
    if family == ScenarioFamily.MANUAL_VARIATION:
        return ScenarioDefinition(scenario_id=scenario_id, family=family, station_ids=[station], start_time=start_time, duration=duration, severity=severity, params={'cycle_time_multiplier': 1.15 + severity * 0.5, 'variability_multiplier': 1.5 + severity * 2.0, 'quality_weight_per_visit': 0.012 + severity * 0.025})
    raise ValueError(f'no scenario builder for family {family}')

# ---- merged from backend/historical/flow_enrichment.py ----
"""
Coverage-balanced Flow enrichment scheduler (Decision 36, Dataset B;
Decision 37, Dataset C mechanistic calibration).

This module NEVER touches MANUAL_VARIATION's or EQUIPMENT_DEGRADATION's
effect equations, and reuses the base shift scheduler's `_build_mix_overload`
verbatim for VEHICLE_MIX_OVERLOAD. The ONE exception, introduced in
Decision 37 after a capacity-margin audit proved it mechanically
necessary, is a locally-scoped, recalibrated MICRO_STOPS builder
(`_build_recalibrated_micro_stops`) used ONLY by this enrichment path —
the base shift scheduler's own MICRO_STOPS branch (used by the unchanged
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
only factory.yaml, the DEFAULT_VARIANT_MIX, DEFAULT_MEAN_
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
in simulation.py `_maybe_run_micro_stop`:
`total_time = proc_time + micro_stop_duration`, where a stop fires with
probability `params["probability"]` and, if it fires, its duration is
drawn Uniform(min_duration, max_duration). So the EXPECTED extra time
added to one visit's service time is

    E[extra] = stop_probability * (min_duration + max_duration) / 2

OLD equation (the base shift scheduler, unchanged there): stop_probability =
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
the base shift scheduler's own MICRO_STOPS branch, used by the background
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
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from models import derive_seed
from scenarios import ScenarioDefinition, ScenarioFamily
STATION_CANDIDATES: Dict[str, dict] = {'S21': {'zone': 'final_assembly', 'family': ScenarioFamily.MANUAL_VARIATION}, 'S22': {'zone': 'final_assembly', 'family': ScenarioFamily.MANUAL_VARIATION}, 'S26': {'zone': 'final_assembly', 'family': ScenarioFamily.MICRO_STOPS}}
REJECTED_CANDIDATES = {'S11': 'MANUAL_VARIATION margin -0.144 (breakeven 1.769 > max deliverable 1.625)', 'S24': 'MANUAL_VARIATION margin +0.092 -- technically capable but negligible in practice', 'S33': 'MANUAL_VARIATION margin -0.358', 'S34': 'MANUAL_VARIATION margin -0.066', 'S07': 'MICRO_STOPS gap 67.0s vs. max deliverable 38.5s even recalibrated', 'S20': 'MICRO_STOPS gap 49.0s vs. max deliverable 38.5s even recalibrated'}
MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS = ['S22', 'S26', 'S36']
KNOWN_FLOW_FAMILIES = [ScenarioFamily.MANUAL_VARIATION, ScenarioFamily.MICRO_STOPS, ScenarioFamily.VEHICLE_MIX_OVERLOAD]
FAMILY_OPPORTUNITY_WEIGHTS = {ScenarioFamily.MANUAL_VARIATION: 0.35, ScenarioFamily.MICRO_STOPS: 0.35, ScenarioFamily.VEHICLE_MIX_OVERLOAD: 0.3}
BOTTLENECK_CAPABLE_FAMILIES = {ScenarioFamily.MANUAL_VARIATION, ScenarioFamily.MICRO_STOPS}
SEVERITY_STRATA = {'MILD': (0.15, 0.35), 'MODERATE': (0.35, 0.65), 'SEVERE': (0.65, 0.95)}
SEVERITY_STRATUM_WEIGHTS = {'MILD': 0.35, 'MODERATE': 0.35, 'SEVERE': 0.3}
MICRO_STOPS_CALIBRATION = {'old': {'stop_probability': '0.15 + 0.45*severity', 'max_duration_seconds': '15 + 45*severity', 'min_duration_seconds': 8}, 'new': {'stop_probability': '0.20 + 0.65*severity', 'max_duration_seconds': '15 + 75*severity', 'min_duration_seconds': 8}}
FLOW_OPPORTUNITY_RANGE = {'train': (24, 30), 'validation': (8, 10), 'test': (8, 10)}
DEGRADATION_OPPORTUNITY_COUNT = {'train': 6, 'validation': 2, 'test': 2}
DEGRADATION_SEVERITY_RANGE = (0.3, 0.9)
START_TIME_FRACTION_RANGE = (0.05, 0.65)
DURATION_FRACTION_RANGE = (0.15, 0.45)

@dataclass
class EnrichmentOpportunity:
    shift_id: str
    partition: str
    kind: str
    family: str
    station_id: Optional[str]
    severity_stratum: Optional[str]
    severity: float
    start_time_fraction: float
    duration_fraction: float
    expected_bottleneck_capable: bool = True

def _shift_id(i: int) -> str:
    return f'SHIFT{i:03d}'

def _partition_shift_ids() -> Dict[str, List[str]]:
    return {'train': [_shift_id(i) for i in range(1, 71)], 'validation': [_shift_id(i) for i in range(71, 86)], 'test': [_shift_id(i) for i in range(86, 101)]}

def _thirds(items: List[str]) -> List[List[str]]:
    n = len(items)
    a, b = (n // 3, 2 * n // 3)
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

def build_flow_enrichment_plan(dataset_master_seed: int, n_shifts: int=100) -> List[EnrichmentOpportunity]:
    """Pure function of (dataset_master_seed, n_shifts) plus the static
    tables above. Reads no events, labels, or simulation output."""
    if n_shifts != 100:
        raise ValueError('the locked 70/15/15 partition assumes exactly 100 shifts')
    plan_rng = random.Random(derive_seed(dataset_master_seed, 'flow_enrichment_plan_v2'))
    partitions = _partition_shift_ids()
    opportunities: List[EnrichmentOpportunity] = []
    for partition_name in ['train', 'validation', 'test']:
        low, high = FLOW_OPPORTUNITY_RANGE[partition_name]
        count = plan_rng.randint(low, high)
        chosen_shifts = _spread_sample(plan_rng, partitions[partition_name], count)
        for shift_id in chosen_shifts:
            family = plan_rng.choices(KNOWN_FLOW_FAMILIES, weights=[FAMILY_OPPORTUNITY_WEIGHTS[f] for f in KNOWN_FLOW_FAMILIES], k=1)[0]
            stratum = plan_rng.choices(list(SEVERITY_STRATUM_WEIGHTS), weights=list(SEVERITY_STRATUM_WEIGHTS.values()), k=1)[0]
            severity = _draw_severity(plan_rng, stratum)
            start_frac = plan_rng.uniform(*START_TIME_FRACTION_RANGE)
            dur_frac = plan_rng.uniform(*DURATION_FRACTION_RANGE)
            if family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
                station_id = None
            else:
                candidates = [s for s, info in STATION_CANDIDATES.items() if info['family'] == family]
                station_id = plan_rng.choice(candidates)
            opportunities.append(EnrichmentOpportunity(shift_id=shift_id, partition=partition_name, kind='known_flow_enrichment', family=family.value, station_id=station_id, severity_stratum=stratum, severity=severity, start_time_fraction=start_frac, duration_fraction=dur_frac, expected_bottleneck_capable=family in BOTTLENECK_CAPABLE_FAMILIES))
    degradation_pool = FAMILY_STATION_POOLS[ScenarioFamily.EQUIPMENT_DEGRADATION]
    for partition_name in ['train', 'validation', 'test']:
        count = DEGRADATION_OPPORTUNITY_COUNT[partition_name]
        chosen_shifts = _spread_sample(plan_rng, partitions[partition_name], count)
        for shift_id in chosen_shifts:
            station_id = plan_rng.choice(degradation_pool)
            severity = plan_rng.uniform(*DEGRADATION_SEVERITY_RANGE)
            start_frac = plan_rng.uniform(*START_TIME_FRACTION_RANGE)
            dur_frac = plan_rng.uniform(*DURATION_FRACTION_RANGE)
            opportunities.append(EnrichmentOpportunity(shift_id=shift_id, partition=partition_name, kind='unseen_degradation_opportunity', family=ScenarioFamily.EQUIPMENT_DEGRADATION.value, station_id=station_id, severity_stratum=None, severity=severity, start_time_fraction=start_frac, duration_fraction=dur_frac, expected_bottleneck_capable=False))
    return opportunities

def plan_by_shift(plan: List[EnrichmentOpportunity]) -> Dict[str, List[EnrichmentOpportunity]]:
    out: Dict[str, List[EnrichmentOpportunity]] = {}
    for opp in plan:
        out.setdefault(opp.shift_id, []).append(opp)
    return out

def save_plan(plan: List[EnrichmentOpportunity], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        json.dump([asdict(o) for o in plan], f, indent=2)

def _build_recalibrated_micro_stops(scenario_id, station, start_time, duration, severity) -> ScenarioDefinition:
    """Decision 37 Section 3: mechanically recalibrated MICRO_STOPS,
    local to the Flow-enrichment path only. See MICRO_STOPS_CALIBRATION
    and the module docstring for the derivation. the base shift scheduler's own
    MICRO_STOPS branch (background scheduler) is untouched."""
    return ScenarioDefinition(scenario_id=scenario_id, family=ScenarioFamily.MICRO_STOPS, station_ids=[station], start_time=start_time, duration=duration, severity=severity, params={'stop_probability': 0.2 + severity * 0.65, 'min_duration_seconds': 8, 'max_duration_seconds': 15 + severity * 75})

def _opportunity_to_scenario(opp: EnrichmentOpportunity, shift_id: str, shift_duration_seconds: float, scenario_id: str, rng: random.Random) -> ScenarioDefinition:
    start_time = opp.start_time_fraction * shift_duration_seconds
    duration = opp.duration_fraction * shift_duration_seconds
    family = ScenarioFamily(opp.family)
    if family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
        return _build_mix_overload(scenario_id, start_time, duration, opp.severity, rng)
    if family == ScenarioFamily.MICRO_STOPS:
        return _build_recalibrated_micro_stops(scenario_id, opp.station_id, start_time, duration, opp.severity)
    return _build_station_scenario(scenario_id, family, opp.station_id, start_time, duration, opp.severity, rng)

def build_shift_schedule_enriched(dataset_master_seed: int, shift_id: str, shift_duration_seconds: float, mean_interarrival_seconds: float, plan_by_shift: Dict[str, List[EnrichmentOpportunity]], held_out_family=None):
    """Baseline (identical to Dataset A/B's build_shift_schedule, same
    RNG stream, same call) PLUS the frozen enrichment opportunities for
    this shift appended on top. Never mutates or reorders the baseline
    scenarios."""
    baseline = build_shift_schedule(dataset_master_seed=dataset_master_seed, shift_id=shift_id, shift_duration_seconds=shift_duration_seconds, mean_interarrival_seconds=mean_interarrival_seconds, held_out_family=held_out_family)
    opportunities = plan_by_shift.get(shift_id, [])
    if not opportunities:
        return baseline
    apply_rng = random.Random(derive_seed(dataset_master_seed, f'flow_enrichment_apply_v2::{shift_id}'))
    scenarios = list(baseline.scenarios)
    for i, opp in enumerate(opportunities):
        scenario_id = f'{shift_id}::flow_enrich::{opp.kind}::{i}'
        scenarios.append(_opportunity_to_scenario(opp, shift_id, shift_duration_seconds, scenario_id, apply_rng))
    baseline.scenarios = scenarios
    return baseline

# ---- merged from backend/historical/generator.py ----
"""
Development historical dataset generator (Step 4, Sections M, N, W, X).

Orchestrates many independent shift-level simulations on the full
45-station line, each with its own deterministic scenario schedule and
its own deterministic simulation seed (both derived from one dataset
master seed via the same isolated-stream mechanism as everything else —
see models.py), and assembles the results into a small
set of observable and latent tables, physically separated on disk.

The simulation engine itself has no notion of "shifts" — that concept
lives entirely here, one layer up, which is why vehicle IDs are
re-namespaced per shift only at export time (SHIFT_ID::V00001), not
inside the engine.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional
from config import FactoryConfig
from simulation import RunResult, run_simulation
from models import QCParameters
from models import derive_seed
from scenarios import ScenarioFamily
from models import SensorModelRegistry
DEFAULT_VEHICLES_PER_SHIFT = 450
DEFAULT_MEAN_INTERARRIVAL_SECONDS = 115.0
DEFAULT_STD_INTERARRIVAL_SECONDS = 15.0
DEFAULT_VARIANT_MIX = {'ICE_SEDAN': 0.45, 'ICE_SUV': 0.35, 'EV': 0.2}
QC_STATION_ID = 'S45'

def _resolve_production_inputs(config: FactoryConfig, mean_interarrival_seconds: Optional[float], variant_mix: Optional[Dict[str, float]]) -> tuple[float, Dict[str, float]]:
    """Same-factory-physics rule (Section 3): headway/mix come from
    config.production_plan, never from a duplicated module constant,
    unless the caller explicitly overrides them for a specific experiment."""
    plan = config.production_plan
    if mean_interarrival_seconds is None:
        mean_interarrival_seconds = float(plan.nominal_interarrival_seconds) if plan is not None else DEFAULT_MEAN_INTERARRIVAL_SECONDS
    if variant_mix is None:
        variant_mix = dict(plan.baseline_variant_mix) if plan is not None else dict(DEFAULT_VARIANT_MIX)
    return (mean_interarrival_seconds, variant_mix)

@dataclass
class ShiftResult:
    shift_id: str
    shift_seed: int
    n_vehicles: int
    is_abnormal: bool
    scenario_ids: List[str]
    result: RunResult

def generate_development_dataset(config: FactoryConfig, sensor_models: SensorModelRegistry, batch_relevant_stations: Dict[str, int], n_shifts: int, dataset_master_seed: int, vehicles_per_shift: int=DEFAULT_VEHICLES_PER_SHIFT, mean_interarrival_seconds: Optional[float]=None, std_interarrival_seconds: float=DEFAULT_STD_INTERARRIVAL_SECONDS, variant_mix: Optional[Dict[str, float]]=None, qc_params: Optional[QCParameters]=None, held_out_family: Optional[ScenarioFamily]=None, schedule_fn: Callable=build_shift_schedule) -> List[ShiftResult]:
    mean_interarrival_seconds, variant_mix = _resolve_production_inputs(config, mean_interarrival_seconds, variant_mix)
    qc_params = qc_params or QCParameters()
    shift_results: List[ShiftResult] = []
    for i in range(1, n_shifts + 1):
        shift_results.append(_run_one_shift(config, sensor_models, batch_relevant_stations, i, dataset_master_seed, vehicles_per_shift, mean_interarrival_seconds, std_interarrival_seconds, variant_mix, qc_params, held_out_family, schedule_fn))
    return shift_results

def _global_vehicle_id(shift_id: str, local_vehicle_id: str) -> str:
    return f'{shift_id}::{local_vehicle_id}'

def _extract_rows(shift_results: List[ShiftResult]) -> Dict[str, list]:
    """Pure extraction: ShiftResult objects -> plain-dict rows per table.
    Shared by write_dataset() (batch, in-memory) and
    generate_and_write_dataset_streaming() (chunked) so both paths use
    IDENTICAL row-construction logic — the only difference between them
    is memory management, never the values produced."""
    tables: Dict[str, list] = {'events': [], 'genealogy': [], 'vehicles': [], 'shifts': [], 'scenario_truth': [], 'exposure': [], 'qc_generation': []}
    for sr in shift_results:
        result = sr.result
        for e in result.events:
            row = asdict(e)
            if row.get('vehicle_id'):
                row['vehicle_id'] = _global_vehicle_id(sr.shift_id, row['vehicle_id'])
            row['shift_id'] = sr.shift_id
            tables['events'].append(row)
        for local_vid, visits in result.genealogy.items():
            gvid = _global_vehicle_id(sr.shift_id, local_vid)
            vehicle = result.vehicles[local_vid]
            for visit in visits:
                tables['genealogy'].append({'vehicle_id': gvid, 'shift_id': sr.shift_id, 'variant_id': vehicle.variant_id, **asdict(visit)})
        for local_vid, vehicle in result.vehicles.items():
            tables['vehicles'].append({'vehicle_id': _global_vehicle_id(sr.shift_id, local_vid), 'shift_id': sr.shift_id, 'variant_id': vehicle.variant_id, 'created_at': vehicle.created_at, 'completed': vehicle.completed, 'completed_at': vehicle.completed_at})
        tables['shifts'].append({'shift_id': sr.shift_id, 'shift_seed': sr.shift_seed, 'n_vehicles': sr.n_vehicles, 'is_abnormal': sr.is_abnormal, 'scenario_ids': json.dumps(sr.scenario_ids), 'vehicles_completed': result.summary['vehicles_completed'], 'throughput_vehicles_per_hour': result.summary['throughput_vehicles_per_hour']})
        for rec in result.latent_truth.scenario_truth:
            row = asdict(rec)
            row['params'] = json.dumps(row['params'])
            row['station_ids'] = json.dumps(row['station_ids'])
            row['shift_id'] = sr.shift_id
            tables['scenario_truth'].append(row)
        for rec in result.latent_truth.quality_exposure:
            row = asdict(rec)
            row['vehicle_id'] = _global_vehicle_id(sr.shift_id, row['vehicle_id'])
            row['shift_id'] = sr.shift_id
            tables['exposure'].append(row)
        for rec in result.latent_truth.qc_generation:
            row = asdict(rec)
            row['vehicle_id'] = _global_vehicle_id(sr.shift_id, row['vehicle_id'])
            row['shift_id'] = sr.shift_id
            tables['qc_generation'].append(row)
    return tables

def _run_one_shift(config, sensor_models, batch_relevant_stations, shift_index, dataset_master_seed, vehicles_per_shift, mean_interarrival_seconds, std_interarrival_seconds, variant_mix, qc_params, held_out_family, schedule_fn: Callable=build_shift_schedule) -> ShiftResult:
    """The exact per-shift logic factored out of generate_development_dataset
    so the streaming path below cannot silently drift from it.

    `schedule_fn` defaults to the unchanged build_shift_schedule, so every
    existing call site (Dataset A) is byte-identical to before this
    parameter existed. It exists solely so Dataset B (Decision 36) can
    inject build_shift_schedule_enriched via functools.partial without
    touching this function's own logic."""
    shift_id = f'SHIFT{shift_index:03d}'
    shift_seed = derive_seed(dataset_master_seed, f'shift_sim::{shift_id}')
    shift_duration_estimate = vehicles_per_shift * mean_interarrival_seconds
    plan = schedule_fn(dataset_master_seed=dataset_master_seed, shift_id=shift_id, shift_duration_seconds=shift_duration_estimate, mean_interarrival_seconds=mean_interarrival_seconds, held_out_family=held_out_family)
    is_abnormal = any((s.family != ScenarioFamily.RANDOM_QUALITY_EVENT for s in plan.scenarios))
    result = run_simulation(config, n_vehicles=vehicles_per_shift, seed=shift_seed, mean_interarrival_seconds=mean_interarrival_seconds, std_interarrival_seconds=std_interarrival_seconds, variant_mix=variant_mix, sensor_models=sensor_models, scenarios=plan.scenarios, batch_relevant_stations=batch_relevant_stations, qc_station_id=QC_STATION_ID, qc_params=qc_params)
    return ShiftResult(shift_id=shift_id, shift_seed=shift_seed, n_vehicles=vehicles_per_shift, is_abnormal=is_abnormal, scenario_ids=[s.scenario_id for s in plan.scenarios], result=result)

def generate_and_write_dataset_streaming(config: FactoryConfig, sensor_models: SensorModelRegistry, batch_relevant_stations: Dict[str, int], n_shifts: int, dataset_master_seed: int, observable_dir: Path, latent_dir: Path, vehicles_per_shift: int=DEFAULT_VEHICLES_PER_SHIFT, mean_interarrival_seconds: Optional[float]=None, std_interarrival_seconds: float=DEFAULT_STD_INTERARRIVAL_SECONDS, variant_mix: Optional[Dict[str, float]]=None, qc_params: Optional[QCParameters]=None, held_out_family: Optional[ScenarioFamily]=None, batch_size: int=10, schedule_fn: Callable=build_shift_schedule):
    """Memory-bounded variant of generate_development_dataset() +
    write_dataset(), for dataset sizes where holding every shift's full
    RunResult in memory simultaneously risks OOM (encountered in practice
    scaling from 24 to 100 shifts). Processes `batch_size` shifts at a
    time, writes each batch as a row-group via an incrementally-opened
    pyarrow.parquet.ParquetWriter, and discards each batch's RunResult
    objects before starting the next — so peak memory is O(batch_size
    shifts), not O(n_shifts).

    This is a pure orchestration/IO refactor: `_run_one_shift` and
    `_extract_rows` are the SAME per-shift simulation and row-extraction
    logic used by generate_development_dataset()/write_dataset() (shared,
    not reimplemented), so output is byte-identical — verified by
    tests/test_historical_100.py's prefix-identity test against the
    already-audited 24-shift dataset. No change to FactoryEngine,
    ScenarioManager, QCOutcomeGenerator, or any RNG/causal code path.

    Returns (shift_metadata: List[dict], output_stats: dict) — shift
    metadata (shift_id, shift_seed, is_abnormal, scenario_ids) for the
    manifest, deliberately NOT the full ShiftResult list (which would
    reintroduce the memory problem this function exists to avoid).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    mean_interarrival_seconds, variant_mix = _resolve_production_inputs(config, mean_interarrival_seconds, variant_mix)
    qc_params = qc_params or QCParameters()
    observable_dir.mkdir(parents=True, exist_ok=True)
    latent_dir.mkdir(parents=True, exist_ok=True)
    table_paths = {'events': observable_dir / 'events.parquet', 'genealogy': observable_dir / 'genealogy.parquet', 'vehicles': observable_dir / 'vehicles.parquet', 'shifts': observable_dir / 'shifts.parquet', 'scenario_truth': latent_dir / 'scenario_truth.parquet', 'exposure': latent_dir / 'quality_exposure.parquet', 'qc_generation': latent_dir / 'generator_truth.parquet'}
    writers: Dict[str, Optional[pq.ParquetWriter]] = {k: None for k in table_paths}
    counts = {k: 0 for k in table_paths}
    sensor_reading_count = 0
    qc_result_count = 0
    shift_metadata = []
    NULLABLE_STRING_COLUMNS = {'events': ['vehicle_id', 'vehicle_variant', 'station_id', 'buffer_id', 'from_state', 'to_state', 'sensor_name', 'unit', 'measurement_status', 'batch_id', 'batch_key', 'qc_result'], 'scenario_truth': ['affected_batch_id'], 'exposure': ['scenario_id', 'station_id']}
    NULLABLE_FLOAT_COLUMNS = {'events': ['route_position', 'value', 'occupancy'], 'scenario_truth': ['end_time'], 'vehicles': ['completed_at']}

    def _flush_batch(batch_results: List[ShiftResult]):
        nonlocal sensor_reading_count, qc_result_count
        tables = _extract_rows(batch_results)
        for key, rows in tables.items():
            if not rows:
                continue
            import pandas as pd
            df = pd.DataFrame(rows)
            for col in NULLABLE_STRING_COLUMNS.get(key, []):
                if col in df.columns:
                    df[col] = df[col].astype('string')
            for col in NULLABLE_FLOAT_COLUMNS.get(key, []):
                if col in df.columns:
                    df[col] = df[col].astype('float64')
            arrow_table = pa.Table.from_pandas(df, preserve_index=False)
            if writers[key] is None:
                writers[key] = pq.ParquetWriter(table_paths[key], arrow_table.schema)
            writers[key].write_table(arrow_table)
            counts[key] += len(rows)
            if key == 'events':
                sensor_reading_count += int((df.event_type == 'SENSOR_READING').sum())
                qc_result_count += int((df.event_type == 'QC_RESULT_RECORDED').sum())
    batch: List[ShiftResult] = []
    for i in range(1, n_shifts + 1):
        sr = _run_one_shift(config, sensor_models, batch_relevant_stations, i, dataset_master_seed, vehicles_per_shift, mean_interarrival_seconds, std_interarrival_seconds, variant_mix, qc_params, held_out_family, schedule_fn)
        shift_metadata.append({'shift_id': sr.shift_id, 'shift_seed': sr.shift_seed, 'is_abnormal': sr.is_abnormal, 'scenario_ids': sr.scenario_ids})
        batch.append(sr)
        if len(batch) >= batch_size:
            _flush_batch(batch)
            batch = []
    if batch:
        _flush_batch(batch)
    for w in writers.values():
        if w is not None:
            w.close()
    stats = {'events': counts['events'], 'sensor_readings': sensor_reading_count, 'genealogy_rows': counts['genealogy'], 'vehicles': counts['vehicles'], 'shifts': counts['shifts'], 'scenario_truth_rows': counts['scenario_truth'], 'exposure_rows': counts['exposure'], 'qc_generation_rows': counts['qc_generation']}
    import pandas as pd
    events_pf = pq.ParquetFile(table_paths['events'])
    sensor_writer = None
    qc_writer = None
    for batch_table in events_pf.iter_batches():
        chunk = batch_table.to_pandas()
        sensor_chunk = chunk[chunk.event_type == 'SENSOR_READING']
        if len(sensor_chunk):
            t = pa.Table.from_pandas(sensor_chunk, preserve_index=False)
            if sensor_writer is None:
                sensor_writer = pq.ParquetWriter(observable_dir / 'sensor_readings.parquet', t.schema)
            sensor_writer.write_table(t)
        qc_chunk = chunk[chunk.event_type == 'QC_RESULT_RECORDED'][['vehicle_id', 'shift_id', 'vehicle_variant', 'simulation_time', 'qc_result']]
        if len(qc_chunk):
            t2 = pa.Table.from_pandas(qc_chunk, preserve_index=False)
            if qc_writer is None:
                qc_writer = pq.ParquetWriter(observable_dir / 'qc_results.parquet', t2.schema)
            qc_writer.write_table(t2)
    if sensor_writer is not None:
        sensor_writer.close()
    if qc_writer is not None:
        qc_writer.close()
    return (shift_metadata, stats)

def write_dataset(shift_results: List[ShiftResult], observable_dir: Path, latent_dir: Path) -> Dict[str, int]:
    import pandas as pd
    observable_dir.mkdir(parents=True, exist_ok=True)
    latent_dir.mkdir(parents=True, exist_ok=True)
    event_rows, genealogy_rows, vehicle_rows, shift_rows = ([], [], [], [])
    scenario_truth_rows, exposure_rows, qc_generation_rows = ([], [], [])
    for sr in shift_results:
        result = sr.result
        for e in result.events:
            row = asdict(e)
            if row.get('vehicle_id'):
                row['vehicle_id'] = _global_vehicle_id(sr.shift_id, row['vehicle_id'])
            row['shift_id'] = sr.shift_id
            event_rows.append(row)
        for local_vid, visits in result.genealogy.items():
            gvid = _global_vehicle_id(sr.shift_id, local_vid)
            vehicle = result.vehicles[local_vid]
            for visit in visits:
                genealogy_rows.append({'vehicle_id': gvid, 'shift_id': sr.shift_id, 'variant_id': vehicle.variant_id, **asdict(visit)})
        for local_vid, vehicle in result.vehicles.items():
            vehicle_rows.append({'vehicle_id': _global_vehicle_id(sr.shift_id, local_vid), 'shift_id': sr.shift_id, 'variant_id': vehicle.variant_id, 'created_at': vehicle.created_at, 'completed': vehicle.completed, 'completed_at': vehicle.completed_at})
        shift_rows.append({'shift_id': sr.shift_id, 'shift_seed': sr.shift_seed, 'n_vehicles': sr.n_vehicles, 'is_abnormal': sr.is_abnormal, 'scenario_ids': json.dumps(sr.scenario_ids), 'vehicles_completed': result.summary['vehicles_completed'], 'throughput_vehicles_per_hour': result.summary['throughput_vehicles_per_hour']})
        for rec in result.latent_truth.scenario_truth:
            row = asdict(rec)
            row['params'] = json.dumps(row['params'])
            row['station_ids'] = json.dumps(row['station_ids'])
            row['shift_id'] = sr.shift_id
            scenario_truth_rows.append(row)
        for rec in result.latent_truth.quality_exposure:
            row = asdict(rec)
            row['vehicle_id'] = _global_vehicle_id(sr.shift_id, row['vehicle_id'])
            row['shift_id'] = sr.shift_id
            exposure_rows.append(row)
        for rec in result.latent_truth.qc_generation:
            row = asdict(rec)
            row['vehicle_id'] = _global_vehicle_id(sr.shift_id, row['vehicle_id'])
            row['shift_id'] = sr.shift_id
            qc_generation_rows.append(row)
    events_df = pd.DataFrame(event_rows)
    events_df.to_parquet(observable_dir / 'events.parquet', index=False)
    events_df[events_df.event_type == 'SENSOR_READING'].to_parquet(observable_dir / 'sensor_readings.parquet', index=False)
    events_df[events_df.event_type == 'QC_RESULT_RECORDED'][['vehicle_id', 'shift_id', 'vehicle_variant', 'simulation_time', 'qc_result']].to_parquet(observable_dir / 'qc_results.parquet', index=False)
    pd.DataFrame(genealogy_rows).to_parquet(observable_dir / 'genealogy.parquet', index=False)
    pd.DataFrame(vehicle_rows).to_parquet(observable_dir / 'vehicles.parquet', index=False)
    pd.DataFrame(shift_rows).to_parquet(observable_dir / 'shifts.parquet', index=False)
    pd.DataFrame(scenario_truth_rows).to_parquet(latent_dir / 'scenario_truth.parquet', index=False)
    pd.DataFrame(exposure_rows).to_parquet(latent_dir / 'quality_exposure.parquet', index=False)
    pd.DataFrame(qc_generation_rows).to_parquet(latent_dir / 'generator_truth.parquet', index=False)
    return {'events': len(event_rows), 'sensor_readings': int((events_df.event_type == 'SENSOR_READING').sum()), 'genealogy_rows': len(genealogy_rows), 'vehicles': len(vehicle_rows), 'shifts': len(shift_rows), 'scenario_truth_rows': len(scenario_truth_rows), 'exposure_rows': len(exposure_rows), 'qc_generation_rows': len(qc_generation_rows)}
