"""Quality intelligence service (Part F): loads the production Quality
artifacts and turns a vehicle's current feature row into a vehicle-level
risk + evidence object."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import lightgbm as lgb
import pandas as pd

ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "quality"

FEATURE_DESCRIPTIONS = {
    "mean_cycle_deviation": "Elevated average process-time deviation across completed stations",
    "max_cycle_deviation": "A completed station ran well outside its expected cycle time",
    "recent_cycle_deviation_3": "Recent stations trending slower than expected",
    "count_slow_visits": "Multiple slow-running station visits so far",
    "waiting_time_total": "Extended buffer/queue exposure earlier in the line",
    "max_standardized_deviation": "A sensor reading deviated sharply from its expected range",
    "count_abnormal_readings": "Multiple abnormal sensor readings recorded",
    "mean_abnormality": "Sustained sensor deviation across the vehicle's history",
    "sensor_coverage": "Limited sensor coverage on this vehicle's route so far",
    "sensor_missingness": "Elevated missing/degraded sensor readings",
    "torque_deviation_max": "Fastening process deviation",
    "dimensional_deviation_max": "Dimensional inspection deviation",
    "paint_environment_deviation_max": "Paint/environmental process deviation",
    "sealing_deviation_max": "Sealing/adhesive process deviation",
    "deviation_trend": "Process deviation trending upward recently",
    "n_batch_contexts_visited": "Multiple material batch contexts involved",
    "cohort_defect_rate_mean": "Associated material cohort requires monitoring",
    "cohort_sample_size_mean": "Limited cohort evidence available",
}

RISK_BUCKET_HIGH = 0.66
RISK_BUCKET_MEDIUM = 0.33


def risk_bucket(risk: float) -> str:
    if risk >= RISK_BUCKET_HIGH:
        return "HIGH"
    if risk >= RISK_BUCKET_MEDIUM:
        return "MEDIUM"
    return "LOW"


class QualityService:
    def __init__(self, artifact_dir: Path = ARTIFACT_DIR):
        self.artifact_dir = Path(artifact_dir)
        self.model = lgb.Booster(model_file=str(self.artifact_dir / "quality_lightgbm_model.txt"))
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

    def score_vehicle(self, row: pd.Series, top_k_evidence: int = 5) -> Dict:
        frame = self._prep(row)
        risk = float(self.model.predict(frame)[0])
        contrib = self.model.predict(frame, pred_contrib=True)[0][:-1]
        contrib_series = pd.Series(contrib, index=self.features).sort_values(key=abs, ascending=False)

        evidence = []
        for feat in contrib_series.head(top_k_evidence).index:
            if contrib_series[feat] <= 0 or feat not in FEATURE_DESCRIPTIONS:
                continue
            evidence.append({
                "station_id": row.get("checkpoint_station_id"),
                "description": FEATURE_DESCRIPTIONS[feat],
            })

        return {
            "quality_risk": round(risk, 4),
            "risk_level": risk_bucket(risk),
            "is_high_risk_alert": risk >= self.threshold,
            "evidence": evidence[: min(5, max(3, len(evidence)))],
        }
