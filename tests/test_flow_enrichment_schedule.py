"""
Tests for the coverage-balanced Flow enrichment scheduler (Decision 36,
Section 39). Covers: schedule-plan reproducibility, the "plan built before
outcomes" boundary, locked shift boundaries, opportunity-count ranges,
station compatibility, severity-strata bounds, unchanged effect equations,
Dataset A non-regression, and additive-only application.
"""

from __future__ import annotations

import inspect
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.historical.flow_enrichment as flow_enrichment
import backend.historical.generator as generator
import backend.historical.shift_scheduler as shift_scheduler
from backend.flow.split import locked_100_shift_split
from backend.historical.flow_enrichment import (
    DEGRADATION_OPPORTUNITY_COUNT,
    FLOW_OPPORTUNITY_RANGE,
    SEVERITY_STRATA,
    STATION_CANDIDATES,
    build_flow_enrichment_plan,
    build_shift_schedule_enriched,
    plan_by_shift,
    save_plan,
)
from backend.simulation.scenarios.config import ScenarioFamily

MASTER_SEED = 20240002


def test_plan_reproducible():
    plan_a = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    plan_b = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    assert [vars(o) for o in plan_a] == [vars(o) for o in plan_b]


def test_plan_has_no_flow_label_dependency():
    """The plan-generation module must never import Flow label/event/
    outcome code -- it is a pure function of (seed, n_shifts) and static
    config-derived tables, called strictly BEFORE any simulation runs."""
    source = inspect.getsource(flow_enrichment)
    forbidden = ["backend.flow.bottleneck_events", "backend.flow.labels",
                 "backend.flow.features", "backend.flow.pipeline", "events.parquet"]
    for token in forbidden:
        assert token not in source, f"flow_enrichment.py must not reference {token}"


def test_plan_is_pure_function_of_seed_and_count():
    """Calling the plan builder requires no events/simulation output at
    all -- it can run standing alone with nothing generated yet."""
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    assert len(plan) > 0


def test_locked_shift_boundaries_match_split():
    split = locked_100_shift_split()
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    by_partition = {"train": set(split.train_shifts), "validation": set(split.validation_shifts),
                     "test": set(split.test_shifts)}
    for opp in plan:
        assert opp.shift_id in by_partition[opp.partition], (
            f"{opp.shift_id} assigned to partition {opp.partition} but split disagrees"
        )


def test_opportunity_count_within_declared_ranges():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    known = [o for o in plan if o.kind == "known_flow_enrichment"]
    for partition, (low, high) in FLOW_OPPORTUNITY_RANGE.items():
        shifts = {o.shift_id for o in known if o.partition == partition}
        assert low <= len(shifts) <= high, f"{partition}: {len(shifts)} opportunity shifts, expected [{low},{high}]"


def test_degradation_opportunity_counts():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    degradation = [o for o in plan if o.kind == "unseen_degradation_opportunity"]
    for partition, expected in DEGRADATION_OPPORTUNITY_COUNT.items():
        shifts = {o.shift_id for o in degradation if o.partition == partition}
        assert len(shifts) == expected


def test_no_single_family_dominates_flow_opportunities():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    known = [o for o in plan if o.kind == "known_flow_enrichment"]
    counts = {}
    for o in known:
        counts[o.family] = counts.get(o.family, 0) + 1
    total = len(known)
    for family, n in counts.items():
        assert n / total < 0.7, f"{family} accounts for {n}/{total} opportunities -- too dominant"
    assert len(counts) >= 2


def test_severities_include_mild_moderate_not_only_severe():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    known = [o for o in plan if o.kind == "known_flow_enrichment"]
    strata = {o.severity_stratum for o in known}
    assert "MILD" in strata or "MODERATE" in strata, "enrichment must not be all-SEVERE"


def test_station_compatibility_respected():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    for o in plan:
        if o.kind != "known_flow_enrichment":
            continue
        if o.family == ScenarioFamily.VEHICLE_MIX_OVERLOAD.value:
            assert o.station_id is None
        else:
            assert o.station_id in STATION_CANDIDATES
            assert STATION_CANDIDATES[o.station_id]["family"].value == o.family


def test_severity_strata_bounds():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    for o in plan:
        if o.severity_stratum is None:
            continue
        lo, hi = SEVERITY_STRATA[o.severity_stratum]
        assert lo <= o.severity <= hi


