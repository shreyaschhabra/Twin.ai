"""
Flow intelligence service (Part F): loads the production Flow artifacts
and turns a single station's current feature row into a station-level
risk + evidence + onset object. No HTTP -- returns plain Python dicts,
JSON-serializable as-is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import lightgbm as lgb
import pandas as pd

from backend.intelligence.onset import estimate_onset_window

ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "flow"


class FlowService:
    def __init__(self, artifact_dir: Path = ARTIFACT_DIR):
        self.artifact_dir = Path(artifact_dir)
        self.model = lgb.Booster(model_file=str(self.artifact_dir / "flow_lightgbm_model.txt"))
        with (self.artifact_dir / "feature_list.json").open() as f:
            fl = json.load(f)
        self.numeric_features = fl["numeric_features"]
        self.categorical_features = fl["categorical_features"]
        self.categorical_levels = fl["categorical_levels"]
        self.features = self.numeric_features + self.categorical_features
        with (self.artifact_dir / "threshold.json").open() as f:
            self.threshold = json.load(f)["frozen_threshold"]

    def _prep(self, row: pd.Series) -> pd.DataFrame:
        frame = pd.DataFrame([row[self.features]])
        for col in self.categorical_features:
            frame[col] = pd.Categorical(frame[col], categories=self.categorical_levels[col])
        return frame

    def score_station(self, row: pd.Series, top_k_evidence: int = 5) -> Dict:
        frame = self._prep(row)
        risk = float(self.model.predict(frame)[0])
        contrib = self.model.predict(frame, pred_contrib=True)[0][:-1]
        contrib_series = pd.Series(contrib, index=self.features).sort_values(key=abs, ascending=False)

        evidence = []
        for feat in contrib_series.head(top_k_evidence).index:
            value = row.get(feat)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = str(value)
            evidence.append({
                "feature": feat, "value": value,
                "effect": "increases_risk" if contrib_series[feat] > 0 else "decreases_risk",
            })

        onset_min, onset_max = None, None
        if all(k in row for k in ("inbound_occupancy_ratio", "arrivals_5m", "completions_5m")):
            onset_min, onset_max = estimate_onset_window(
                current_occupancy=row.get("inbound_occupancy_ratio", 0.0) * 1.0,
                buffer_capacity=1.0,  # ratio-based projection (0-1 scale); station-level absolute capacity is applied by factory_state
                arrivals_per_min=(row.get("arrivals_5m", 0.0) or 0.0) / 5.0,
                departures_per_min=(row.get("completions_5m", 0.0) or 0.0) / 5.0,
            )

        return {
            "bottleneck_risk": round(risk, 4),
            "status": "HIGH_RISK" if risk >= self.threshold else "NORMAL",
            "predicted_onset_min": onset_min,
            "predicted_onset_max": onset_max,
            "evidence": evidence,
        }
