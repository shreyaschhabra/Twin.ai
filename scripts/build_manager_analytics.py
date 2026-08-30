"""
Manager analytics export (Section 45): aggregated Python functions run
once over Dataset C (Flow) / Dataset A (Quality) and saved as one JSON
example for later frontend/API integration. No API.

Usage:
    python scripts/build_manager_analytics.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.analytics.manager_analytics import build_manager_analytics_summary
from backend.config.loader import load_factory_config
from backend.flow_v2.episode_evaluation import evaluate_episodes
from backend.flow_v2.split import locked_flow_v2_split
from backend.intelligence.flow_service import FlowService
from backend.intelligence.quality_service import QualityService

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
DATASET_C = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"
FLOW_PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v2"
QUALITY_PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed" / "quality_v1"
DEMO_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "demo"


def main():
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    events = pd.read_parquet(DATASET_C / "observable" / "events.parquet")
    impacts = pd.read_parquet(FLOW_PROCESSED / "bottleneck_events.parquet")
    flow_test = pd.read_parquet(FLOW_PROCESSED / "test.parquet")
    quality_test = pd.read_parquet(QUALITY_PROCESSED / "test.parquet")

    # recompute lead times fresh from the v2 model + episode evaluator, since
    # flow_v2's training_metadata.json only persists summary recall bands,
    # not the per-episode lead-time list (see scripts/train_flow_v2_model.py).
    flow_service = FlowService()
    flow_test_cast = flow_test.copy()
    for col in flow_service.categorical_features:
        flow_test_cast[col] = pd.Categorical(flow_test_cast[col], categories=flow_service.categorical_levels[col])
    flow_scores = flow_service.model.predict(flow_test_cast[flow_service.features])
    flow_pred = (flow_scores >= flow_service.threshold).astype(int)
    split = locked_flow_v2_split(sorted(events.shift_id.unique(), key=lambda x: int(x[5:])))
    test_impacts = impacts[impacts.shift_id.isin(split.test_shifts)]
    episode_result = evaluate_episodes(flow_test, flow_pred, test_impacts)
    lead_time_list = episode_result.first_warning_lead_times

    quality_service = QualityService()
    quality_scores = quality_test.apply(lambda row: quality_service.score_vehicle(row)["quality_risk"], axis=1).to_numpy()

    summary = build_manager_analytics_summary(
        events_df=events, impacts_df=impacts, flow_rows=flow_test, quality_rows=quality_test,
        quality_risk_scores=quality_scores, lead_times=lead_time_list, config=config,
        data_states=["LIVE"] * 850 + ["INFERRED"] * 120 + ["UNKNOWN"] * 30,  # illustrative distribution, see demo 3 for the real mechanism
    )

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    with (DEMO_DIR / "manager_analytics.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved {DEMO_DIR / 'manager_analytics.json'}")
    print(json.dumps({k: (v if not isinstance(v, dict) or len(v) < 5 else f"{len(v)} entries") for k, v in summary.items()}, indent=2, default=str))


if __name__ == "__main__":
    main()