def test_degradation_severity_uses_original_unstratified_range():
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    degradation = [o for o in plan if o.kind == "unseen_degradation_opportunity"]
    for o in degradation:
        assert o.severity_stratum is None
        assert 0.3 <= o.severity <= 0.9


def test_scenario_effect_equations_reused_not_duplicated():
    """Proves flow_enrichment.py reuses the exact same builder functions
    as the unchanged background scheduler -- no duplicated/drifted effect
    equations for the enriched corpus."""
    assert flow_enrichment._build_station_scenario is shift_scheduler._build_station_scenario
    assert flow_enrichment._build_mix_overload is shift_scheduler._build_mix_overload


def test_dataset_a_default_schedule_fn_unchanged():
    """generate_development_dataset / generate_and_write_dataset_streaming
    default schedule_fn to the ORIGINAL build_shift_schedule, so Dataset A's
    code path is untouched by this module's existence."""
    sig1 = inspect.signature(generator.generate_development_dataset)
    sig2 = inspect.signature(generator.generate_and_write_dataset_streaming)
    assert sig1.parameters["schedule_fn"].default is shift_scheduler.build_shift_schedule
    assert sig2.parameters["schedule_fn"].default is shift_scheduler.build_shift_schedule


def test_enriched_schedule_is_additive_only():
    """For a shift with a planned opportunity, the enriched schedule must
    contain every scenario the baseline (unmodified) build_shift_schedule
    would have produced, plus the planned addition -- never fewer, never
    reordered in a way that drops anything."""
    shift_id = "SHIFT005"
    plan = [
        flow_enrichment.EnrichmentOpportunity(
            shift_id=shift_id, partition="train", kind="known_flow_enrichment",
            family=ScenarioFamily.MANUAL_VARIATION.value, station_id="S22",
            severity_stratum="SEVERE", severity=0.8, start_time_fraction=0.3, duration_fraction=0.3,
        )
    ]
    by_shift = plan_by_shift(plan)

    baseline = shift_scheduler.build_shift_schedule(
        dataset_master_seed=MASTER_SEED, shift_id=shift_id,
        shift_duration_seconds=51750.0, mean_interarrival_seconds=115.0,
    )
    enriched = build_shift_schedule_enriched(
        dataset_master_seed=MASTER_SEED, shift_id=shift_id,
        shift_duration_seconds=51750.0, mean_interarrival_seconds=115.0,
        plan_by_shift=by_shift,
    )

    baseline_ids = [s.scenario_id for s in baseline.scenarios]
    enriched_ids = [s.scenario_id for s in enriched.scenarios]
    assert enriched_ids[: len(baseline_ids)] == baseline_ids
    assert len(enriched_ids) == len(baseline_ids) + 1
    assert enriched.scenarios[-1].family == ScenarioFamily.MANUAL_VARIATION
    assert enriched.scenarios[-1].station_ids == ["S22"]


def test_shift_with_no_opportunity_is_untouched():
    shift_id = "SHIFT999"  # not in the plan
    by_shift = plan_by_shift([])
    baseline = shift_scheduler.build_shift_schedule(
        dataset_master_seed=MASTER_SEED, shift_id=shift_id,
        shift_duration_seconds=51750.0, mean_interarrival_seconds=115.0,
    )
    enriched = build_shift_schedule_enriched(
        dataset_master_seed=MASTER_SEED, shift_id=shift_id,
        shift_duration_seconds=51750.0, mean_interarrival_seconds=115.0,
        plan_by_shift=by_shift,
    )
    assert [s.scenario_id for s in baseline.scenarios] == [s.scenario_id for s in enriched.scenarios]


def test_save_plan_round_trips_and_stores_no_labels(tmp_path):
    plan = build_flow_enrichment_plan(MASTER_SEED, n_shifts=100)
    out_path = tmp_path / "flow_enriched_schedule.json"
    save_plan(plan, out_path)
    data = json.loads(out_path.read_text())
    assert len(data) == len(plan)
    forbidden_keys = {"label", "target", "bottleneck", "onset_time", "impact_event_id", "outcome"}
    for row in data:
        assert forbidden_keys.isdisjoint(row.keys())


def test_n_shifts_other_than_100_rejected():
    with pytest.raises(ValueError):
        build_flow_enrichment_plan(MASTER_SEED, n_shifts=50)
