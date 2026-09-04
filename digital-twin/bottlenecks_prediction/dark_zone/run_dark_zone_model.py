from __future__ import annotations

import argparse
from pathlib import Path

from dark_zone_model_adapter import run_model_on_csv


def main():
    p = argparse.ArgumentParser(description="Run the frozen bottleneck XGBoost bundle on reconstructed Dark-Zone features.")
    p.add_argument("--features", required=True, help="dark_zone_bottleneck_features_28.csv")
    p.add_argument("--model-bundle", required=True, help="bottleneck_model_bundle.joblib from training")
    p.add_argument("--output", default="dark_zone_bottleneck_predictions.csv")
    p.add_argument("--audit", default="dark_zone_model_inference_audit.json")
    a = p.parse_args()

    pred, audit = run_model_on_csv(a.features, a.model_bundle, a.output, a.audit)
    print(f"Rows predicted: {len(pred)}")
    print(f"Threshold: {audit['threshold']}")
    print(f"Predicted bottlenecks: {audit['positive_predictions']}")
    print(f"Output: {Path(a.output)}")


if __name__ == "__main__":
    main()
