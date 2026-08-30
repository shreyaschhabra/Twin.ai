"""Predeclared Flow-v3 controlled corpus (Section 14).

The manifest below is a pure function of static config -- it enumerates
(run_id, seed, partition, mechanism, station, severity, profile) BEFORE any
simulation is executed and BEFORE any label/outcome exists. Partition
assignment is by whole COMBO (mechanism, station/target, severity), never by
resulting label, so every mechanism and every severity band appears in every
partition. Each combo contributes three independent seeds.

Supervised mechanisms (used for Flow ML training/evaluation):
    MANUAL_VARIATION over the 7 approved candidates
    MICRO_STOPS over the 2 approved candidates
    ARRIVAL_BURST (line-level, no fixed target station)

Additional predeclared categories (Section 14):
    healthy controls (no scenario at all)
    VEHICLE_MIX_OVERLOAD hard negatives

EQUIPMENT_DEGRADATION is a completely separate, smaller unseen-robustness
manifest (`build_unseen_degradation_manifest`) -- never mixed into
train/validation/test and never used to tune anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.flow_v3.scenario_physics import (
    ARRIVAL_PROFILES,
    DEGRADATION_PROFILES,
    MANUAL_CANDIDATES,
    MANUAL_PROFILES,
    MICRO_STOP_CANDIDATES,
    MICRO_STOP_PROFILES,
    PROVISIONAL_HEADWAY_SECONDS,
    SEVERITY_ORDER,
)
from backend.historical.shift_scheduler import FAMILY_STATION_POOLS
from backend.simulation.rng import derive_seed
from backend.simulation.scenarios.config import ScenarioFamily

CORPUS_MASTER_SEED = 20260830
STD_INTERARRIVAL_SECONDS = 15.0
N_VEHICLES = 300
SCENARIO_START_SECONDS = 7200.0

# One representative profile per severity keeps the combo grid at a size
# that fits the ~90-run budget while still exercising every profile shape
# declared in Section 5 across the corpus as a whole.
MANUAL_PROFILE_BY_SEVERITY = {"MILD": "STEP", "MODERATE": "GRADUAL", "SEVERE": "RECOVERING"}
MICRO_PROFILE_BY_SEVERITY = {"MILD": "GRADUAL", "MODERATE": "STEP", "SEVERE": "RECOVERING"}
ARRIVAL_PROFILE_BY_SEVERITY = {"MILD": "STEP_BURST", "MODERATE": "RAMP_BURST", "SEVERE": "STEP_BURST"}
assert set(MANUAL_PROFILE_BY_SEVERITY.values()) <= set(MANUAL_PROFILES)
assert set(MICRO_PROFILE_BY_SEVERITY.values()) <= set(MICRO_STOP_PROFILES)
assert set(ARRIVAL_PROFILE_BY_SEVERITY.values()) <= set(ARRIVAL_PROFILES)


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    seed: int
    partition: str  # "train" | "validation" | "test"
    mechanism: str  # ScenarioFamily value, or "HEALTHY_CONTROL"
    station_id: Optional[str]  # None for line-level / healthy
    severity: Optional[str]
    profile: Optional[str]
    arrival_regime: str
    n_vehicles: int = N_VEHICLES
    scenario_start_seconds: float = SCENARIO_START_SECONDS
    notes: str = ""


def _axis_severity_partitions(axis_index: int) -> dict[str, str]:
    """Per (mechanism, target) axis: one severity goes to validation, one
    to test (rotating which, across axes, for variety), one to train.

    This -- rather than a global index-cycling pattern, and rather than
    holding out only a single severity per axis -- is what actually
    guarantees every mechanism AND every severity appears in every
    partition unconditionally. ARRIVAL_BURST is a single axis (no
    per-station variation): with only one axis and one held-out slot it
    can reach validation OR test but never both; holding out two of its
    three severities (one each way) is the only design that gives every
    axis, including single-axis mechanisms, a representative in all three
    partitions regardless of how many stations that mechanism has.

    10 axes x 3 severities = 30 combos -> 10 train-combos, 10 validation,
    10 test; x3 seeds/combo -> 30/30/30 runs. This is a more even split
    than Section 14's suggested 54/18/18, traded deliberately for an
    unconditional coverage guarantee rather than a ratio that depends on
    how many stations happen to share a mechanism.
    """
    validation_severity = SEVERITY_ORDER[axis_index % 3]
    test_severity = SEVERITY_ORDER[(axis_index + 1) % 3]
    return {
        severity: (
            "validation" if severity == validation_severity
            else "test" if severity == test_severity
            else "train"
        )
        for severity in SEVERITY_ORDER
    }


def _seed(stream_name: str) -> int:
    return derive_seed(CORPUS_MASTER_SEED, stream_name) % (2**31 - 1)


def _supervised_combos() -> list[tuple[str, Optional[str]]]:
    """(mechanism, station_id) axes, in a fixed deterministic order."""
    combos: list[tuple[str, Optional[str]]] = []
    for station_id in MANUAL_CANDIDATES:
        combos.append((ScenarioFamily.MANUAL_VARIATION.value, station_id))
    for station_id in MICRO_STOP_CANDIDATES:
        combos.append((ScenarioFamily.MICRO_STOPS.value, station_id))
    combos.append((ScenarioFamily.ARRIVAL_BURST.value, None))
    return combos


def build_run_manifest() -> list[RunSpec]:
    specs: list[RunSpec] = []

    # --- Supervised mechanisms: (mechanism, target) x severity, 3 seeds/
    # combo. 10 axes x 3 severities = 30 combos x 3 seeds = 90 runs
    # (30 train / 30 validation / 30 test); see _axis_severity_partitions.
    combo_axes = _supervised_combos()
    for axis_index, (mechanism, station_id) in enumerate(combo_axes):
        axis_partitions = _axis_severity_partitions(axis_index)
        for severity in SEVERITY_ORDER:
            partition = axis_partitions[severity]
            if mechanism == ScenarioFamily.MANUAL_VARIATION.value:
                profile = MANUAL_PROFILE_BY_SEVERITY[severity]
            elif mechanism == ScenarioFamily.MICRO_STOPS.value:
                profile = MICRO_PROFILE_BY_SEVERITY[severity]
            else:
                profile = ARRIVAL_PROFILE_BY_SEVERITY[severity]
            for seed_index in range(3):
                target = station_id or "LINE"
                run_id = f"flowv3_{mechanism}_{target}_{severity}_{seed_index}"
                specs.append(RunSpec(
                    run_id=run_id,
                    seed=_seed(run_id),
                    partition=partition,
                    mechanism=mechanism,
                    station_id=station_id,
                    severity=severity,
                    profile=profile,
                    arrival_regime=f"nominal_{PROVISIONAL_HEADWAY_SECONDS:.1f}s",
                    notes="supervised precursor mechanism",
                ))

    # --- Healthy controls: no scenario at all. Spread across partitions;
    # doubles as the anomaly layer's genuinely-nominal fitting population
    # and as the false-alert denominator for healthy operation.
    healthy_partitions = (
        ["train"] * 6 + ["validation"] * 2 + ["test"] * 2
    )
    for index, partition in enumerate(healthy_partitions):
        run_id = f"flowv3_healthy_control_{index}"
        specs.append(RunSpec(
            run_id=run_id,
            seed=_seed(run_id),
            partition=partition,
            mechanism="HEALTHY_CONTROL",
            station_id=None,
            severity=None,
            profile=None,
            arrival_regime=f"nominal_{PROVISIONAL_HEADWAY_SECONDS:.1f}s",
            notes="no scenario active; nominal operation only",
        ))

    # --- VEHICLE_MIX_OVERLOAD hard negatives: workload composition shifts
    # without ever crossing physical service capacity (Section 6/7).
    mix_specs = [
        ("MILD", "train"), ("MILD", "train"), ("MILD", "validation"),
        ("MODERATE", "train"), ("MODERATE", "train"), ("MODERATE", "test"),
        ("SEVERE", "train"), ("SEVERE", "validation"), ("SEVERE", "test"),
    ]
    for index, (severity, partition) in enumerate(mix_specs):
        run_id = f"flowv3_mix_overload_{severity}_{index}"
        specs.append(RunSpec(
            run_id=run_id,
            seed=_seed(run_id),
            partition=partition,
            mechanism=ScenarioFamily.VEHICLE_MIX_OVERLOAD.value,
            station_id=None,
            severity=severity,
            profile="SUSTAINED_MIX",
            arrival_regime=f"nominal_{PROVISIONAL_HEADWAY_SECONDS:.1f}s",
            notes="hard negative: workload mix shift, not a supervised precursor mechanism",
        ))

    return specs


def build_unseen_degradation_manifest() -> list[RunSpec]:
    """Completely separate corpus: never in train/validation/test, never
    used to tune anything. EQUIPMENT_DEGRADATION only appears here."""
    stations = FAMILY_STATION_POOLS[ScenarioFamily.EQUIPMENT_DEGRADATION][:3]
    specs: list[RunSpec] = []
    for station_id in stations:
        for severity in SEVERITY_ORDER:
            profile = DEGRADATION_PROFILES[SEVERITY_ORDER.index(severity) % len(DEGRADATION_PROFILES)]
            for seed_index in range(2):
                run_id = f"flowv3_unseen_degradation_{station_id}_{severity}_{seed_index}"
                specs.append(RunSpec(
                    run_id=run_id,
                    seed=_seed(run_id),
                    partition="unseen_equipment_degradation",
                    mechanism=ScenarioFamily.EQUIPMENT_DEGRADATION.value,
                    station_id=station_id,
                    severity=severity,
                    profile=profile,
                    arrival_regime=f"nominal_{PROVISIONAL_HEADWAY_SECONDS:.1f}s",
                    notes="unseen-only robustness corpus; never used in supervised training or tuning",
                ))
    return specs
