"""End-to-end runtime bottleneck pipeline: event -> Light/Dark -> 28 features -> XGBoost.

This file is deliberately thin.  It does not duplicate feature engineering, Dark
Zone particle filters, or XGBoost preprocessing.  It composes the already-tested
components:

    runtime_controller.py
          -> FeaturePacket (same 28 features for LIGHT and DARK)
    bottleneck_model_runtime.py
          -> BottleneckPrediction

The existing Dark-only dark_zone_model_adapter.py remains useful for offline Dark
Zone validation, but is not called here.  Production has exactly ONE XGBoost
inference path for both Light and Dark.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd

# Allow both `python -m runtime.digital_twin_pipeline` and direct script execution.
if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from runtime.runtime_controller import DigitalTwinRuntimeController
from ml.bottleneck_model_runtime import BottleneckModelRuntime, BottleneckPrediction
from runtime.event_source import SequentialEventSource


class DigitalTwinBottleneckPipeline:
    """Persistent live pipeline. Instantiate once, then feed events in time order."""

    def __init__(
        self,
        configured_stations_csv: str | Path,
        units_csv: str | Path,
        dark_zone_dir: str | Path,
        model_bundle_path: str | Path,
        historical_dwell_csv: Optional[str | Path] = None,
        corridor_residence_csv: Optional[str | Path] = None,
        run_id: str = "LIVE",
        prediction_interval_s: float = 60.0,
        corridor_particles: int = 3000,
        dwell_dist: str = "gamma",
        config_prior_scale: float = 1.0,
        random_seed: Optional[int] = None,
    ):
        if random_seed is None:
            digest = hashlib.sha256(str(run_id).encode("utf-8")).digest()
            random_seed = int.from_bytes(digest[:4], "big", signed=False)
        self.controller = DigitalTwinRuntimeController(
            configured_stations_csv=configured_stations_csv,
            units_csv=units_csv,
            dark_zone_dir=dark_zone_dir,
            historical_dwell_csv=historical_dwell_csv,
            corridor_residence_csv=corridor_residence_csv,
            run_id=run_id,
            prediction_interval_s=prediction_interval_s,
            corridor_particles=corridor_particles,
            dwell_dist=dwell_dist,
            config_prior_scale=config_prior_scale,
            random_seed=random_seed,
        )
        self.model = BottleneckModelRuntime(model_bundle_path)

        if self.controller.feature_names != self.model.features:
            raise RuntimeError(
                "Runtime controller and XGBoost model feature contracts differ"
            )

    def route_event(self, event: Mapping[str, Any] | pd.Series):
        """Route one event to feature packets without scoring them yet."""
        return self.controller.process_event(event)

    def route_evidence_event(self, event: Mapping[str, Any]):
        """Route Dark evidence to feature packets without model inference."""
        return self.controller.process_evidence_event(event)

    def route_advance_time(self, timestamp_ms: int):
        """Advance Dark estimators and return due feature packets."""
        return self.controller.advance_time(timestamp_ms)

    def score_packets(self, packets):
        """Batch-score already causally ordered feature packets."""
        return self.model.predict_packets(packets)

    def process_event(
        self, event: Mapping[str, Any] | pd.Series
    ) -> list[BottleneckPrediction]:
        """Consume one station event and return all predictions causally due."""
        return self.score_packets(self.route_event(event))

    def process_evidence_event(
        self, event: Mapping[str, Any]
    ) -> list[BottleneckPrediction]:
        """Consume optional Dark checkpoint evidence and score resulting packets."""
        return self.score_packets(self.route_evidence_event(event))

    def advance_time(self, timestamp_ms: int) -> list[BottleneckPrediction]:
        """Emit/scored Dark PF heartbeats due up to timestamp_ms."""
        return self.score_packets(self.route_advance_time(timestamp_ms))

    def process_source(self, source: SequentialEventSource) -> list[BottleneckPrediction]:
        """Consume any already ordered source through the one live inference path.

        CSV replay, a simulator callback, and a future plant connector all use
        this method.  Source adapters own ordering; this pipeline never performs
        retrospective reordering or feature reconstruction.
        """
        predictions: list[BottleneckPrediction] = []
        for event in source:
            predictions.extend(self.process_event(event))
        return predictions

    def summary(self) -> dict[str, Any]:
        return {
            "topology": self.controller.topology_summary(),
            "model": self.model.model_summary(),
            "integration": {
                "single_shared_xgboost_path": True,
                "dark_zone_model_adapter_used_in_production": False,
                "feature_contract_match": self.controller.feature_names
                == self.model.features,
            },
        }


def run_csv_replay(
    pipeline: DigitalTwinBottleneckPipeline,
    station_events_csv: str | Path,
    output_jsonl: str | Path,
    flush_dark_to_ms: Optional[int] = None,
) -> int:
    """Validation/demo replay. Live deployments should call process_event directly."""
    events = pd.read_csv(station_events_csv)
    output_path = Path(output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in events.itertuples(index=False):
            event = row._asdict()
            for prediction in pipeline.process_event(event):
                handle.write(json.dumps(prediction.as_dict(), ensure_ascii=False) + "\n")
                count += 1

        if flush_dark_to_ms is not None:
            for prediction in pipeline.advance_time(int(flush_dark_to_ms)):
                handle.write(json.dumps(prediction.as_dict(), ensure_ascii=False) + "\n")
                count += 1

    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the integrated Light/Dark Digital Twin bottleneck pipeline."
    )
    parser.add_argument("--configured-stations", type=Path, required=True)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--dark-zone-dir", type=Path, required=True)
    parser.add_argument("--model-bundle", type=Path, required=True)
    parser.add_argument("--historical-dwell", type=Path)
    parser.add_argument("--corridor-residence", type=Path)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--run-id", default="LIVE")
    parser.add_argument("--prediction-interval-s", type=float, default=60.0)
    parser.add_argument("--corridor-particles", type=int, default=3000)
    parser.add_argument("--flush-dark-to-ms", type=int)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    pipeline = DigitalTwinBottleneckPipeline(
        configured_stations_csv=args.configured_stations,
        units_csv=args.units,
        dark_zone_dir=args.dark_zone_dir,
        model_bundle_path=args.model_bundle,
        historical_dwell_csv=args.historical_dwell,
        corridor_residence_csv=args.corridor_residence,
        run_id=args.run_id,
        prediction_interval_s=args.prediction_interval_s,
        corridor_particles=args.corridor_particles,
    )

    if args.print_summary:
        print(json.dumps(pipeline.summary(), indent=2))

    count = run_csv_replay(
        pipeline,
        args.events,
        args.output_jsonl,
        flush_dark_to_ms=args.flush_dark_to_ms,
    )
    print(f"Predictions written: {count}")
    print(args.output_jsonl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
