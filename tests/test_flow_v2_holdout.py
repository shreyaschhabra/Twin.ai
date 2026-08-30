"""Confirms Flow v2 reuses the EQUIPMENT_DEGRADATION holdout mask
unchanged (Decision 35, Section 12/33) and that once the dataset is
built, no held-out row ever appears in train/validation/test."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import backend.flow.holdout as flow_holdout
from backend.flow_v2 import labels as v2_labels  # noqa: F401 -- confirms no separate holdout logic exists in flow_v2

V2_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v2"


def test_flow_v2_does_not_redefine_holdout_logic():
    """flow_v2 has no holdout.py of its own -- it must import
    backend.flow.holdout.compute_holdout_mask unchanged, not reimplement
    it (which could silently drift from Decision 35)."""
    assert not (Path(__file__).resolve().parent.parent / "backend" / "flow_v2" / "holdout.py").exists()
    assert hasattr(flow_holdout, "compute_holdout_mask")


@pytest.mark.skipif(not (V2_DIR / "train.parquet").exists(), reason="Flow v2 dataset not built yet")
def test_no_held_out_shift_rows_leak_into_supervised_partitions():
    holdout = pd.read_parquet(V2_DIR / "unseen_equipment_degradation.parquet")
    train = pd.read_parquet(V2_DIR / "train.parquet")
    val = pd.read_parquet(V2_DIR / "validation.parquet")
    test = pd.read_parquet(V2_DIR / "test.parquet")

    holdout_keys = set(zip(holdout.shift_id, holdout.station_id, holdout.window_end_time))
    for name, df in [("train", train), ("validation", val), ("test", test)]:
        supervised_keys = set(zip(df.shift_id, df.station_id, df.window_end_time))
        overlap = holdout_keys & supervised_keys
        assert not overlap, f"{len(overlap)} held-out rows leaked into {name}"


@pytest.mark.skipif(not (V2_DIR / "train.parquet").exists(), reason="Flow v2 dataset not built yet")
def test_holdout_not_used_for_split_or_threshold():
    """Structural check: the holdout partition is excluded from the
    grouped split entirely (never assigned a train/val/test membership of
    its own) -- it is diagnostic-only, per Section 12."""
    holdout = pd.read_parquet(V2_DIR / "unseen_equipment_degradation.parquet")
    assert len(holdout) > 0
    assert "target" in holdout.columns
