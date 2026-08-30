"""Tests for the final Quality LightGBM artifact (Section 49)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "quality"

pytestmark = pytest.mark.skipif(
    not (ARTIFACT_DIR / "quality_lightgbm_model.txt").exists(), reason="Quality model artifact not built yet"
)


def test_quality_model_loads_and_predicts():
    from backend.intelligence.quality_service import QualityService
    service = QualityService()
    test = pd.read_parquet(Path(__file__).resolve().parent.parent / "data" / "processed" / "quality_v1" / "test.parquet")
    row = test.iloc[0]
    result = service.score_vehicle(row)
    assert 0.0 <= result["quality_risk"] <= 1.0
    assert result["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert isinstance(result["evidence"], list)


def test_quality_threshold_saved_and_valid():
    with (ARTIFACT_DIR / "threshold.json").open() as f:
        data = json.load(f)
    assert 0.0 <= data["frozen_threshold"] <= 1.0


def test_quality_training_metadata_has_required_fields():
    with (ARTIFACT_DIR / "training_metadata.json").open() as f:
        meta = json.load(f)
    for key in ["model_type", "source_dataset", "validation_metrics", "test_metrics", "early_detection", "known_limitations"]:
        assert key in meta


def test_early_detection_percentage_is_plausible():
    with (ARTIFACT_DIR / "training_metadata.json").open() as f:
        meta = json.load(f)
    pct = meta["early_detection"]["pct_defective_detected_before_qc"]
    assert 0.0 <= pct <= 100.0
