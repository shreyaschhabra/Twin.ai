"""
Builds the Flow v2 processed dataset (Section 31): consequence-based
labels, deduplicated rows, mechanism-aware grouped split. Reuses the
existing ~43 point-in-time features (backend.flow.features) and the
EQUIPMENT_DEGRADATION holdout mask (backend.flow.holdout) unchanged.

Saves data/processed/flow_v2/{train,validation,test,
unseen_equipment_degradation,bottleneck_events}.parquet +
feature_manifest.json + dataset_manifest.json + split_manifest.json.

Usage:
    python scripts/build_flow_v2_dataset.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.feature_manifest import FEATURE_MANIFEST
from backend.flow.features import build_features
from backend.flow.holdout import compute_holdout_mask
from backend.flow.pipeline import build_station_minute_grid
from backend.flow_v2.labels import label_rows_v2
from backend.flow_v2.sampling import deduplicate_rows, deduplication_report
from backend.flow_v2.split import locked_flow_v2_split, validate_split
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v2"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    t0 = time.time()
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")
    events = pd.read_parquet(BASE / "observable" / "events.parquet")
    scenario_truth = pd.read_parquet(BASE / "latent" / "scenario_truth.parquet")

    section("1. BOTTLENECK EVENTS + LABELS v2")
    impacts = detect_bottleneck_events(events, config)
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)
    labeled = label_rows_v2(grid, impacts, events)
    raw_candidate_rows = len(grid)
    print(f"Raw candidate rows: {raw_candidate_rows:,}")
    print(labeled.label.value_counts())

    eligible = labeled[labeled.label.isin(["POSITIVE", "NEGATIVE"])].copy()
    print(f"Eligible (pre-dedup, pre-already-full-exclusion): {len(eligible):,}")

    section("2. FEATURES (unchanged point-in-time builder)")
    t_feat = time.time()
    featured = build_features(eligible[["shift_id", "station_id", "window_end_time"]], events, config, sensor_models)
    print(f"Feature build time: {time.time()-t_feat:.1f}s")
    eligible = eligible.merge(featured, on=["shift_id", "station_id", "window_end_time"])

    section("3. ALREADY-FULL EXCLUSION -- DELIBERATELY NOT APPLIED (see rationale below)")
    n_already_full = 0
    print(
        "An occupancy-ratio-based 'already full' exclusion was implemented and tested "
        "(backend/flow_v2/labels.py::apply_already_full_exclusion) but is NOT applied in this "
        "pipeline: running it revealed it discarded ~79% of all positive rows (2320 -> ~490), "
        "because this factory's small integer-valued buffer capacities (4-5 slots) mean a buffer "
        "commonly sits at 100% occupancy for a genuine, non-trivial stretch of time before the "
        "formal BLOCKED state transition registers -- i.e. 'buffer already full' and 'target "
        "bottleneck already ACTIVE' describe the same underlying situation here, not two "
        "independent conditions. The ACTIVE exclusion below (using the true, precise impact-event "
        "boundaries, not an occupancy proxy) already implements this requirement correctly and "
        "completely. Applying the occupancy-based version on top would have discarded legitimate "
        "short-lead-time precursor rows that Section 5 explicitly says to keep "
        "('allow positive precursor states across the whole next-10-minute horizon')."
    )

    section("4. TEMPORAL DEDUPLICATION (label-blind)")
    before_dedup = len(eligible)
    deduped = deduplicate_rows(eligible)
    report = deduplication_report(before_dedup, len(deduped))
    print(json.dumps(report, indent=2))
    print(f"Positives before dedup: {(eligible.target==1).sum()}, after: {(deduped.target==1).sum()} "
          f"(dedup must not have dropped positives disproportionately, since it never reads the label)")

    section("5. EQUIPMENT_DEGRADATION HOLDOUT (Decision 35, unchanged)")
    holdout_mask = compute_holdout_mask(deduped, scenario_truth)
    supervised = deduped[~holdout_mask].copy()
    holdout = deduped[holdout_mask].copy()
    print(f"Held-out rows: {len(holdout):,}; supervised rows: {len(supervised):,}")

    section("6. GROUPED SPLIT")
    all_shifts = sorted(events.shift_id.unique(), key=lambda x: int(x[5:]))
    split = locked_flow_v2_split(all_shifts)
    validate_split(split, all_shifts)
    train = supervised[supervised.shift_id.isin(split.train_shifts)].copy()
    val = supervised[supervised.shift_id.isin(split.validation_shifts)].copy()
    test = supervised[supervised.shift_id.isin(split.test_shifts)].copy()
    for name, df in [("TRAIN", train), ("VALIDATION", val), ("TEST", test)]:
        print(f"{name}: rows={len(df):,} positives={(df.target==1).sum()} "
              f"positive_shifts={df[df.target==1].shift_id.nunique()} "
              f"episodes={df[df.target==1].impact_event_id.nunique()}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train.to_parquet(OUT_DIR / "train.parquet", index=False)
    val.to_parquet(OUT_DIR / "validation.parquet", index=False)
    test.to_parquet(OUT_DIR / "test.parquet", index=False)
    holdout.to_parquet(OUT_DIR / "unseen_equipment_degradation.parquet", index=False)
    impacts.to_parquet(OUT_DIR / "bottleneck_events.parquet", index=False)

    with (OUT_DIR / "feature_manifest.json").open("w") as f:
        json.dump(FEATURE_MANIFEST, f, indent=2)

    from backend.flow.baselines import CATEGORICAL_FEATURES, NUMERIC_FEATURES
    dataset_manifest = {
        "source_dataset": "historical_100_flow_calibrated (Dataset C, unchanged raw simulator events)",
        "formulation": "flow_v2: consequence-based, full 10-minute precursor window (see backend/flow_v2/labels.py)",
        "sampling_method": "60s station-minute grid (reused from v1) + label-blind temporal deduplication",
        "deduplication_report": report,
        "already_full_excluded": int(n_already_full),
        "split": {"train_shifts": split.train_shifts, "validation_shifts": split.validation_shifts, "test_shifts": split.test_shifts},
        "row_counts": {"train": len(train), "validation": len(val), "test": len(test),
                       "unseen_equipment_degradation": len(holdout), "bottleneck_events": len(impacts)},
        "positive_counts": {"train": int((train.target == 1).sum()), "validation": int((val.target == 1).sum()),
                             "test": int((test.target == 1).sum())},
        "n_features": len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES),
        "numeric_features": NUMERIC_FEATURES, "categorical_features": CATEGORICAL_FEATURES,
        "metadata_only_columns": ["shift_id", "station_id", "window_end_time", "label", "target",
                                   "impact_event_id", "time_to_impact_seconds"],
        "generation_seconds": time.time() - t0,
    }
    with (OUT_DIR / "dataset_manifest.json").open("w") as f:
        json.dump(dataset_manifest, f, indent=2)

    with (OUT_DIR / "split_manifest.json").open("w") as f:
        json.dump({
            "run_group_unit": "shift_id",
            "train_shifts": split.train_shifts, "validation_shifts": split.validation_shifts, "test_shifts": split.test_shifts,
            "predeclared_mechanism_allocation": {
                "manual_variation_s21_s22_shifts": 11, "micro_stops_s26_shifts": 2, "mixed_s34_shifts": 1,
                "note": "predeclared using known scenario/impact metadata before any model was trained; see backend/flow_v2/split.py docstring",
            },
        }, f, indent=2)

    print(f"\nSaved to {OUT_DIR}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
