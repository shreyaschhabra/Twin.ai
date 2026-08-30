"""
Flow ablation study — a real, functioning version of what the reference
project's train_bottleneck_xgboost_no_station.py / _ablation.py only
claimed to do (both turned out to be byte-identical to the main training
script and ablate nothing). This one actually removes feature groups and
reports what survives, to characterize how much of our near-perfect
ROC-AUC comes from one dominant signal (inbound_occupancy_ratio, which
alone hits AUC 0.9998) versus genuine multi-feature structure, and
whether station-identity-correlated features are doing hidden work.

Uses the already-saved Dataset C train/validation/test features
(data/processed/flow_v1/) -- no regeneration needed.

Usage:
    python scripts/flow_ablation_study.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.flow.baselines import build_logistic_regression_pipeline
from backend.flow.evaluation import row_level_metrics

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1"

BUFFER_OCCUPANCY_FAMILY = [
    "inbound_occupancy_ratio", "inbound_occupancy_max_5m", "inbound_occupancy_mean_5m",
    "inbound_growth_1m", "inbound_growth_3m", "inbound_growth_5m", "inbound_recent_full",
    "outbound_occupancy_ratio", "outbound_growth_3m",
]
CYCLE_TIME_FAMILY = [
    "last_cycle_time", "cycle_time_mean_1m", "cycle_time_mean_3m", "cycle_time_mean_5m",
    "cycle_time_std_5m", "cycle_time_dev_from_baseline", "cycle_time_dev_relative", "cycle_time_slope_5m",
]
OPERATIONAL_STATE_FAMILY = ["prop_processing_5m", "prop_starved_5m", "prop_blocked_5m", "prop_down_5m"]
STATION_IDENTITY_CORRELATED = ["station_type", "sensor_maturity", "zone"]


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def evaluate(name, num_feats, cat_feats, train, val, test):
    feats = num_feats + cat_feats
    pipe = build_logistic_regression_pipeline(num_feats, cat_feats)
    pipe.fit(train[feats], train.target)
    print(f"\n{name}  ({len(feats)} features: {len(num_feats)} numeric + {len(cat_feats)} categorical)")
    for part_name, df in [("VAL", val), ("TEST", test)]:
        scores = pipe.predict_proba(df[feats])[:, 1]
        m = row_level_metrics(df.target.values, scores, threshold=0.5)
        print(f"  {part_name}: precision={m.precision:.3f} recall={m.recall:.3f} f1={m.f1:.3f} "
              f"PR-AUC={m.pr_auc:.3f} ROC-AUC={m.roc_auc:.3f}")


def main():
    with (OUT_DIR / "dataset_manifest.json").open() as f:
        manifest = json.load(f)
    active_numeric = manifest["numeric_features"]
    active_categorical = manifest["categorical_features"]

    train = pd.read_parquet(OUT_DIR / "train.parquet")
    val = pd.read_parquet(OUT_DIR / "validation.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")

    section("ABLATION STUDY -- what survives when the dominant/identity-correlated signals are removed")
    print("Motivation: the trivial shortcut audit found inbound_occupancy_ratio ALONE achieves "
          "AUC 0.9998, and positive-class diversity is extremely low (TEST's 16 positive rows are "
          "only 4 episodes at 2 stations: S21, S22). This checks how much of that near-perfect "
          "discrimination survives once the most obviously-informative and station-identity-linked "
          "signals are removed.")

    evaluate("FULL (all active features)", active_numeric, active_categorical, train, val, test)
    evaluate("WITHOUT buffer/occupancy family",
             [c for c in active_numeric if c not in BUFFER_OCCUPANCY_FAMILY], active_categorical,
             train, val, test)
    evaluate("WITHOUT categorical (station_type/sensor_maturity/zone)",
             active_numeric, [], train, val, test)
    evaluate("WITHOUT buffer/occupancy AND categorical",
             [c for c in active_numeric if c not in BUFFER_OCCUPANCY_FAMILY], [],
             train, val, test)
    evaluate("ONLY cycle-time family (+ no categorical)",
             CYCLE_TIME_FAMILY, [], train, val, test)
    evaluate("ONLY operational-state family (+ no categorical)",
             OPERATIONAL_STATE_FAMILY, [], train, val, test)
    evaluate("ONLY buffer/occupancy family (+ no categorical)",
             BUFFER_OCCUPANCY_FAMILY, [], train, val, test)
    evaluate("WITHOUT buffer/occupancy, cycle-time, AND operational-state (remaining families only)",
             [c for c in active_numeric
              if c not in BUFFER_OCCUPANCY_FAMILY + CYCLE_TIME_FAMILY + OPERATIONAL_STATE_FAMILY],
             [], train, val, test)

    section("INTERPRETATION")
    print("If ROC-AUC stays near 1.0 across most of these ablations, that confirms the earlier "
          "finding: near-perfect discrimination is not due to one dominant feature, but because "
          "the few physical bottleneck archetypes present in this dataset (chronically slow, "
          "chronically BLOCKED manual-assembly stations) look obviously different from healthy "
          "operation on almost any feature subset -- which is a statement about positive-class "
          "diversity being too low, not about any single feature leaking the future.")


if __name__ == "__main__":
    main()
