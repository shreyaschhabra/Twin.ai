"""
Grouped, mechanism-aware TRAIN/VALIDATION/TEST split (Sections 9-11).
`run_group_id` = shift_id: shifts are the only truly independent
statistical unit this corpus provides (each shift's simulation and
scenario-schedule RNG streams are derived independently -- see
backend/simulation/rng.py), so a whole shift is the atomic group; no
congestion episode is ever split across partitions.

Predeclared using ONLY already-known scenario/impact METADATA (which
station each shift's impact events are attributed to, and which known
scenario families are active in that shift) -- used here purely for
split construction/auditing, never as a model feature, and never
re-drawn after looking at trained-model metrics.

Of the 14 shifts containing >=1 impact event in Dataset C:
  - 11 are S21/S22 MANUAL_VARIATION-driven (the dominant mechanism)
  - 2 are S26 MICRO_STOPS-driven (SHIFT037, SHIFT083)
  - 1 is S34, a mixed BAD_BATCH/MICRO_STOPS/MANUAL_VARIATION shift (SHIFT057)
The 11 S21/S22 shifts are distributed round-robin (index i%3) across
TRAIN/VALIDATION/TEST so no partition is starved of the dominant
mechanism purely by chronological luck (Flow v1's documented failure
mode). The 2 S26 shifts are split TRAIN/TEST (not enough to also cover
VALIDATION -- documented gap, not hidden). The single S34 shift goes to
TRAIN (only one exists; no other partition could evaluate generalization
to it anyway). The remaining 86 all-negative shifts fill out the
remaining slots to keep partition sizes close to v1's 70/15/15
proportions, in shift-ID order (arbitrary among interchangeable
negative-only shifts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

MANUAL_VARIATION_S21_S22_SHIFTS = [
    "SHIFT004", "SHIFT005", "SHIFT014", "SHIFT019", "SHIFT034",
    "SHIFT049", "SHIFT052", "SHIFT077", "SHIFT078", "SHIFT088", "SHIFT099",
]
MICRO_STOPS_S26_SHIFTS = ["SHIFT037", "SHIFT083"]
MIXED_S34_SHIFTS = ["SHIFT057"]

TARGET_TRAIN_COUNT = 70
TARGET_VAL_COUNT = 15
TARGET_TEST_COUNT = 15


@dataclass(frozen=True)
class FlowV2Split:
    train_shifts: List[str]
    validation_shifts: List[str]
    test_shifts: List[str]


def _round_robin(shifts: List[str], train_bucket, val_bucket, test_bucket):
    for i, s in enumerate(sorted(shifts, key=lambda x: int(x[5:]))):
        (train_bucket, val_bucket, test_bucket)[i % 3].append(s)


def locked_flow_v2_split(all_shift_ids: List[str]) -> FlowV2Split:
    train, val, test = [], [], []
    _round_robin(MANUAL_VARIATION_S21_S22_SHIFTS, train, val, test)
    # S26: split train/test only (2 instances -- not enough for all 3 partitions)
    train.append(MICRO_STOPS_S26_SHIFTS[0])
    test.append(MICRO_STOPS_S26_SHIFTS[1])
    # S34: only one instance, goes to train
    train.extend(MIXED_S34_SHIFTS)

    assigned = set(train) | set(val) | set(test)
    remaining = sorted([s for s in all_shift_ids if s not in assigned], key=lambda x: int(x[5:]))

    n_train_needed = max(0, TARGET_TRAIN_COUNT - len(train))
    n_val_needed = max(0, TARGET_VAL_COUNT - len(val))
    train.extend(remaining[:n_train_needed])
    val.extend(remaining[n_train_needed:n_train_needed + n_val_needed])
    test.extend(remaining[n_train_needed + n_val_needed:])

    return FlowV2Split(train_shifts=sorted(train, key=lambda x: int(x[5:])),
                        validation_shifts=sorted(val, key=lambda x: int(x[5:])),
                        test_shifts=sorted(test, key=lambda x: int(x[5:])))


def validate_split(split: FlowV2Split, all_shift_ids: List[str]) -> None:
    train, val, test = set(split.train_shifts), set(split.validation_shifts), set(split.test_shifts)
    assert not (train & val), "TRAIN/VALIDATION overlap"
    assert not (train & test), "TRAIN/TEST overlap"
    assert not (val & test), "VALIDATION/TEST overlap"
    assert train | val | test == set(all_shift_ids), "split does not cover all shifts exactly once"
