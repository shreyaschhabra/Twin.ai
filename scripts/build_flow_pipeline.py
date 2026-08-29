"""
Step 5 (minimum viable Flow pipeline): build the full Flow dataset from
Dataset C (data/generated/historical_100_flow_calibrated/) -- features,
holdout, split, a BASIC sanity audit, save -- then run Baseline 0/1/2 and
report row-level + event-level + lead-time + shortcut-audit results.
Dataset C is APPROVED and frozen for Flow despite TEST's 16 positive
rows; no further generator/scenario/scheduler/split changes are made
here regardless of what these results show.

Usage:
    python scripts/build_flow_pipeline.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from backend.config.loader import load_factory_config
from backend.flow.baselines import (
    CATEGORICAL_FEATURES, NUMERIC_FEATURES,
    apply_rule, build_logistic_regression_pipeline, fit_rule_thresholds,
)
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.evaluation import event_level_evaluation, lead_time_summary, row_level_metrics
from backend.flow.feature_manifest import FEATURE_MANIFEST
from backend.flow.features import build_features
from backend.flow.holdout import compute_holdout_mask
from backend.flow.labels import label_rows
from backend.flow.pipeline import build_station_minute_grid
from backend.flow.split import locked_100_shift_split, validate_split
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
RAW_BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"
NATURALISTIC_BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    t_start = time.time()
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")

    events = pd.read_parquet(RAW_BASE / "observable" / "events.parquet")
    scenario_truth = pd.read_parquet(RAW_BASE / "latent" / "scenario_truth.parquet")

    section("1. BOTTLENECK EVENTS + LABELS")
    impacts = detect_bottleneck_events(events, config)
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)
    labeled = label_rows(grid, impacts)
    print(f"Total rows: {len(labeled)}; labels: {dict(labeled.label.value_counts())}")

    section("2. HOLDOUT")
    holdout_mask = compute_holdout_mask(labeled, scenario_truth)
    supervised_labeled = labeled[~holdout_mask].copy()
    robustness_labeled = labeled[holdout_mask].copy()
    print(f"Held-out rows: {len(robustness_labeled)}; supervised rows: {len(supervised_labeled)}")

    section("3. FEATURES (point-in-time, on supervised + holdout rows only — never the excluded active/imminent-only union beyond what's needed)")
    t0 = time.time()
    feat_supervised = build_features(supervised_labeled[["shift_id", "station_id", "window_end_time"]], events, config, sensor_models)
    feat_holdout = build_features(robustness_labeled[["shift_id", "station_id", "window_end_time"]], events, config, sensor_models)
    print(f"Feature build time: {time.time() - t0:.1f}s")

    supervised = supervised_labeled.merge(feat_supervised, on=["shift_id", "station_id", "window_end_time"])
    holdout = robustness_labeled.merge(feat_holdout, on=["shift_id", "station_id", "window_end_time"])

    section("4. SPLIT")
    split = locked_100_shift_split()
    validate_split(split)
    train_full = supervised[supervised.shift_id.isin(split.train_shifts)]
    val_full = supervised[supervised.shift_id.isin(split.validation_shifts)]
    test_full = supervised[supervised.shift_id.isin(split.test_shifts)]
    print(f"train={len(train_full)} val={len(val_full)} test={len(test_full)} holdout={len(holdout)}")

    # primary supervised training tables: only POSITIVE/NEGATIVE rows
    train = train_full[train_full.label.isin(["POSITIVE", "NEGATIVE"])].copy()
    val = val_full[val_full.label.isin(["POSITIVE", "NEGATIVE"])].copy()
    test = test_full[test_full.label.isin(["POSITIVE", "NEGATIVE"])].copy()
    print(f"After excluding ACTIVE/IMMINENT: train={len(train)} val={len(val)} test={len(test)}")
    print(f"Train positives: {(train.target == 1).sum()}, Val positives: {(val.target == 1).sum()}, "
          f"Test positives: {(test.target == 1).sum()}")

    section("5. BASIC FEATURE AUDIT (missingness, constants, exact duplicates, broken values, extreme correlation)")
    removed_features = []
    for col in NUMERIC_FEATURES:
        miss = train[col].isna().mean()
        nunique = train[col].nunique(dropna=True)
        has_inf = np.isinf(train[col].to_numpy(dtype="float64", na_value=np.nan)).any()
        flags = []
        if nunique <= 1:
            flags.append("CONSTANT")
        if miss > 0.5:
            flags.append(f"HIGH_MISSING({miss*100:.1f}%)")
        if has_inf:
            flags.append("CONTAINS_INF")
        if flags:
            print(f"  {col}: nunique={nunique} missing={miss*100:.1f}% flags={flags}")
        if "CONSTANT" in flags or "CONTAINS_INF" in flags:
            removed_features.append((col, ",".join(flags)))

    active_numeric = [c for c in NUMERIC_FEATURES if c not in {c2 for c2, _ in removed_features}]
    corr = train[active_numeric].corr().abs()
    high_corr_pairs = []
    seen_dupe = set()
    for i, a in enumerate(active_numeric):
        for b in active_numeric[i + 1:]:
            v = corr.loc[a, b]
            if pd.notna(v) and v > 0.95:
                high_corr_pairs.append((a, b, round(float(v), 4)))
                if v > 0.9999 and b not in seen_dupe:
                    removed_features.append((b, f"exact_duplicate_of({a})"))
                    seen_dupe.add(b)
    print(f"High-correlation (>0.95) pairs: {high_corr_pairs}")

    active_numeric = [c for c in NUMERIC_FEATURES if c not in {c2 for c2, _ in removed_features}]
    active_categorical = list(CATEGORICAL_FEATURES)
    active_features = active_numeric + active_categorical
    if removed_features:
        print(f"\nREMOVED FEATURES ({len(removed_features)}):")
        for name, reason in removed_features:
            print(f"  - {name}: {reason}")
    else:
        print("\nNo features removed -- audit found no constants, exact duplicates, or broken values in TRAIN.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train.to_parquet(OUT_DIR / "train.parquet", index=False)
    val.to_parquet(OUT_DIR / "validation.parquet", index=False)
    test.to_parquet(OUT_DIR / "test.parquet", index=False)
    holdout.to_parquet(OUT_DIR / "unseen_equipment_degradation.parquet", index=False)
    impacts.to_parquet(OUT_DIR / "bottleneck_events.parquet", index=False)
    with (OUT_DIR / "feature_manifest.json").open("w") as f:
        json.dump(FEATURE_MANIFEST, f, indent=2)

    dataset_manifest = {
        "source_dataset": "historical_100_flow_calibrated (Dataset C, Decision 37/38 approved despite "
                           "TEST's 16 positive rows -- a development sanity guideline, not a hard requirement)",
        "split": {"train_shifts": "SHIFT001-070", "validation_shifts": "SHIFT071-085", "test_shifts": "SHIFT086-100"},
        "row_counts": {
            "train": len(train), "validation": len(val), "test": len(test),
            "unseen_equipment_degradation": len(holdout), "bottleneck_events": len(impacts),
        },
        "positive_counts": {
            "train": int((train.target == 1).sum()), "validation": int((val.target == 1).sum()),
            "test": int((test.target == 1).sum()),
        },
        "n_features": len(active_features),
        "numeric_features": active_numeric,
        "categorical_features": active_categorical,
        "removed_features": [{"name": n, "reason": r} for n, r in removed_features],
    }
    with (OUT_DIR / "dataset_manifest.json").open("w") as f:
        json.dump(dataset_manifest, f, indent=2)

    section("6. BASELINE 0 — ALWAYS NEGATIVE")
    for name, df in [("VALIDATION", val), ("TEST", test)]:
        prevalence = df.target.mean()
        print(f"{name}: accuracy={1-prevalence:.4f} (misleading — recall=0, precision=undefined), prevalence={prevalence:.5f}")

    section("7. BASELINE 1 — OPERATIONAL RULE")
    print("Rule definition: cycle-time deviation elevated AND (buffer occupancy elevated OR "
          "arrivals outpacing departures) -- i.e. "
          "(cycle_time_dev_relative >= p75) AND (inbound_occupancy_ratio >= p75 OR arrival_minus_departure_5m >= p75), "
          "all three p75 thresholds derived from TRAIN only.")
    thresholds = fit_rule_thresholds(train)
    print(f"Thresholds (TRAIN-derived): {thresholds}")
    val_rule_pred = apply_rule(val, thresholds)
    test_rule_pred = apply_rule(test, thresholds)
    for name, df, pred in [("VALIDATION", val, val_rule_pred), ("TEST", test, test_rule_pred)]:
        m = row_level_metrics(df.target.values, pred.astype(float), threshold=0.5)
        print(f"{name} rule: precision={m.precision:.3f} recall={m.recall:.3f} f1={m.f1:.3f} "
              f"prevalence={m.prevalence:.5f}\n  confusion=\n{m.confusion}")

    section("8. BASELINE 2 — LOGISTIC REGRESSION")
    print("Preprocessing: SimpleImputer(median)+StandardScaler for numeric features, "
          "SimpleImputer(most_frequent)+OneHotEncoder(handle_unknown='ignore') for categorical -- "
          "all fitted on TRAIN only via sklearn Pipeline/ColumnTransformer. "
          "LogisticRegression(class_weight='balanced', max_iter=1000). No SMOTE, no hyperparameter sweep.")
    pipe = build_logistic_regression_pipeline(active_numeric, active_categorical)
    pipe.fit(train[active_features], train.target)
    val_scores = pipe.predict_proba(val[active_features])[:, 1]
    test_scores = pipe.predict_proba(test[active_features])[:, 1]
    for name, df, scores in [("VALIDATION", val, val_scores), ("TEST", test, test_scores)]:
        m = row_level_metrics(df.target.values, scores, threshold=0.5)
        print(f"{name} logreg: precision={m.precision:.3f} recall={m.recall:.3f} f1={m.f1:.3f} "
              f"PR-AUC={m.pr_auc:.3f} ROC-AUC={m.roc_auc:.3f} (0.5 threshold shown diagnostically only)\n"
              f"  confusion=\n{m.confusion}")

    section("9. EVENT-LEVEL EVALUATION")
    for name, df, pred in [("VALIDATION (rule)", val, val_rule_pred),
                           ("TEST (rule)", test, test_rule_pred),
                           ("VALIDATION (logreg@0.5)", val, (val_scores >= 0.5).astype(int)),
                           ("TEST (logreg@0.5)", test, (test_scores >= 0.5).astype(int))]:
        res = event_level_evaluation(df, pred, impacts)
        lt = lead_time_summary(res.lead_times)
        detected_counts = [n for n in res.warnings_per_event.values() if n > 0]
        mean_warnings_per_detected_event = (sum(detected_counts) / len(detected_counts)) if detected_counts else float("nan")
        print(f"{name}: events={res.total_events} detected={res.detected_events} "
              f"recall={res.event_recall:.3f} missed={res.missed_events} "
              f"false_warnings/shift={res.false_warnings_per_shift:.3f} "
              f"mean_warnings_per_detected_event={mean_warnings_per_detected_event:.2f}")
        print(f"  lead-time: {lt}")

    section("10. TRIVIAL SHORTCUT AUDIT")
    y = train.target.values
    for col in ["station_id", "zone", "sensor_maturity", "shift_id"]:
        dummies = pd.get_dummies(train[col])
        aucs = []
        for c in dummies.columns:
            try:
                aucs.append(roc_auc_score(y, dummies[c]))
            except ValueError:
                continue
        if aucs:
            best = max(aucs, key=lambda a: abs(a - 0.5))
            print(f"  {col}: best single-category |AUC-0.5| = {abs(best-0.5):.4f} (best AUC={best:.4f})")
    for col in ["inbound_occupancy_ratio", "cycle_time_dev_relative"]:
        try:
            auc = roc_auc_score(y, train[col].fillna(0))
            print(f"  {col} alone -> AUC {auc:.4f}")
        except ValueError:
            pass
    for col in ["mix_ice_sedan_5m", "mix_ice_suv_5m", "mix_ev_5m"]:
        try:
            auc = roc_auc_score(y, train[col].fillna(0))
            print(f"  {col} alone -> AUC {auc:.4f}")
        except ValueError:
            pass

    section("11. UNSEEN EQUIPMENT-DEGRADATION DIAGNOSTIC (read-only, not used for selection)")
    print("UNSEEN-SCENARIO DIAGNOSTIC — NOT USED FOR MODEL SELECTION.")
    if len(holdout) and holdout.target.notna().any():
        holdout_valid = holdout[holdout.label.isin(["POSITIVE", "NEGATIVE"])]
        if len(holdout_valid) and holdout_valid.target.nunique() > 1:
            hd_scores = pipe.predict_proba(holdout_valid[active_features])[:, 1]
            m = row_level_metrics(holdout_valid.target.values, hd_scores, threshold=0.5)
            print(f"  logreg on holdout: precision={m.precision:.3f} recall={m.recall:.3f} "
                  f"PR-AUC={m.pr_auc:.3f} prevalence={m.prevalence:.5f}")
        else:
            print(f"  holdout has {len(holdout_valid)} valid rows, insufficient class variety for a diagnostic score.")
    else:
        print("  no valid (POSITIVE/NEGATIVE) rows in the holdout set to diagnose.")

    section("12. NATURALISTIC CORPUS DIAGNOSTIC (Dataset A, read-only, NOT used for tuning)")
    print("NATURALISTIC CORPUS DIAGNOSTIC — Dataset A is not trained on; this only checks "
          "false-warning behavior of the Dataset-C-trained rule/logreg under naturalistic conditions.")
    try:
        events_a = pd.read_parquet(NATURALISTIC_BASE / "observable" / "events.parquet")
        impacts_a = detect_bottleneck_events(events_a, config)
        grid_a = build_station_minute_grid(events_a, station_ids)
        labeled_a = label_rows(grid_a, impacts_a)
        feat_a = build_features(labeled_a[["shift_id", "station_id", "window_end_time"]], events_a, config, sensor_models)
        full_a = labeled_a.merge(feat_a, on=["shift_id", "station_id", "window_end_time"])
        eval_a = full_a[full_a.label.isin(["POSITIVE", "NEGATIVE"])].copy()

        rule_pred_a = apply_rule(eval_a, thresholds)
        logreg_scores_a = pipe.predict_proba(eval_a[active_features])[:, 1]
        logreg_pred_a = (logreg_scores_a >= 0.5).astype(int)

        for name, pred in [("rule", rule_pred_a), ("logreg@0.5", logreg_pred_a)]:
            res_a = event_level_evaluation(eval_a, pred, impacts_a)
            print(f"  Dataset A / {name}: false_warnings/shift={res_a.false_warnings_per_shift:.3f} "
                  f"(events={res_a.total_events}, detected={res_a.detected_events})")
    except Exception as exc:
        print(f"  Skipped -- {exc}")

    print(f"\nTotal pipeline runtime: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
