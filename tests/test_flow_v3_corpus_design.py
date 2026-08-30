"""Section 14: the predeclared Flow-v3 corpus manifest must be a pure
function of static config, with unique run identity and full mechanism/
severity coverage in every partition -- computed BEFORE any simulation
runs, never adjusted after seeing outcomes."""

from __future__ import annotations

from backend.flow_v3.corpus_design import (
    build_run_manifest,
    build_unseen_degradation_manifest,
)
from backend.simulation.scenarios.config import ScenarioFamily


def test_manifest_is_a_pure_deterministic_function():
    a = build_run_manifest()
    b = build_run_manifest()
    assert [vars(s) for s in a] == [vars(s) for s in b]


def test_run_ids_and_seeds_are_unique():
    specs = build_run_manifest()
    assert len({s.run_id for s in specs}) == len(specs)
    assert len({s.seed for s in specs}) == len(specs)


def test_every_partition_gets_every_supervised_mechanism_and_severity():
    specs = build_run_manifest()
    supervised = {ScenarioFamily.MANUAL_VARIATION.value, ScenarioFamily.MICRO_STOPS.value, ScenarioFamily.ARRIVAL_BURST.value}
    for partition in ("train", "validation", "test"):
        subset = [s for s in specs if s.partition == partition]
        mechanisms = {s.mechanism for s in subset} & supervised
        severities = {s.severity for s in subset if s.severity}
        assert mechanisms == supervised, f"{partition} missing supervised mechanisms: {supervised - mechanisms}"
        assert severities == {"MILD", "MODERATE", "SEVERE"}, f"{partition} missing severities"


def test_no_run_id_appears_in_more_than_one_partition():
    specs = build_run_manifest()
    by_partition = {}
    for spec in specs:
        by_partition.setdefault(spec.run_id, set()).add(spec.partition)
    assert all(len(v) == 1 for v in by_partition.values())


def test_equipment_degradation_is_a_completely_separate_corpus():
    supervised = build_run_manifest()
    degradation = build_unseen_degradation_manifest()
    assert not any(s.mechanism == ScenarioFamily.EQUIPMENT_DEGRADATION.value for s in supervised)
    assert all(s.mechanism == ScenarioFamily.EQUIPMENT_DEGRADATION.value for s in degradation)
    assert all(s.partition == "unseen_equipment_degradation" for s in degradation)
    assert set(s.run_id for s in supervised).isdisjoint({s.run_id for s in degradation})


def test_healthy_controls_and_hard_negatives_are_predeclared():
    specs = build_run_manifest()
    assert any(s.mechanism == "HEALTHY_CONTROL" for s in specs)
    assert any(s.mechanism == ScenarioFamily.VEHICLE_MIX_OVERLOAD.value for s in specs)
    # both categories must appear in more than one partition, not dumped
    # entirely into train
    for mechanism in ("HEALTHY_CONTROL", ScenarioFamily.VEHICLE_MIX_OVERLOAD.value):
        partitions = {s.partition for s in specs if s.mechanism == mechanism}
        assert len(partitions) >= 2
