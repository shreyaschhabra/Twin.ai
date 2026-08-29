"""
Step 5 continuation, Sections 12/13/22: chronological split and
EQUIPMENT_DEGRADATION holdout tests. Uses synthetic data so these don't
depend on the large generated dataset existing.
"""

import pandas as pd
import pytest

from backend.flow.split import (
    locked_100_shift_split,
    locked_24_shift_split,
    validate_split,
    apply_split,
    SplitDefinition,
)
from backend.flow.holdout import compute_holdout_mask, split_holdout, RECOVERY_GUARD_SECONDS


# ---------------------------------------------------------------- split

def test_locked_100_shift_split_boundaries():
    split = locked_100_shift_split()
    assert split.train_shifts[0] == "SHIFT001"
    assert split.train_shifts[-1] == "SHIFT070"
    assert split.validation_shifts[0] == "SHIFT071"
    assert split.validation_shifts[-1] == "SHIFT085"
    assert split.test_shifts[0] == "SHIFT086"
    assert split.test_shifts[-1] == "SHIFT100"
    assert len(split.train_shifts) == 70
    assert len(split.validation_shifts) == 15
    assert len(split.test_shifts) == 15


def test_split_no_overlap_and_chronological_order():
    for split in [locked_100_shift_split(), locked_24_shift_split()]:
        validate_split(split)  # must not raise


def test_split_detects_overlap():
    bad = SplitDefinition(
        train_shifts=["SHIFT001", "SHIFT002"],
        validation_shifts=["SHIFT002", "SHIFT003"],  # SHIFT002 duplicated
        test_shifts=["SHIFT004"],
    )
    with pytest.raises(AssertionError):
        validate_split(bad)


def test_split_detects_out_of_order_boundaries():
    bad = SplitDefinition(
        train_shifts=["SHIFT005", "SHIFT006"],
        validation_shifts=["SHIFT001", "SHIFT002"],  # earlier than train!
        test_shifts=["SHIFT010"],
    )
    with pytest.raises(AssertionError):
        validate_split(bad)


def test_apply_split_partitions_rows_correctly():
    df = pd.DataFrame({
        "shift_id": ["SHIFT001", "SHIFT071", "SHIFT086", "SHIFT100"],
        "value": [1, 2, 3, 4],
    })
    parts = apply_split(df, locked_100_shift_split())
    assert list(parts["train"].shift_id) == ["SHIFT001"]
    assert list(parts["validation"].shift_id) == ["SHIFT071"]
    assert list(parts["test"].shift_id) == ["SHIFT086", "SHIFT100"]
    # no row duplicated across partitions
    total = len(parts["train"]) + len(parts["validation"]) + len(parts["test"])
    assert total == len(df)


# ---------------------------------------------------------------- holdout

def _scenario_truth_row(shift_id, station_ids, start, end, family="EQUIPMENT_DEGRADATION"):
    import json
    return {
        "shift_id": shift_id, "scenario_id": f"{shift_id}::deg::1", "family": family,
        "station_ids": json.dumps(station_ids), "start_time": start, "end_time": end,
        "severity": 0.7, "params": "{}", "affected_batch_id": None,
    }


def test_holdout_excludes_feature_history_overlap():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0)])
    # a row whose feature window [t-300, t] overlaps [1000,1500]: t=1050 -> window [750,1050], overlaps
    rows = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S05"], "window_end_time": [1050.0]})
    mask = compute_holdout_mask(rows, scenario_truth)
    assert mask.iloc[0]


def test_holdout_excludes_target_horizon_overlap():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0)])
    # a row whose target horizon [t, t+600] overlaps [1000,1500]: t=900 -> horizon [900,1500], overlaps
    rows = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S05"], "window_end_time": [900.0]})
    mask = compute_holdout_mask(rows, scenario_truth)
    assert mask.iloc[0]


def test_holdout_recovery_guard_extends_past_scenario_end():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0)])
    # a row just after end_time but within the recovery guard must still be excluded
    t = 1500.0 + RECOVERY_GUARD_SECONDS - 10  # feature window [t-300,t] reaches into guard zone
    rows = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S05"], "window_end_time": [t]})
    mask = compute_holdout_mask(rows, scenario_truth)
    assert mask.iloc[0]


def test_holdout_does_not_exclude_far_away_rows():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0)])
    # well before: t+600 < start -> no overlap
    far_before = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S05"], "window_end_time": [100.0]})
    # well after: t-300 > guarded_end -> no overlap
    far_after = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S05"], "window_end_time": [1500.0 + RECOVERY_GUARD_SECONDS + 1000.0]})
    assert not compute_holdout_mask(far_before, scenario_truth).iloc[0]
    assert not compute_holdout_mask(far_after, scenario_truth).iloc[0]


def test_holdout_does_not_affect_unrelated_station():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0)])
    rows = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S06"], "window_end_time": [1050.0]})
    mask = compute_holdout_mask(rows, scenario_truth)
    assert not mask.iloc[0]


def test_holdout_ignores_non_degradation_families():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0, family="MANUAL_VARIATION")])
    rows = pd.DataFrame({"shift_id": ["SHIFT_T"], "station_id": ["S05"], "window_end_time": [1050.0]})
    mask = compute_holdout_mask(rows, scenario_truth)
    assert not mask.iloc[0]  # only EQUIPMENT_DEGRADATION triggers the holdout


def test_split_holdout_partitions_supervised_and_robustness():
    scenario_truth = pd.DataFrame([_scenario_truth_row("SHIFT_T", ["S05"], 1000.0, 1500.0)])
    rows = pd.DataFrame({
        "shift_id": ["SHIFT_T"] * 3, "station_id": ["S05", "S05", "S06"],
        "window_end_time": [1050.0, 100000.0, 1050.0],
    })
    parts = split_holdout(rows, scenario_truth)
    assert len(parts["unseen_equipment_degradation"]) == 1
    assert len(parts["supervised"]) == 2
    # no row appears in both
    assert set(parts["supervised"].index).isdisjoint(set(parts["unseen_equipment_degradation"].index))
