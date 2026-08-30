"""Tests for the final Flow LightGBM artifact (Section 49): loads,
predicts, has a saved threshold, and the event evaluator respects the
300-600s window (delegated to test_flow_event_evaluation.py's dedicated
coverage; re-asserted here against the real saved threshold config)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "flow"

pytestmark = pytest.mark.skipif(
    not (ARTIFACT_DIR / "flow_lightgbm_model.txt").exists(), reason="Flow model artifact not built yet"
)


def test_flow_model_loads_and_predicts():
    from backend.intelligence.flow_service import FlowService
    service = FlowService()
    test = pd.read_parquet(Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1" / "test.parquet")
    row = test.iloc[0]
    result = service.score_station(row)
    assert 0.0 <= result["bottleneck_risk"] <= 1.0
    assert result["status"] in {"HIGH_RISK", "NORMAL"}
    assert isinstance(result["evidence"], list)
    assert len(result["evidence"]) <= 5


def test_flow_threshold_saved_and_valid():
    with (ARTIFACT_DIR / "threshold.json").open() as f:
        data = json.load(f)
    assert 0.0 <= data["frozen_threshold"] <= 1.0
    assert len(data["threshold_grid"]) > 0


def test_flow_training_metadata_has_required_fields():
    with (ARTIFACT_DIR / "training_metadata.json").open() as f:
        meta = json.load(f)
    for key in ["model_type", "code_commit", "source_dataset", "validation_metrics", "test_metrics",
                "anti_shortcut_audit", "known_limitations"]:
        assert key in meta


def test_flow_event_metrics_lead_times_within_bounds():
    with (ARTIFACT_DIR / "training_metadata.json").open() as f:
        meta = json.load(f)
    for partition in ["validation_event_metrics", "test_event_metrics"]:
        lt = meta[partition]["lead_time"]
        if lt.get("count", 0) > 0:
            assert 300 - 1e-3 <= lt["min_lead_time_s"] <= 600 + 1e-3
            assert 300 - 1e-3 <= lt["max_lead_time_s"] <= 600 + 1e-3
