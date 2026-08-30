"""
Final Flow model (Part A of the ML/intelligence build): LightGBM,
validation-derived threshold, corrected eligible-event evaluation,
anti-shortcut audit, TreeSHAP-equivalent evidence (LightGBM's native
pred_contrib -- exact SHAP values, no extra `shap` dependency), and
production artifacts under artifacts/flow/.

Reuses data/processed/flow_v1/ as-is. No feature regeneration.

Usage:
    python scripts/train_flow_final_model.py
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
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

from backend.flow.event_evaluation import evaluate_events, lead_time_report
from backend.flow.split import locked_100_shift_split

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1"
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "flow"
N_OPTUNA_TRIALS = 15
SEED = 20240002

BUFFER_FAMILY = [
    "inbound_occupancy_ratio", "inbound_occupancy_max_5m", "inbound_occupancy_mean_5m",
    "inbound_growth_1m", "inbound_growth_3m", "inbound_growth_5m", "inbound_recent_full",
    "outbound_occupancy_ratio", "outbound_growth_3m",
]
CYCLE_TIME_FAMILY = [
    "last_cycle_time", "cycle_time_mean_1m", "cycle_time_mean_3m", "cycle_time_mean_5m",
    "cycle_time_std_5m", "cycle_time_dev_from_baseline", "cycle_time_dev_relative", "cycle_time_slope_5m",
]
SINGLE_FEATURES_TO_AUDIT = [
    "inbound_occupancy_ratio", "cycle_time_dev_relative", "arrival_minus_departure_5m", "inbound_growth_5m",
]


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def file_hash(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def prep_categoricals(train, val, test, holdout, cat_features):
    """Fit category levels on TRAIN only; val/test/holdout use the same
    levels (an unseen category becomes NaN -> LightGBM treats as missing)."""
    for col in cat_features:
        cats = pd.Categorical(train[col]).categories
        for df in (train, val, test, holdout):
            df[col] = pd.Categorical(df[col], categories=cats)
    return train, val, test, holdout


def row_metrics(y_true, y_score, threshold):
    y_pred = (y_score >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, y_score)) if len(set(y_true)) > 1 else None,
        "roc_auc": float(roc_auc_score(y_true, y_score)) if len(set(y_true)) > 1 else None,
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "threshold": threshold,
    }


def _pr_auc_feval(preds, dataset):
    labels = dataset.get_label()
    return "pr_auc", average_precision_score(labels, preds), True  # True = higher is better


def train_lgbm(train, val, features, cat_features, params, seed=SEED):
    """metric='None' + a custom PR-AUC feval makes PR-AUC -- not AUC -- the
    actual early-stopping criterion. AUC saturates almost immediately on
    this near-separable data (see the ablation study: 4-9 features already
    hit ROC-AUC~0.999), which was silently stopping training at iteration 1
    every time -- a real bug, not a modeling choice, caught by the
    degenerate best_iteration=1 / single-feature-contribution result of
    the first run. PR-AUC keeps discriminating meaningfully far past where
    AUC plateaus, so it gives a real, non-degenerate stopping signal."""
    scale_pos_weight = (train.target == 0).sum() / max(1, (train.target == 1).sum())
    full_params = dict(
        objective="binary", metric="None", verbosity=-1, seed=seed,
        scale_pos_weight=scale_pos_weight, **params,
    )
    train_set = lgb.Dataset(train[features], label=train.target, categorical_feature=cat_features, free_raw_data=False)
    val_set = lgb.Dataset(val[features], label=val.target, categorical_feature=cat_features, reference=train_set, free_raw_data=False)
    model = lgb.train(
        full_params, train_set, num_boost_round=500, valid_sets=[val_set],
        feval=_pr_auc_feval,
        callbacks=[lgb.early_stopping(40, verbose=False, first_metric_only=True), lgb.log_evaluation(0)],
    )
    return model, scale_pos_weight


def main():
    t_start = time.time()
    with (OUT_DIR / "dataset_manifest.json").open() as f:
        manifest = json.load(f)
    numeric_features = manifest["numeric_features"]
    categorical_features = manifest["categorical_features"]
    features = numeric_features + categorical_features

    train = pd.read_parquet(OUT_DIR / "train.parquet")
    val = pd.read_parquet(OUT_DIR / "validation.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")
    holdout = pd.read_parquet(OUT_DIR / "unseen_equipment_degradation.parquet")
    impacts = pd.read_parquet(OUT_DIR / "bottleneck_events.parquet")
    split = locked_100_shift_split()
    val_impacts = impacts[impacts.shift_id.isin(split.validation_shifts)]
    test_impacts = impacts[impacts.shift_id.isin(split.test_shifts)]

    train, val, test, holdout = prep_categoricals(train, val, test, holdout, categorical_features)

    section("1. HYPERPARAMETER TUNING (Optuna, VALIDATION PR-AUC objective)")
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 15, 127),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 200),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": 1,
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        }
        model, _ = train_lgbm(train, val, features, categorical_features, params)
        val_scores = model.predict(val[features])
        return average_precision_score(val.target, val_scores)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(objective, n_trials=N_OPTUNA_TRIALS, show_progress_bar=False)
    print(f"Best trial: PR-AUC={study.best_value:.4f}")
    print(f"Best params: {study.best_params}")

    section("2. FINAL MODEL FIT (best hyperparameters)")
    final_model, scale_pos_weight = train_lgbm(train, val, features, categorical_features, study.best_params)
    print(f"scale_pos_weight (TRAIN-derived) = {scale_pos_weight:.1f}")
    print(f"best_iteration = {final_model.best_iteration}")

    val_scores = final_model.predict(val[features])
    test_scores = final_model.predict(test[features])

    section("3. THRESHOLD SELECTION (VALIDATION ONLY)")
    grid = np.round(np.arange(0.05, 0.96, 0.05), 2)
    threshold_rows = []
    for thr in grid:
        m = row_metrics(val.target.values, val_scores, thr)
        pred = (val_scores >= thr).astype(int)
        ev = evaluate_events(val, pred, val_impacts)
        f2 = (5 * m["precision"] * m["recall"] / (4 * m["precision"] + m["recall"])) if (m["precision"] + m["recall"]) > 0 else 0.0
        threshold_rows.append({
            "threshold": float(thr), "precision": m["precision"], "recall": m["recall"], "f1": m["f1"], "f2": f2,
            "false_warnings_per_shift": ev.false_warnings_per_shift, "event_recall": ev.event_recall,
            "eligible_events": ev.eligible_events, "detected_eligible_events": ev.detected_eligible_events,
        })
        print(f"  thr={thr:.2f}: precision={m['precision']:.3f} recall={m['recall']:.3f} f2={f2:.3f} "
              f"false_warn/shift={ev.false_warnings_per_shift:.2f} event_recall={ev.event_recall}")

    best_row = max(threshold_rows, key=lambda r: r["f2"])
    frozen_threshold = best_row["threshold"]
    print(f"\nFROZEN THRESHOLD = {frozen_threshold} (max F2 on VALIDATION; F2 weights recall over precision, "
          f"a defensible choice for an early-warning system where a missed bottleneck is costlier than a false alert)")

    section("4. VALIDATION METRICS AT FROZEN THRESHOLD")
    val_row_metrics = row_metrics(val.target.values, val_scores, frozen_threshold)
    val_pred = (val_scores >= frozen_threshold).astype(int)
    val_event = evaluate_events(val, val_pred, val_impacts)
    val_lead = lead_time_report(val_event.first_valid_lead_times)
    print(json.dumps(val_row_metrics, indent=2))
    print(f"Eligible events: {val_event.eligible_events}/{val_event.total_impact_events} total impact events")
    print(f"Detected: {val_event.detected_eligible_events}, event_recall={val_event.event_recall}, "
          f"missed={val_event.missed_events}, false_warnings/shift={val_event.false_warnings_per_shift:.2f}")
    print(f"Lead time: {val_lead}")

    section("5. TEST METRICS (evaluated ONCE, frozen threshold)")
    test_row_metrics = row_metrics(test.target.values, test_scores, frozen_threshold)
    test_pred = (test_scores >= frozen_threshold).astype(int)
    test_event = evaluate_events(test, test_pred, test_impacts)
    test_lead = lead_time_report(test_event.first_valid_lead_times)
    print(json.dumps(test_row_metrics, indent=2))
    print(f"Eligible events: {test_event.eligible_events}/{test_event.total_impact_events} total impact events")
    print(f"Detected: {test_event.detected_eligible_events}, event_recall={test_event.event_recall}, "
          f"missed={test_event.missed_events}, false_warnings/shift={test_event.false_warnings_per_shift:.2f}")
    print(f"Lead time: {test_lead}")

    section("6. ANTI-SHORTCUT AUDIT")
    print("A. Single-feature PR-AUC (VAL / TEST):")
    single_feature_audit = {}
    for feat in SINGLE_FEATURES_TO_AUDIT:
        vpr = average_precision_score(val.target, val[feat].fillna(0))
        vroc = roc_auc_score(val.target, val[feat].fillna(0))
        tpr = average_precision_score(test.target, test[feat].fillna(0))
        troc = roc_auc_score(test.target, test[feat].fillna(0))
        single_feature_audit[feat] = {"val_pr_auc": vpr, "val_roc_auc": vroc, "test_pr_auc": tpr, "test_roc_auc": troc}
        print(f"  {feat}: VAL PR-AUC={vpr:.3f} ROC-AUC={vroc:.3f} | TEST PR-AUC={tpr:.3f} ROC-AUC={troc:.3f}")

    print("\nB. Feature-family ablation (LightGBM, same params, full feature set vs. without a family):")
    family_ablation = {}
    for label, drop in [("full", []), ("without_buffer_family", BUFFER_FAMILY), ("without_cycle_time_family", CYCLE_TIME_FAMILY)]:
        feats = [f for f in numeric_features if f not in drop] + categorical_features
        m, _ = train_lgbm(train, val, feats, categorical_features, study.best_params)
        vpr = average_precision_score(val.target, m.predict(val[feats]))
        tpr = average_precision_score(test.target, m.predict(test[feats]))
        family_ablation[label] = {"val_pr_auc": vpr, "test_pr_auc": tpr, "n_features": len(feats)}
        print(f"  {label} ({len(feats)} features): VAL PR-AUC={vpr:.3f}  TEST PR-AUC={tpr:.3f}")

    print("\nC. Leave-one-station diagnostic (train without S22 positives, evaluate on S22):")
    train_no_s22_pos = train[~((train.target == 1) & (train.station_id == "S22"))]
    m_no_s22, _ = train_lgbm(train_no_s22_pos, val, features, categorical_features, study.best_params)
    s22_val = val[val.station_id == "S22"]
    s22_test = test[test.station_id == "S22"]
    leave_one_station = {"n_s22_positives_removed_from_train": int(((train.target == 1) & (train.station_id == "S22")).sum())}
    for name, df in [("val_S22", s22_val), ("test_S22", s22_test)]:
        if df.target.nunique() > 1:
            scores = m_no_s22.predict(df[features])
            pr = average_precision_score(df.target, scores)
            roc = roc_auc_score(df.target, scores)
            leave_one_station[name] = {"pr_auc": pr, "roc_auc": roc, "n_positives": int((df.target == 1).sum())}
            print(f"  {name}: n_positives={int((df.target==1).sum())} PR-AUC={pr:.3f} ROC-AUC={roc:.3f}")
        else:
            leave_one_station[name] = {"note": f"only one class present ({df.target.nunique()}), cannot score", "n_positives": int((df.target==1).sum())}
            print(f"  {name}: only one class present, cannot compute PR-AUC/ROC-AUC (n_positives={int((df.target==1).sum())})")
    print("  NOTE per instructions: if performance collapses here, this does NOT trigger a dataset redesign. "
          "It documents that supervised Flow intelligence is currently plant/station-calibrated.")

    section("7. EVIDENCE (LightGBM native TreeSHAP-equivalent contributions)")
    rng = np.random.RandomState(SEED)
    sample_idx = rng.choice(len(val), size=min(20000, len(val)), replace=False)
    val_sample = val.iloc[sample_idx]
    contrib = final_model.predict(val_sample[features], pred_contrib=True)  # shape (n, n_features+1), last col = base value
    contrib_df = pd.DataFrame(contrib[:, :-1], columns=features)
    global_importance = contrib_df.abs().mean().sort_values(ascending=False)
    top_global = global_importance.head(10)
    print("Top 10 global features (mean |SHAP contribution| over a 20k-row validation sample):")
    for feat, val_imp in top_global.items():
        print(f"  {feat}: {val_imp:.4f}")

    # local example: highest-scoring validation alert
    top_alert_idx = int(np.argmax(val_scores))
    alert_row = val.iloc[top_alert_idx]
    alert_contrib = final_model.predict(val[features].iloc[[top_alert_idx]], pred_contrib=True)[0][:-1]
    alert_contrib_series = pd.Series(alert_contrib, index=features).sort_values(key=abs, ascending=False)

    def _jsonable(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)

    local_evidence = [
        {"feature": feat, "value": _jsonable(alert_row[feat]),
         "contribution": float(alert_contrib_series[feat]),
         "effect": "increases_risk" if alert_contrib_series[feat] > 0 else "decreases_risk"}
        for feat in alert_contrib_series.head(5).index
    ]
    print(f"\nLocal evidence example -- station {alert_row.station_id}, shift {alert_row.shift_id}, "
          f"bottleneck_risk={val_scores[top_alert_idx]:.3f}:")
    for e in local_evidence:
        print(f"  {e['feature']} = {e['value']} -> {e['effect']} (contribution={e['contribution']:.4f})")

    section("8. SAVE ARTIFACTS")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(ARTIFACT_DIR / "flow_lightgbm_model.txt"))
    joblib.dump(final_model, ARTIFACT_DIR / "flow_lightgbm_model.joblib")

    with (ARTIFACT_DIR / "feature_list.json").open("w") as f:
        json.dump({"numeric_features": numeric_features, "categorical_features": categorical_features,
                    "categorical_levels": {c: list(pd.Categorical(train[c]).categories) for c in categorical_features}}, f, indent=2)

    with (ARTIFACT_DIR / "threshold.json").open("w") as f:
        json.dump({"frozen_threshold": frozen_threshold, "selection_criterion": "max F2 on VALIDATION",
                    "threshold_grid": threshold_rows}, f, indent=2)

    metadata = {
        "model_type": "LightGBM (binary classification)",
        "code_commit": git_commit(),
        "source_dataset": "data/processed/flow_v1 (Dataset C: historical_100_flow_calibrated)",
        "feature_hash": file_hash(OUT_DIR / "dataset_manifest.json"),
        "split_definition": {"train": "SHIFT001-070", "validation": "SHIFT071-085", "test": "SHIFT086-100"},
        "hyperparameters": study.best_params,
        "scale_pos_weight": scale_pos_weight,
        "n_optuna_trials": N_OPTUNA_TRIALS,
        "best_iteration": final_model.best_iteration,
        "frozen_threshold": frozen_threshold,
        "validation_metrics": val_row_metrics,
        "validation_event_metrics": {
            "total_impact_events": val_event.total_impact_events, "eligible_events": val_event.eligible_events,
            "detected_eligible_events": val_event.detected_eligible_events, "event_recall": val_event.event_recall,
            "missed_events": val_event.missed_events, "false_warnings_per_shift": val_event.false_warnings_per_shift,
            "lead_time": val_lead,
        },
        "test_metrics": test_row_metrics,
        "test_event_metrics": {
            "total_impact_events": test_event.total_impact_events, "eligible_events": test_event.eligible_events,
            "detected_eligible_events": test_event.detected_eligible_events, "event_recall": test_event.event_recall,
            "missed_events": test_event.missed_events, "false_warnings_per_shift": test_event.false_warnings_per_shift,
            "lead_time": test_lead,
        },
        "anti_shortcut_audit": {
            "single_feature": single_feature_audit, "family_ablation": family_ablation, "leave_one_station_S22": leave_one_station,
        },
        "top_global_features": top_global.to_dict(),
        "training_timestamp": pd.Timestamp.utcnow().isoformat(),
        "known_limitations": [
            "Positive-class physical diversity is low (S21/S22 dominate); TEST contains few independent bottleneck episodes.",
            "This is a plant/line-calibrated prototype, not evidence of station-agnostic generalization.",
            "Row-level metrics (esp. TEST, n=16 positives) carry high sampling variance -- see cross-split robustness results.",
            "Training corpus (Dataset C) is a mechanistically-calibrated synthetic enrichment, not a claim about real production scenario frequency.",
        ],
    }
    with (ARTIFACT_DIR / "training_metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"Artifacts saved to {ARTIFACT_DIR}")
    print(f"\nTotal runtime: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
