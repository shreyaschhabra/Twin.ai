"""
Flow chronological train/validation/test split (Step 5, Section L /
continuation Section 4). Shift boundaries are LOCKED before inspecting
where any bottleneck positives fall — they must never be adjusted to
chase target prevalence.

100-shift split:
    TRAIN      SHIFT001-070
    VALIDATION SHIFT071-085
    TEST       SHIFT086-100
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd


@dataclass(frozen=True)
class SplitDefinition:
    train_shifts: List[str]
    validation_shifts: List[str]
    test_shifts: List[str]


def locked_100_shift_split() -> SplitDefinition:
    return SplitDefinition(
        train_shifts=[f"SHIFT{i:03d}" for i in range(1, 71)],
        validation_shifts=[f"SHIFT{i:03d}" for i in range(71, 86)],
        test_shifts=[f"SHIFT{i:03d}" for i in range(86, 101)],
    )


def locked_24_shift_split() -> SplitDefinition:
    """The Step-4/5 development-scale split (16/4/4), kept for the
    24-shift audit dataset — never used for the 100-shift modeling set."""
    return SplitDefinition(
        train_shifts=[f"SHIFT{i:03d}" for i in range(1, 17)],
        validation_shifts=[f"SHIFT{i:03d}" for i in range(17, 21)],
        test_shifts=[f"SHIFT{i:03d}" for i in range(21, 25)],
    )


def validate_split(split: SplitDefinition) -> None:
    train, val, test = set(split.train_shifts), set(split.validation_shifts), set(split.test_shifts)
    assert not (train & val), "train/validation overlap"
    assert not (val & test), "validation/test overlap"
    assert not (train & test), "train/test overlap"
    assert len(split.train_shifts) == len(train), "duplicate shift in train"
    assert len(split.validation_shifts) == len(val), "duplicate shift in validation"
    assert len(split.test_shifts) == len(test), "duplicate shift in test"

    def _idx(shift_id: str) -> int:
        return int(shift_id[5:])

    assert max(_idx(s) for s in split.train_shifts) < min(_idx(s) for s in split.validation_shifts), \
        "train must precede validation chronologically"
    assert max(_idx(s) for s in split.validation_shifts) < min(_idx(s) for s in split.test_shifts), \
        "validation must precede test chronologically"


def apply_split(df: pd.DataFrame, split: SplitDefinition) -> dict:
    validate_split(split)
    return {
        "train": df[df.shift_id.isin(split.train_shifts)].copy(),
        "validation": df[df.shift_id.isin(split.validation_shifts)].copy(),
        "test": df[df.shift_id.isin(split.test_shifts)].copy(),
    }
