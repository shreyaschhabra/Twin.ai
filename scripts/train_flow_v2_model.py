"""
Flow v2: baselines, final model, full diagnostic suite (Sections 16-30).

Usage:
    python scripts/train_flow_v2_model.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from backend.flow.baselines import build_preprocessor
from backend.flow_v2.episode_evaluation import evaluate_episodes
from backend.flow_v2.split import MANUAL_VARIATION_S21_S22_SHIFTS

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v2"
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "flow_v2"
SEED = 20240002
N_OPTUNA_TRIALS = 15

BUFFER_FAMILY = [
    "inbound_occupancy_ratio", "inbound_occupancy_max_5m", "inbound_occupancy_mean_5m",
    "inbound_growth_1m", "inbound_growth_3m", "inbound_growth_5m", "inbound_recent_full",
    "outbound_occupancy_ratio", "outbound_growth_3m",
]
CYCLE_TIME_FAMILY = [
    "last_cycle_time", "cycle_time_mean_1m", "cycle_time_mean_3m", "cycle_time_mean_5m",
    "cycle_time_std_5m", "cycle_time_dev_from_baseline", "cycle_time_dev_relative", "cycle_time_slope_5m",
]
SINGLE_FEATURES = ["inbound_occupancy_ratio", "cycle_time_dev_relative", "arrival_minus_departure_5m", "inbound_growth_5m"]


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def row_metrics(y_true, y_score, threshold):
    y_pred = (y_score >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, y_score)) if len(set(y_true)) > 1 else None,
        "roc_auc": float(roc_auc_score(y_true, y_score)) if len(set(y_true)) > 1 else None,
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(), "threshold": threshold,
    }


def _pr_auc_feval(preds, dataset):
    labels = dataset.get_label()
    return "pr_auc", average_precision_score(labels, preds), True


def train_lgbm(train, val, features, cat_features, params, scale_pos_weight, seed=SEED):
    full_params = dict(objective="binary", metric="None", verbosity=-1, seed=seed, scale_pos_weight=scale_pos_weight, **params)
    train_set = lgb.Dataset(train[features], label=train.target, categorical_feature=cat_features, free_raw_data=False)
    val_set = lgb.Dataset(val[features], label=val.target, categorical_feature=cat_features, reference=train_set, free_raw_data=False)
    return lgb.train(full_params, train_set, num_boost_round=500, valid_sets=[val_set], feval=_pr_auc_feval,
                      callbacks=[lgb.early_stopping(40, verbose=False, first_metric_only=True), lgb.log_evaluation(0)])


def prep_categoricals(dfs, cat_features, reference_df):
    for col in cat_features:
        cats = pd.Categorical(reference_df[col]).categories
        for df in dfs:
            df[col] = pd.Categorical(df[col], categories=cats)


def main():
    t0 = time.time()
    with (OUT_DIR / "dataset_manifest.json").open() as f:
        manifest = json.load(f)
    numeric_features, categorical_features = manifest["numeric_features"], manifest["categorical_features"]
    features = numeric_features + categorical_features

    train = pd.read_parquet(OUT_DIR / "train.parquet")
    val = pd.read_parquet(OUT_DIR / "validation.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")
    impacts = pd.read_parquet(OUT_DIR / "bottleneck_events.parquet")
    with (OUT_DIR / "split_manifest.json").open() as f:
        split_manifest = json.load(f)
    val_impacts = impacts[impacts.shift_id.isin(split_manifest["validation_shifts"])]
    test_impacts = impacts[impacts.shift_id.isin(split_manifest["test_shifts"])]

    prep_categoricals([train, val, test], categorical_features, train)

    section("0. CLASS RATIO INSPECTION")
    n_pos, n_neg = (train.target == 1).sum(), (train.target == 0).sum()
    ratio = n_neg / max(1, n_pos)
    moderate_weight = np.sqrt(ratio)
    print(f"TRAIN: {n_pos} positives / {n_neg} negatives -> ratio {ratio:.1f}:1")
    print(f"Moderate transparent weight (sqrt(ratio)) = {moderate_weight:.2f} (vs. full inverse-frequency weight {ratio:.1f})")

    section("1. LOGISTIC REGRESSION -- UNWEIGHTED vs. MODERATELY WEIGHTED")
    from sklearn.pipeline import Pipeline
    baseline_pipe = None  # the moderately-weighted one is kept as the saved baseline artifact
    for label, class_weight in [("unweighted", None), (f"moderate (weight~{moderate_weight:.0f}:1)", {0: 1, 1: moderate_weight})]:
        preprocess = build_preprocessor(numeric_features, categorical_features)
        clf = LogisticRegression(class_weight=class_weight, max_iter=1000)
        pipe = Pipeline([("preprocess", preprocess), ("clf", clf)])
        pipe.fit(train[features], train.target)
        for name, df in [("VAL", val), ("TEST", test)]:
            scores = pipe.predict_proba(df[features])[:, 1]
            m = row_metrics(df.target.values, scores, 0.5)
            print(f"  {label} / {name}: precision={m['precision']:.3f} recall={m['recall']:.3f} PR-AUC={m['pr_auc']:.3f}")
        if "moderate" in label:
            baseline_pipe = pipe
    assert baseline_pipe is not None

    section("2. FINAL MODEL -- LIGHTGBM (moderate weighting, PR-AUC early stopping, Optuna tuning)")
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 15, 95),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 150),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": 1,
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        }
        model = train_lgbm(train, val, features, categorical_features, params, moderate_weight)
        return average_precision_score(val.target, model.predict(val[features]))

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(objective, n_trials=N_OPTUNA_TRIALS, show_progress_bar=False)
    print(f"Best trial PR-AUC={study.best_value:.4f}, params={study.best_params}")

    final_model = train_lgbm(train, val, features, categorical_features, study.best_params, moderate_weight)
    print(f"best_iteration={final_model.best_iteration}")
    val_scores = final_model.predict(val[features])
    test_scores = final_model.predict(test[features])

    section("3. THRESHOLD SELECTION (VALIDATION ONLY, F2 subject to false-warning cap)")
    FALSE_WARNING_CAP_PER_SHIFT = 30.0
    grid = np.round(np.arange(0.02, 0.96, 0.02), 3)
    threshold_rows = []
    for thr in grid:
        m = row_metrics(val.target.values, val_scores, thr)
        pred = (val_scores >= thr).astype(int)
        ep = evaluate_episodes(val, pred, val_impacts)
        f2 = (5 * m["precision"] * m["recall"] / (4 * m["precision"] + m["recall"])) if (m["precision"] + m["recall"]) > 0 else 0.0
        threshold_rows.append({"threshold": float(thr), "precision": m["precision"], "recall": m["recall"], "f2": f2,
                                "false_warnings_per_shift": ep.false_warnings_per_shift, "any_warning_recall": ep.any_warning_recall})
    within_cap = [r for r in threshold_rows if r["false_warnings_per_shift"] <= FALSE_WARNING_CAP_PER_SHIFT]
    chosen_pool = within_cap if within_cap else threshold_rows
    best_row = max(chosen_pool, key=lambda r: r["f2"])
    frozen_threshold = best_row["threshold"]
    print(f"False-warning cap: {FALSE_WARNING_CAP_PER_SHIFT}/shift ({'applied' if within_cap else 'NO threshold satisfied it -- cap relaxed, documented'})")
    print(f"FROZEN THRESHOLD = {frozen_threshold} -> precision={best_row['precision']:.3f} recall={best_row['recall']:.3f} "
          f"f2={best_row['f2']:.3f} false_warn/shift={best_row['false_warnings_per_shift']:.2f}")

    section("4. VALIDATION / TEST ROW METRICS AT FROZEN THRESHOLD")
    val_row_m = row_metrics(val.target.values, val_scores, frozen_threshold)
    test_row_m = row_metrics(test.target.values, test_scores, frozen_threshold)
    print("VALIDATION:", json.dumps(val_row_m, indent=2))
    print("TEST:", json.dumps(test_row_m, indent=2))

    section("5. EPISODE-LEVEL EVALUATION (any-warning / 5-10min / 0-5min)")
    val_pred = (val_scores >= frozen_threshold).astype(int)
    test_pred = (test_scores >= frozen_threshold).astype(int)
    val_ep = evaluate_episodes(val, val_pred, val_impacts)
    test_ep = evaluate_episodes(test, test_pred, test_impacts)
    for name, ep in [("VALIDATION", val_ep), ("TEST", test_ep)]:
        print(f"{name}: episodes={ep.total_episodes} any_warning_recall={ep.any_warning_recall:.3f} "
              f"5-10min_recall={ep.band_5_10_min_recall:.3f} 0-5min_recall={ep.band_0_5_min_recall:.3f} "
              f"missed={ep.missed_episodes} false_warnings/shift={ep.false_warnings_per_shift:.2f}")
        if ep.first_warning_lead_times:
            arr = np.array(ep.first_warning_lead_times)
            print(f"  lead times: mean={arr.mean():.1f}s median={np.median(arr):.1f}s min={arr.min():.1f}s max={arr.max():.1f}s")

    section("6. TEST METRICS PER GROUP (per test shift with positives) + pooled")
    per_group = []
    for shift_id in sorted(test[test.target == 1].shift_id.unique(), key=lambda x: int(x[5:])):
        g = test[test.shift_id == shift_id]
        if g.target.nunique() < 2:
            continue
        scores_g = final_model.predict(g[features])
        m = row_metrics(g.target.values, scores_g, frozen_threshold)
        per_group.append({"shift_id": shift_id, "rows": len(g), "positives": int((g.target == 1).sum()),
                           "prevalence": float((g.target == 1).mean()), **m})
        print(f"  {shift_id}: rows={len(g)} positives={int((g.target==1).sum())} "
              f"prevalence={(g.target==1).mean()*100:.3f}% PR-AUC={m['pr_auc']} precision={m['precision']:.3f} recall={m['recall']:.3f}")
    print(f"POOLED TEST: {json.dumps(test_row_m, indent=2)}")

    section("7. GROUPED CROSS-RUN ROBUSTNESS (StratifiedGroupKFold, groups=shift_id)")
    pool = pd.concat([train, val, test], ignore_index=True)
    prep_categoricals([pool], categorical_features, train)
    n_groups_with_pos = pool[pool.target == 1].shift_id.nunique()
    n_splits = min(5, n_groups_with_pos) if n_groups_with_pos >= 2 else 0
    fold_metrics = []
    if n_splits >= 2:
        sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
        for fold, (train_idx, test_idx) in enumerate(sgkf.split(pool, pool.target, groups=pool.shift_id)):
            fold_train, fold_test = pool.iloc[train_idx], pool.iloc[test_idx]
            assert not (set(fold_train.shift_id) & set(fold_test.shift_id)), "GroupKFold leakage detected"
            if fold_test.target.nunique() < 2 or (fold_train.target == 1).sum() < 3:
                continue
            m = train_lgbm(fold_train, fold_test, features, categorical_features, study.best_params, moderate_weight)
            scores = m.predict(fold_test[features])
            rm = row_metrics(fold_test.target.values, scores, 0.5)
            fold_metrics.append(rm)
            print(f"  fold {fold}: PR-AUC={rm['pr_auc']} precision={rm['precision']:.3f} recall={rm['recall']:.3f}")
        if fold_metrics:
            pr_aucs = [f["pr_auc"] for f in fold_metrics if f["pr_auc"] is not None]
            print(f"Mean PR-AUC={np.mean(pr_aucs):.3f} std={np.std(pr_aucs):.3f} across {len(fold_metrics)} folds")
    else:
        print(f"Too few independent positive-containing groups ({n_groups_with_pos}) for meaningful grouped CV -- reported explicitly, not run.")

    section("8. DIAGNOSTICS")
    print("A. Single-feature baselines:")
    single_feature_results = {}
    for feat in SINGLE_FEATURES:
        vpr, vroc = average_precision_score(val.target, val[feat].fillna(0)), roc_auc_score(val.target, val[feat].fillna(0))
        tpr, troc = average_precision_score(test.target, test[feat].fillna(0)), roc_auc_score(test.target, test[feat].fillna(0))
        single_feature_results[feat] = {"val_pr_auc": vpr, "val_roc_auc": vroc, "test_pr_auc": tpr, "test_roc_auc": troc}
        print(f"  {feat}: VAL PR-AUC={vpr:.3f} ROC-AUC={vroc:.3f} | TEST PR-AUC={tpr:.3f} ROC-AUC={troc:.3f}")

    print("\nB. Station-ID diagnostic (Model A: without station_id [main] vs Model B: with station_id):")
    train_b, val_b, test_b = train.copy(), val.copy(), test.copy()
    for df in (train_b, val_b, test_b):
        df["station_id_cat"] = df["station_id"]
    cats_b = ["station_id_cat"] + categorical_features
    prep_categoricals([train_b, val_b, test_b], ["station_id_cat"], train_b)
    model_b = train_lgbm(train_b, val_b, numeric_features + cats_b, cats_b, study.best_params, moderate_weight)
    vpr_b = average_precision_score(val_b.target, model_b.predict(val_b[numeric_features + cats_b]))
    tpr_b = average_precision_score(test_b.target, model_b.predict(test_b[numeric_features + cats_b]))
    print(f"  Model A (no station_id): VAL PR-AUC={val_row_m['pr_auc']:.3f} TEST PR-AUC={test_row_m['pr_auc']:.3f}")
    print(f"  Model B (with station_id): VAL PR-AUC={vpr_b:.3f} TEST PR-AUC={tpr_b:.3f}")
    station_id_diagnostic = {"model_a_no_station_id": {"val_pr_auc": val_row_m["pr_auc"], "test_pr_auc": test_row_m["pr_auc"]},
                              "model_b_with_station_id": {"val_pr_auc": vpr_b, "test_pr_auc": tpr_b}}

    print("\nC. Feature-family ablation (full / no-buffer / no-cycle):")
    family_ablation = {}
    for label, drop in [("full", []), ("no_buffer", BUFFER_FAMILY), ("no_cycle", CYCLE_TIME_FAMILY)]:
        feats = [f for f in numeric_features if f not in drop] + categorical_features
        m = train_lgbm(train, val, feats, categorical_features, study.best_params, moderate_weight)
        vpr = average_precision_score(val.target, m.predict(val[feats]))
        family_ablation[label] = vpr
        print(f"  {label} ({len(feats)} feat): VAL PR-AUC={vpr:.3f}")

    print("\nD. Leave-S21-out / Leave-S22-out:")
    leave_station = {}
    for station in ["S21", "S22"]:
        train_wo = train[~((train.target == 1) & (train.station_id == station))]
        m = train_lgbm(train_wo, val, features, categorical_features, study.best_params, moderate_weight)
        for part_name, df in [("val", val), ("test", test)]:
            sub = df[df.station_id == station]
            if sub.target.nunique() < 2:
                leave_station[f"{station}_{part_name}"] = {"note": "insufficient class variety"}
                print(f"  leave-{station}-out / {part_name}_{station}: insufficient positives to score")
                continue
            scores = m.predict(sub[features])
            pr, roc = average_precision_score(sub.target, scores), roc_auc_score(sub.target, scores)
            leave_station[f"{station}_{part_name}"] = {"pr_auc": pr, "roc_auc": roc, "n_positives": int((sub.target == 1).sum())}
            print(f"  leave-{station}-out / {part_name}_{station}: n_pos={int((sub.target==1).sum())} PR-AUC={pr:.3f} ROC-AUC={roc:.3f}")

    print("\nE. Leave-one-mechanism-out (MANUAL_VARIATION S21/S22 shifts):")
    train_wo_mech = train[~((train.target == 1) & (train.shift_id.isin(MANUAL_VARIATION_S21_S22_SHIFTS)))]
    m_mech = train_lgbm(train_wo_mech, val, features, categorical_features, study.best_params, moderate_weight)
    leave_mechanism = {}
    for part_name, df in [("val", val), ("test", test)]:
        sub = df[df.shift_id.isin(MANUAL_VARIATION_S21_S22_SHIFTS)]
        if sub.target.nunique() < 2:
            leave_mechanism[part_name] = {"note": "insufficient class variety"}
            continue
        scores = m_mech.predict(sub[features])
        pr, roc = average_precision_score(sub.target, scores), roc_auc_score(sub.target, scores)
        leave_mechanism[part_name] = {"pr_auc": pr, "roc_auc": roc}
        print(f"  {part_name} (MANUAL_VARIATION shifts): PR-AUC={pr:.3f} ROC-AUC={roc:.3f}")

    section("9. EXPLAINABILITY")
    rng = np.random.RandomState(SEED)
    sample_idx = rng.choice(len(val), size=min(20000, len(val)), replace=False)
    contrib = final_model.predict(val.iloc[sample_idx][features], pred_contrib=True)
    contrib_df = pd.DataFrame(contrib[:, :-1], columns=features)
    top_global = contrib_df.abs().mean().sort_values(ascending=False).head(10)
    print("Top 10 global features:")
    for feat, imp in top_global.items():
        print(f"  {feat}: {imp:.4f}")
    occupancy_dominates = top_global.index[0] in BUFFER_FAMILY
    print(f"\nBuffer-occupancy feature dominates top-1: {occupancy_dominates} (documented, not hidden)")

    section("10. SAVE ARTIFACTS")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(ARTIFACT_DIR / "flow_v2_lightgbm_model.txt"))
    joblib.dump(final_model, ARTIFACT_DIR / "flow_v2_lightgbm_model.joblib")
    joblib.dump(baseline_pipe, ARTIFACT_DIR / "flow_v2_logistic_baseline.joblib")

    with (ARTIFACT_DIR / "feature_list.json").open("w") as f:
        json.dump({"numeric_features": numeric_features, "categorical_features": categorical_features,
                    "categorical_levels": {c: list(pd.Categorical(train[c]).categories) for c in categorical_features}}, f, indent=2)
    with (ARTIFACT_DIR / "threshold.json").open("w") as f:
        json.dump({"frozen_threshold": frozen_threshold, "selection_criterion": f"max F2 on VALIDATION subject to <= {FALSE_WARNING_CAP_PER_SHIFT} false warnings/shift",
                    "threshold_grid": threshold_rows}, f, indent=2)

    metadata = {
        "model_type": "LightGBM (binary classification), flow_v2 consequence-based formulation",
        "code_commit": git_commit(), "source_dataset": "data/processed/flow_v2 (Dataset C raw events, v2 labeling/sampling/split)",
        "class_ratio": {"train_neg_pos_ratio": float(ratio), "moderate_weight_used": float(moderate_weight)},
        "hyperparameters": study.best_params, "frozen_threshold": frozen_threshold,
        "logistic_baseline_unweighted_note": "see stdout log for unweighted vs moderately-weighted comparison",
        "validation_row_metrics": val_row_m, "test_row_metrics": test_row_m,
        "episode_metrics": {
            "validation": {"total_episodes": val_ep.total_episodes, "any_warning_recall": val_ep.any_warning_recall,
                           "band_5_10_min_recall": val_ep.band_5_10_min_recall, "band_0_5_min_recall": val_ep.band_0_5_min_recall,
                           "false_warnings_per_shift": val_ep.false_warnings_per_shift},
            "test": {"total_episodes": test_ep.total_episodes, "any_warning_recall": test_ep.any_warning_recall,
                     "band_5_10_min_recall": test_ep.band_5_10_min_recall, "band_0_5_min_recall": test_ep.band_0_5_min_recall,
                     "false_warnings_per_shift": test_ep.false_warnings_per_shift},
        },
        "test_metrics_per_group": per_group,
        "grouped_cv_fold_metrics": fold_metrics,
        "diagnostics": {
            "single_feature": single_feature_results, "station_id": station_id_diagnostic,
            "feature_family_ablation": family_ablation, "leave_one_station": leave_station,
            "leave_one_mechanism_manual_variation": leave_mechanism,
        },
        "top_global_features": top_global.to_dict(),
        "occupancy_dominates_top1": bool(occupancy_dominates),
        "training_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "known_limitations": [
            "Plant/station-calibrated: leave-one-station diagnostics document generalization limits explicitly.",
            "Grouped CV is constrained by only 14 positive-containing shifts total.",
            "This is a mechanistically-calibrated synthetic corpus, not a claim about real production frequency.",
        ],
    }
    with (ARTIFACT_DIR / "training_metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"Artifacts saved to {ARTIFACT_DIR}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
