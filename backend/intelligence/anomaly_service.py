"""Anomaly intelligence service (Part F): loads the fitted Isolation
Forest + statistical thresholds and scores a single station row."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import joblib
import pandas as pd

from backend.anomaly.combined import build_anomaly_output
from backend.anomaly.statistical import SIGNAL_FEATURES, Z_THRESHOLD

ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "anomaly"


class AnomalyService:
    def __init__(self, artifact_dir: Path = ARTIFACT_DIR):
        self.artifact_dir = Path(artifact_dir)
        bundle = joblib.load(self.artifact_dir / "isolation_forest.joblib")
        self.pipe = bundle["pipe"]
        self.features = bundle["features"]
        with (self.artifact_dir / "metadata.json").open() as f:
            self.metadata = json.load(f)
        self.baselines = self.metadata.get("feature_baselines", {})

    def score_station(self, station_id: str, row: pd.Series) -> Dict:
        import numpy as np
        frame = pd.DataFrame([row[self.features]])
        raw = -self.pipe.named_steps["iforest"].decision_function(self.pipe.named_steps["impute"].transform(frame))
        iforest_score = float(1.0 / (1.0 + np.exp(-raw[0] * 3.0)))

        signals = []
        z_like_scores = []
        for feat, label in SIGNAL_FEATURES.items():
            if feat not in row or feat not in self.baselines:
                continue
            base = self.baselines[feat]
            std = base.get("std") or 1.0
            z = abs((row[feat] - base.get("mean", 0.0)) / std) if std else 0.0
            z_like_scores.append(z)
            if z > Z_THRESHOLD:
                signals.append(label)
        statistical_score = min(1.0, (max(z_like_scores) / 10.0)) if z_like_scores else 0.0

        return build_anomaly_output(station_id, statistical_score, iforest_score, signals)
