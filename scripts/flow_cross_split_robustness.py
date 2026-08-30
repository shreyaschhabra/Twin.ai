"""
Cross-split robustness check (Step 5 rigor pass), borrowed from the
reference project's cross_run_robustness.py idea: a StratifiedGroupKFold
over simulation runs, with an explicit no-run-leakage assertion, to see
how much reported metrics vary across different held-out partitions
rather than trusting a single fixed split.

Our analogue: group by SHIFT (not run -- we have one long dataset, not
many independent runs), stratified so each fold's test set gets a
comparable share of the ~14 shifts that contain any positive row. This
directly answers "how much would our TRAIN/VAL/TEST numbers have looked
different under a different, equally-valid shift partition" -- the
locked production split (SHIFT001-070/071-085/086-100) stays untouched;
this is a diagnostic only, reusing the already-saved features (no
regeneration).

Usage:
    python scripts/flow_cross_split_robustness.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from backend.flow.baselines import build_logistic_regression_pipeline, fit_rule_thresholds, apply_rule
from backend.flow.evaluation import row_level_metrics

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1"
N_FOLDS = 5
SEED = 20240002


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def stratified_shift_folds(shift_ids_with_positive, all_shift_ids, n_folds, rng):
    """Distributes positive-containing shifts as evenly as possible across
    folds first, then fills remaining (all-negative) shifts, mirroring
    StratifiedGroupKFold's intent without pulling in sklearn's
    group-aware CV (which doesn't stratify by a separate label directly)."""
    pos_shifts = list(shift_ids_with_positive)
    rng.shuffle(pos_shifts)
    other_shifts = [s for s in all_shift_ids if s not in shift_ids_with_positive]
    rng.shuffle(other_shifts)

    folds = [[] for _ in range(n_folds)]
    for i, s in enumerate(pos_shifts):
        folds[i % n_folds].append(s)
    for i, s in enumerate(other_shifts):
        folds[i % n_folds].append(s)
    return folds


def main():
    t_start = time.time()
    import json
    with (OUT_DIR / "dataset_manifest.json").open() as f:
        manifest = json.load(f)
    active_numeric = manifest["numeric_features"]
    active_categorical = manifest["categorical_features"]
    active_features = active_numeric + active_categorical

    train = pd.read_parquet(OUT_DIR / "train.parquet")
    val = pd.read_parquet(OUT_DIR / "validation.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")
    pool = pd.concat([train, val, test], ignore_index=True)
    print(f"Combined supervised pool (all 100 shifts, degradation holdout already excluded upstream): {len(pool):,} rows")

    all_shifts = sorted(pool.shift_id.unique())
    positive_shifts = sorted(pool[pool.target == 1].shift_id.unique())
    print(f"Total shifts: {len(all_shifts)}, shifts with >=1 positive row: {len(positive_shifts)} -> {positive_shifts}")

    rng = np.random.RandomState(SEED)
    folds = stratified_shift_folds(positive_shifts, all_shifts, N_FOLDS, rng)

    section(f"{N_FOLDS}-FOLD CROSS-SPLIT ROBUSTNESS (shift-level, stratified by positive-containing shifts)")
    fold_metrics = []
    for k in range(N_FOLDS):
        test_shifts = set(folds[k])
        train_shifts = set(all_shifts) - test_shifts
        assert not (test_shifts & train_shifts), "fold leakage detected"

        fold_train = pool[pool.shift_id.isin(train_shifts)]
        fold_test = pool[pool.shift_id.isin(test_shifts)]
        n_pos_train = (fold_train.target == 1).sum()
        n_pos_test = (fold_test.target == 1).sum()
        n_pos_shifts_test = fold_test[fold_test.target == 1].shift_id.nunique()

        if n_pos_train == 0 or fold_test.target.nunique() < 2:
            print(f"Fold {k}: skipped (train_pos={n_pos_train}, test has both classes: {fold_test.target.nunique() >= 2})")
            continue

        pipe = build_logistic_regression_pipeline(active_numeric, active_categorical)
        pipe.fit(fold_train[active_features], fold_train.target)
        scores = pipe.predict_proba(fold_test[active_features])[:, 1]
        m = row_level_metrics(fold_test.target.values, scores, threshold=0.5)

        thresholds = fit_rule_thresholds(fold_train)
        rule_pred = apply_rule(fold_test, thresholds)
        rule_m = row_level_metrics(fold_test.target.values, rule_pred.astype(float), threshold=0.5)

        print(f"Fold {k}: test_shifts={len(test_shifts)} test_pos_rows={n_pos_test} test_pos_shifts={n_pos_shifts_test}")
        print(f"  logreg: precision={m.precision:.3f} recall={m.recall:.3f} PR-AUC={m.pr_auc:.3f} ROC-AUC={m.roc_auc:.3f}")
        print(f"  rule:   precision={rule_m.precision:.3f} recall={rule_m.recall:.3f} PR-AUC={rule_m.pr_auc:.3f}")
        fold_metrics.append({
            "fold": k, "n_pos_test": n_pos_test, "n_pos_shifts_test": n_pos_shifts_test,
            "logreg_precision": m.precision, "logreg_recall": m.recall,
            "logreg_pr_auc": m.pr_auc, "logreg_roc_auc": m.roc_auc,
            "rule_precision": rule_m.precision, "rule_recall": rule_m.recall, "rule_pr_auc": rule_m.pr_auc,
        })

    section("AGGREGATE ACROSS FOLDS")
    fdf = pd.DataFrame(fold_metrics)
    if len(fdf):
        for col in ["logreg_precision", "logreg_recall", "logreg_pr_auc", "logreg_roc_auc",
                    "rule_precision", "rule_recall", "rule_pr_auc"]:
            print(f"  {col}: mean={fdf[col].mean():.3f} std={fdf[col].std():.3f} "
                  f"min={fdf[col].min():.3f} max={fdf[col].max():.3f}")
        print(f"\nCompare to the single locked-split (SHIFT086-100) TEST numbers: "
              f"logreg precision=0.050 recall=1.000 PR-AUC=0.112 ROC-AUC=1.000")
        print("Large fold-to-fold spread here means the locked split's single TEST number is not "
              "a reliable point estimate of how this model would perform on a differently-drawn "
              "held-out set -- it reflects the specific, small number of episodes that happened "
              "to land in SHIFT086-100, not a stable property of the model.")
    else:
        print("No valid folds (all had too few positives) -- cannot report cross-split variance.")

    print(f"\nTotal runtime: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
