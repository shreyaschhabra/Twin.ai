"""Flow-v3 intelligence service (Section 36 frontend contract): the single
runtime entry point turning a station's public event history into the
`flowAssessment` object the frontend expects. Reuses the exact same
`build_observation_features` function the offline corpus was built with
(Section 31 parity) -- this module supplies the runtime call site, not a
second feature implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import lightgbm as lgb
import pandas as pd

from backend.config.schemas import FactoryConfig
from backend.flow_v3.observations import build_observation_features
from backend.flow_v3.queue_projection import project_queue_risk
from backend.observability.policy import PublicEvent, public_events_as_of

ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "flow_v3"


class FlowV3Service:
    def __init__(self, artifact_dir: Path = ARTIFACT_DIR):
        self.artifact_dir = Path(artifact_dir)
        self.model = lgb.Booster(model_file=str(self.artifact_dir / "flow_v3_lightgbm_model.txt"))
        with (self.artifact_dir / "flow_v3_model_contract.json").open() as f:
            self.contract = json.load(f)
        self.feature_order = self.contract["feature_order"]
        self.categorical_features = self.contract["categorical_features"]
        self.categorical_levels = self.contract["categorical_levels"]
        operational_path = self.artifact_dir / "flow_v3_operational_evaluation.json"
        self.threshold_crossed_ratio = (
            json.loads(operational_path.read_text())["frozen_ratio_threshold"]
            if operational_path.exists() else 0.75
        )

    def _predict_service_rate(self, features: Dict) -> float:
        frame = pd.DataFrame([features])
        for feature in self.categorical_features:
            frame[feature] = pd.Categorical(frame[feature], categories=self.categorical_levels[feature])
        return float(self.model.predict(frame[self.feature_order])[0])

    def _evidence(self, features: Dict, top_k: int = 5) -> List[Dict]:
        frame = pd.DataFrame([features])
        for feature in self.categorical_features:
            frame[feature] = pd.Categorical(frame[feature], categories=self.categorical_levels[feature])
        contrib = self.model.predict(frame[self.feature_order], pred_contrib=True)[0][:-1]
        contrib_series = pd.Series(contrib, index=self.feature_order).sort_values(key=abs, ascending=False)
        evidence = []
        for feature in contrib_series.head(top_k).index:
            if feature in self.categorical_features:
                continue
            evidence.append({
                "feature": feature, "value": features.get(feature),
                "effect": "decreases_predicted_service_rate" if contrib_series[feature] < 0 else "increases_predicted_service_rate",
                "group": "ML_PRECURSOR_EVIDENCE",
            })
        return evidence

    def score_station(
        self,
        *,
        public_events_upto_t: List[PublicEvent],
        station_id: str,
        observation_time: float,
        config: FactoryConfig,
        current_occupancy: int,
        buffer_capacity: int,
        arrival_rate_vph: float,
        service_rate_std_vph: float = 0.0,
    ) -> Dict:
        """`current_occupancy`/`buffer_capacity`/`arrival_rate_vph` are
        physics-layer inputs the caller supplies from live buffer state --
        never derived here, and never fed to the ML model (Section 18)."""
        visible = public_events_as_of(public_events_upto_t, observation_time)
        features = build_observation_features(
            public_events_upto_t=visible, station_id=station_id,
            observation_time=observation_time, config=config,
        )
        lgb_pred = self._predict_service_rate(features)
        recent_service = features["baseline_cycle_time_seconds"] and (3600.0 / features["baseline_cycle_time_seconds"]) / features.get("svc_cycle_time_ratio_to_baseline", 1.0) if features.get("svc_cycle_time_ratio_to_baseline") else lgb_pred
        predicted_service_rate = 0.6 * lgb_pred + 0.4 * recent_service
        
        projection = project_queue_risk(
            current_occupancy=current_occupancy, buffer_capacity=buffer_capacity,
            arrival_rate_vph=arrival_rate_vph, predicted_service_rate_vph=predicted_service_rate,
            service_rate_std_vph=service_rate_std_vph, seed=int(observation_time),
        )
        threshold_crossed = predicted_service_rate < features["baseline_cycle_time_seconds"] and (
            (3600.0 / features["baseline_cycle_time_seconds"]) > 0
            and predicted_service_rate / (3600.0 / features["baseline_cycle_time_seconds"]) < self.threshold_crossed_ratio
        )

        physics_evidence = [
            {"description": f"arrival rate = {arrival_rate_vph:.1f} veh/hr", "group": "PHYSICS_EVIDENCE"},
            {"description": f"predicted service rate = {predicted_service_rate:.1f} veh/hr", "group": "PHYSICS_EVIDENCE"},
            {"description": f"service deficit = {projection.service_deficit_vph:.1f} veh/hr", "group": "PHYSICS_EVIDENCE"},
            {"description": f"buffer = {current_occupancy}/{buffer_capacity}", "group": "PHYSICS_EVIDENCE"},
        ]

        return {
            "stationId": station_id,
            "flowAssessment": {
                "riskLevel": projection.risk_level,
                "thresholdCrossed": threshold_crossed,
                # not an early warning if congestion is already underway --
                # callers with regime state should further gate this.
                "actionableWarning": threshold_crossed and projection.risk_level != "NORMAL",
                "predictedOnsetMin": projection.as_dict()["predictedOnsetMin"],
                "predictedOnsetMax": projection.as_dict()["predictedOnsetMax"],
                "currentServiceRate": None,  # left to the caller: requires the most recent measured/observed rate
                "predictedServiceRate": round(predicted_service_rate, 2),
                "arrivalRate": arrival_rate_vph,
                "serviceDeficit": round(projection.service_deficit_vph, 2),
            },
            "cycleTime": features.get("svc_recent_cycle_time_seconds"),
            "baselineCycleTime": features["baseline_cycle_time_seconds"],
            "bufferOccupancy": current_occupancy,
            "bufferCapacity": buffer_capacity,
            "evidence": self._evidence(features) + physics_evidence,
        }
