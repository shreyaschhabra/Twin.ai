from __future__ import annotations

import json
import math
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.model_selection import GroupKFold

from feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES, TARGET_COLUMN
from train_catboost_v3 import (
    CATBOOST_PARAMS as V3_CATBOOST_PARAMS,
    add_post_ml_scores,
    apply_calibrator,
    choose_row_thresholds,
    crossfit_calibration,
    fit_final_calibrator,
    fit_single_catboost as v3_fit_single_catboost,
    per_run_probability_metrics,
    predict_models as v3_predict_models,
    prepare_X,
    probability_metrics,
    resample_training_units as v3_resample_training_units,
    row_metrics_at_threshold,
    unit_labels,
    unit_prevalence,
)


# ============================================================
# PATHS / FROZEN EXPERIMENT CONTRACT
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
FEATURE_DIR = ROOT / "generated_features_v5"
RESULTS_DIR = ROOT / "results"
MODEL_DIR = ROOT / "saved_models"

TRAIN_PATH = FEATURE_DIR / "train.pkl"
VALIDATION_PATH = FEATURE_DIR / "validation.pkl"

RANDOM_SEED = 42
N_SPLITS = 5
FWR_CAP = 0.05

BAGGING_RATES = (0.045, 0.050, 0.055)
BAGGING_SEEDS_5 = (42, 52, 62, 72, 82)
BAGGING_SEEDS_7 = (42, 52, 62, 72, 82, 92, 102)

# Hard examples are identified from a fixed V3-compatible 5% x5 source.
# This is fixed before seeing V5 candidate results and avoids adapting the
# mining source to the same OOF scores used for comparison.
MINING_SOURCE_RATE = 0.050
MINING_SOURCE_SEEDS = BAGGING_SEEDS_5
HARD_NEGATIVE_FRACTION = 0.10
HARD_POSITIVE_WEIGHTS = (1.5, 2.0)

# Platt must improve calibration without materially damaging pooled OOF
# ranking. These guardrails are fixed before running the experiment.
MAX_PLATT_PR_AUC_DAMAGE = 0.005
MAX_PLATT_ROC_AUC_DAMAGE = 0.002

STAGES = {
    "early": (None, 17),
    "mid": (18, 23),
    "late": (24, None),
}

POLICY_COLUMNS = {
    "raw": "score",
    "ema_0.3": "ema_0.3",
    "ema_0.5": "ema_0.5",
    "ema_0.7": "ema_0.7",
    "two_consecutive": "two_consecutive",
    "two_of_three": "two_of_three",
}

CATBOOST_PARAMS = dict(V3_CATBOOST_PARAMS)

assert len(DEFECT_FEATURES) == 30
assert len(set(DEFECT_FEATURES)) == 30
assert TARGET_COLUMN not in DEFECT_FEATURES
assert CATEGORICAL_FEATURES == ["supplier_batch", "vehicle_model"]


# ============================================================
# GENERAL HELPERS
# ============================================================

_START_TIME = time.monotonic()


def log(message: str):
    elapsed = time.monotonic() - _START_TIME
    print(f"[{elapsed:8.1f}s] {message}", flush=True)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, payload):
    path.write_text(json.dumps(_json_safe(payload), indent=2))


def normalize_key(run_id, unit_id):
    return str(run_id), str(unit_id)


def key_set(df: pd.DataFrame):
    return {
        normalize_key(run_id, unit_id)
        for run_id, unit_id in df[["run_id", "unit_id"]].itertuples(
            index=False,
            name=None,
        )
    }


def validate_frame(df: pd.DataFrame, split_name: str):
    required_meta = [
        "run_id",
        "unit_id",
        "prediction_station_index",
        "prediction_time",
        "prediction_event_sequence",
        "final_station_index",
        TARGET_COLUMN,
    ]
    missing = [c for c in required_meta + DEFECT_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"{split_name} is missing columns: {missing}")

    if df[TARGET_COLUMN].isna().any():
        raise ValueError(f"{split_name} still contains incomplete labels")

    label_counts = df.groupby(["run_id", "unit_id"])[TARGET_COLUMN].nunique()
    if (label_counts != 1).any():
        raise ValueError(f"{split_name} has inconsistent labels within a unit")

    ordered = df.sort_values(
        ["run_id", "unit_id", "prediction_time", "prediction_event_sequence"],
        kind="stable",
    )
    non_monotonic = ordered.groupby(["run_id", "unit_id"], sort=False)[
        "prediction_station_index"
    ].apply(lambda s: not s.is_monotonic_increasing)
    if non_monotonic.any():
        raise ValueError(
            f"{split_name} contains units whose station order is not chronological"
        )


def grouped_splits(df: pd.DataFrame):
    groups = df["run_id"].astype(str).to_numpy()
    y = df[TARGET_COLUMN].astype(int).to_numpy()
    splitter = GroupKFold(n_splits=min(N_SPLITS, len(np.unique(groups))))
    dummy = np.zeros((len(df), 1), dtype=np.int8)
    return list(splitter.split(dummy, y, groups))


def stage_mask(df: pd.DataFrame, stage: str):
    lower, upper = STAGES[stage]
    station = df["prediction_station_index"]
    mask = pd.Series(True, index=df.index)
    if lower is not None:
        mask &= station >= lower
    if upper is not None:
        mask &= station <= upper
    return mask


# ============================================================
# WHOLE-UNIT SAMPLING AND MODEL FITTING
# ============================================================

def resample_with_forced_negatives(
    df: pd.DataFrame,
    target_rate: float,
    seed: int,
    forced_negative_keys: set[tuple[str, str]] | None = None,
):
    """Keep all positive units, all requested hard negatives, and sample easy negatives."""
    if not forced_negative_keys:
        sampled = v3_resample_training_units(df, target_rate, seed)
        return sampled, {
            "hard_negative_units_kept": 0,
            "requested_target_rate": target_rate,
            "effective_unit_positive_rate": unit_prevalence(sampled),
        }

    labels = unit_labels(df).copy()
    labels["_key"] = [
        normalize_key(r, u)
        for r, u in labels[["run_id", "unit_id"]].itertuples(index=False, name=None)
    ]
    positive = labels[labels[TARGET_COLUMN].eq(1)].copy()
    negative = labels[labels[TARGET_COLUMN].eq(0)].copy()

    n_pos = len(positive)
    n_neg_needed = int(round(n_pos * (1.0 - target_rate) / target_rate))
    n_neg_needed = min(n_neg_needed, len(negative))

    forced = negative[negative["_key"].isin(forced_negative_keys)].copy()
    if len(forced) > n_neg_needed:
        # This should not happen for the pre-registered top-10% rule. Keeping
        # every hard negative is more important than hitting exactly 5%.
        n_neg_needed = len(forced)

    easy = negative[~negative["_key"].isin(set(forced["_key"]))].copy()
    n_easy_needed = n_neg_needed - len(forced)
    if n_easy_needed > len(easy):
        n_easy_needed = len(easy)

    if n_easy_needed:
        rng = np.random.default_rng(seed)
        chosen = rng.choice(len(easy), size=n_easy_needed, replace=False)
        sampled_easy = easy.iloc[chosen]
    else:
        sampled_easy = easy.iloc[0:0]

    selected_units = pd.concat(
        [
            positive[["run_id", "unit_id"]],
            forced[["run_id", "unit_id"]],
            sampled_easy[["run_id", "unit_id"]],
        ],
        ignore_index=True,
    ).drop_duplicates()

    sampled = df.merge(
        selected_units,
        on=["run_id", "unit_id"],
        how="inner",
        validate="many_to_one",
    ).reset_index(drop=True)

    original_positive = key_set(positive)
    sampled_positive = key_set(
        unit_labels(sampled).query(f"{TARGET_COLUMN} == 1")
    )
    if original_positive != sampled_positive:
        raise RuntimeError("A positive unit was lost during hard-negative sampling")

    return sampled, {
        "hard_negative_units_kept": int(len(forced)),
        "requested_target_rate": target_rate,
        "effective_unit_positive_rate": unit_prevalence(sampled),
    }


def hard_positive_row_weights(
    df: pd.DataFrame,
    hard_positive_keys: set[tuple[str, str]] | None,
    hard_positive_weight: float | None,
):
    if not hard_positive_keys or hard_positive_weight is None:
        return None
    keys = [
        normalize_key(r, u)
        for r, u in df[["run_id", "unit_id"]].itertuples(index=False, name=None)
    ]
    mask = np.fromiter(
        (key in hard_positive_keys for key in keys),
        dtype=bool,
        count=len(keys),
    )
    weights = np.ones(len(df), dtype=float)
    weights[mask] = float(hard_positive_weight)
    return weights


def fit_single_catboost(
    df: pd.DataFrame,
    seed: int,
    hard_positive_keys: set[tuple[str, str]] | None = None,
    hard_positive_weight: float | None = None,
):
    weights = hard_positive_row_weights(
        df,
        hard_positive_keys,
        hard_positive_weight,
    )
    if weights is None:
        return v3_fit_single_catboost(df, seed)

    X, cat_idx = prepare_X(df)
    y = df[TARGET_COLUMN].astype(int).to_numpy()
    params = dict(CATBOOST_PARAMS)
    params["random_seed"] = int(seed)
    model = CatBoostClassifier(**params)
    model.fit(X, y, cat_features=cat_idx, sample_weight=weights)
    return model


def predict_single(model, df: pd.DataFrame):
    return v3_predict_models([model], df)


# ============================================================
# ALERT POLICIES
# ============================================================

def add_policy_scores(df: pd.DataFrame, score_col: str = "score"):
    """Reuse V3 policy transforms after validating chronological station order."""
    return add_post_ml_scores(df, score_col)


def unit_policy_table(df: pd.DataFrame, score_col: str):
    """Keep every unit in the denominator; missing policy scores mean no alert."""
    pre = df[df["prediction_station_index"] < df["final_station_index"]].copy()
    labels = pre.groupby(["run_id", "unit_id"], sort=False)[TARGET_COLUMN].max()
    max_scores = pre.groupby(["run_id", "unit_id"], sort=False)[score_col].max()
    unit = labels.rename("y").to_frame().join(max_scores.rename("max_score"), how="left")
    unit["y"] = unit["y"].astype(int)
    return pre, unit


def choose_unit_threshold_exact(
    df: pd.DataFrame,
    score_col: str,
    fwr_cap: float = FWR_CAP,
):
    pre, unit = unit_policy_table(df, score_col)
    total_pos = int(unit["y"].eq(1).sum())
    total_neg = int(unit["y"].eq(0).sum())
    if total_pos == 0 or total_neg == 0:
        raise ValueError("Unit threshold selection requires both classes")

    finite = unit[np.isfinite(unit["max_score"])].copy()
    if finite.empty:
        raise ValueError(f"No finite scores for policy column {score_col}")

    finite = finite.sort_values("max_score", ascending=False, kind="stable")
    by_score = finite.groupby("max_score", sort=False)["y"].agg(["sum", "count"])
    cumulative_pos = by_score["sum"].cumsum().to_numpy(dtype=int)
    cumulative_total = by_score["count"].cumsum().to_numpy(dtype=int)
    cumulative_neg = cumulative_total - cumulative_pos
    thresholds = by_score.index.to_numpy(dtype=float)

    recalls = cumulative_pos / total_pos
    fwrs = cumulative_neg / total_neg
    precisions = cumulative_pos / cumulative_total
    feasible = np.flatnonzero(fwrs <= fwr_cap + 1e-15)

    if len(feasible):
        best_idx = max(
            feasible,
            key=lambda i: (
                float(recalls[i]),
                float(precisions[i]),
                -float(fwrs[i]),
            ),
        )
        observed_rank = (
            float(recalls[best_idx]),
            float(precisions[best_idx]),
            -float(fwrs[best_idx]),
        )
        no_alert_rank = (0.0, 0.0, 0.0)
        if no_alert_rank > observed_rank:
            threshold = float(np.nextafter(finite["max_score"].max(), np.inf))
            unit_recall = 0.0
            false_warning_rate = 0.0
            unit_precision = 0.0
        else:
            threshold = float(thresholds[best_idx])
            unit_recall = float(recalls[best_idx])
            false_warning_rate = float(fwrs[best_idx])
            unit_precision = float(precisions[best_idx])
    else:
        # An above-maximum threshold represents the always-feasible no-alert policy.
        threshold = float(np.nextafter(finite["max_score"].max(), np.inf))
        unit_recall = 0.0
        false_warning_rate = 0.0
        unit_precision = 0.0

    alerted = pre[
        np.isfinite(pre[score_col]) & (pre[score_col] >= threshold)
    ].sort_values(
        ["run_id", "unit_id", "prediction_time", "prediction_event_sequence"],
        kind="stable",
    )
    first = alerted.drop_duplicates(["run_id", "unit_id"], keep="first").set_index(
        ["run_id", "unit_id"]
    )["prediction_station_index"]
    positive_keys = set(unit.index[unit["y"].eq(1)])
    first_positive = [value for key, value in first.items() if key in positive_keys]

    return {
        "threshold": threshold,
        "unit_recall": unit_recall,
        "false_warning_rate": false_warning_rate,
        "unit_precision": unit_precision,
        "median_first_alert_station_index": (
            float(np.median(first_positive)) if first_positive else None
        ),
        "detected_before_final_inspection": unit_recall,
        "positive_units": total_pos,
        "negative_units": total_neg,
        "alerted_positive_units": int(round(unit_recall * total_pos)),
        "alerted_negative_units": int(round(false_warning_rate * total_neg)),
    }


def evaluate_unit_policy_all_units(
    df: pd.DataFrame,
    score_col: str,
    threshold: float,
):
    pre, unit = unit_policy_table(df, score_col)
    hit = unit["max_score"].ge(float(threshold)).fillna(False)
    pos = unit["y"].eq(1)
    neg = unit["y"].eq(0)

    alerted = pre[
        np.isfinite(pre[score_col]) & (pre[score_col] >= float(threshold))
    ].sort_values(
        ["run_id", "unit_id", "prediction_time", "prediction_event_sequence"],
        kind="stable",
    )
    first = alerted.drop_duplicates(["run_id", "unit_id"], keep="first").set_index(
        ["run_id", "unit_id"]
    )["prediction_station_index"]
    positive_keys = set(unit.index[pos])
    first_positive = [value for key, value in first.items() if key in positive_keys]

    alerted_total = int(hit.sum())
    alerted_positive = int((hit & pos).sum())
    alerted_negative = int((hit & neg).sum())
    return {
        "unit_recall": float(alerted_positive / pos.sum()) if pos.any() else None,
        "false_warning_rate": (
            float(alerted_negative / neg.sum()) if neg.any() else None
        ),
        "unit_precision": (
            float(alerted_positive / alerted_total) if alerted_total else 0.0
        ),
        "median_first_alert_station_index": (
            float(np.median(first_positive)) if first_positive else None
        ),
        "detected_before_final_inspection": (
            float(alerted_positive / pos.sum()) if pos.any() else None
        ),
        "positive_units": int(pos.sum()),
        "negative_units": int(neg.sum()),
        "alerted_positive_units": alerted_positive,
        "alerted_negative_units": alerted_negative,
    }


def policy_rank(config: dict):
    median = config.get("median_first_alert_station_index")
    median_rank = -float(median) if median is not None else -math.inf
    return (
        float(config["unit_recall"]),
        float(config["unit_precision"]),
        -float(config["false_warning_rate"]),
        median_rank,
    )


def evaluate_all_policies(df: pd.DataFrame, candidate_name: str):
    scored = add_policy_scores(df, "score")
    configs = {}
    rows = []
    for policy, column in POLICY_COLUMNS.items():
        cfg = choose_unit_threshold_exact(scored, column, FWR_CAP)
        configs[policy] = cfg
        rows.append(
            {
                "candidate": candidate_name,
                "score_space": "raw_probability",
                "calibration": "none",
                "policy": policy,
                **cfg,
            }
        )
    winner = max(configs, key=lambda policy: policy_rank(configs[policy]))
    return winner, configs[winner], configs, rows


# ============================================================
# CANDIDATE METRICS / RANKING
# ============================================================

def candidate_model_count(config: dict):
    kind = config["kind"]
    if kind == "natural" or kind == "hard_positive":
        return 1
    if kind in {"bagging", "hard_negative"}:
        return len(config["seeds"])
    if kind == "stage":
        return len(STAGES)
    if kind == "blend":
        return sum(candidate_model_count(branch) for branch in config["branches"])
    raise ValueError(f"Unknown candidate kind: {kind}")


def fold_metric_row(
    candidate_name: str,
    config: dict,
    fold_number: int,
    fold_train: pd.DataFrame,
    fold_val: pd.DataFrame,
    pred: np.ndarray,
    fit_info: dict,
):
    metrics = probability_metrics(
        fold_val[TARGET_COLUMN].astype(int).to_numpy(),
        pred,
    )
    return {
        "candidate": candidate_name,
        "family": config["family"],
        "fold": fold_number,
        "train_runs": "|".join(sorted(fold_train["run_id"].astype(str).unique())),
        "validation_runs": "|".join(
            sorted(fold_val["run_id"].astype(str).unique())
        ),
        "models_in_candidate": candidate_model_count(config),
        "effective_training_unit_positive_rate_mean": fit_info.get(
            "effective_training_unit_positive_rate_mean"
        ),
        "hard_negative_units": int(fit_info.get("hard_negative_units", 0)),
        "hard_positive_units": int(fit_info.get("hard_positive_units", 0)),
        "heldout_rows": int(len(fold_val)),
        "heldout_units": int(unit_labels(fold_val).shape[0]),
        "heldout_row_positive_rate": float(fold_val[TARGET_COLUMN].mean()),
        **metrics,
    }


def register_candidate(
    candidate_results: dict,
    candidate_name: str,
    config: dict,
    raw_oof: np.ndarray,
    fold_rows: list[dict],
    train: pd.DataFrame,
):
    if np.isnan(raw_oof).any():
        raise RuntimeError(f"{candidate_name} has missing OOF predictions")

    y = train[TARGET_COLUMN].astype(int).to_numpy()
    raw_metrics = probability_metrics(y, raw_oof)
    folds = pd.DataFrame(fold_rows)

    oof_df = train.copy()
    oof_df["score"] = raw_oof
    winner, winner_cfg, policies, policy_rows = evaluate_all_policies(
        oof_df,
        candidate_name,
    )

    result = {
        "config": config,
        "raw_oof": np.asarray(raw_oof, dtype=float),
        "fold_rows": fold_rows,
        "raw_probability_metrics": raw_metrics,
        "mean_fold_pr_auc": float(folds["pr_auc"].mean()),
        "std_fold_pr_auc": float(folds["pr_auc"].std(ddof=0)),
        "min_fold_pr_auc": float(folds["pr_auc"].min()),
        "effective_training_unit_positive_rate": float(
            folds["effective_training_unit_positive_rate_mean"].dropna().mean()
        ),
        "selected_raw_alert_policy": winner,
        "selected_raw_alert_policy_config": winner_cfg,
        "raw_alert_policies": policies,
        "policy_rows": policy_rows,
    }
    candidate_results[candidate_name] = result

    log(
        f"{candidate_name}: pooled PR-AUC={raw_metrics['pr_auc']:.5f}, "
        f"min fold={result['min_fold_pr_auc']:.5f}, "
        f"unit recall={winner_cfg['unit_recall']:.4f}, "
        f"FWR={winner_cfg['false_warning_rate']:.4f}"
    )
    return result


def candidate_rank(result: dict):
    policy = result["selected_raw_alert_policy_config"]
    metrics = result["raw_probability_metrics"]
    roc = metrics.get("roc_auc")
    median = policy.get("median_first_alert_station_index")
    return (
        float(policy["unit_recall"]),
        float(metrics["pr_auc"]),
        float(result["min_fold_pr_auc"]),
        float(roc) if roc is not None else -math.inf,
        float(policy["unit_precision"]),
        -float(median) if median is not None else -math.inf,
        -float(metrics["brier"]),
    )


def comparison_frame(candidate_results: dict, selected_name: str | None = None):
    rows = []
    for name, result in candidate_results.items():
        cfg = result["config"]
        prob = result["raw_probability_metrics"]
        alert = result["selected_raw_alert_policy_config"]
        rows.append(
            {
                "candidate": name,
                "family": cfg["family"],
                "components": "+".join(cfg.get("components", [cfg["family"]])),
                "target_unit_positive_rate": cfg.get("target_rate"),
                "number_of_models": candidate_model_count(cfg),
                "effective_training_unit_positive_rate": result[
                    "effective_training_unit_positive_rate"
                ],
                "mean_fold_pr_auc": result["mean_fold_pr_auc"],
                "std_fold_pr_auc": result["std_fold_pr_auc"],
                "minimum_fold_pr_auc": result["min_fold_pr_auc"],
                "pooled_oof_pr_auc": prob["pr_auc"],
                "pooled_oof_roc_auc": prob["roc_auc"],
                "pooled_oof_brier": prob["brier"],
                "pooled_oof_log_loss": prob["log_loss"],
                "pooled_oof_ece15": prob["ece15"],
                "selected_raw_alert_policy": result["selected_raw_alert_policy"],
                "raw_alert_threshold": alert["threshold"],
                "oof_unit_recall": alert["unit_recall"],
                "oof_false_warning_rate": alert["false_warning_rate"],
                "oof_unit_precision": alert["unit_precision"],
                "oof_median_first_alert_station_index": alert[
                    "median_first_alert_station_index"
                ],
                "selected_final": name == selected_name,
            }
        )
    return pd.DataFrame(rows)


# ============================================================
# OUTER-FOLD FIT / PREDICT HELPERS
# ============================================================

def fit_predict_bagging_fold(
    fold_train: pd.DataFrame,
    fold_val: pd.DataFrame,
    target_rate: float,
    seeds: tuple[int, ...] | list[int],
    fold_number: int,
    forced_negative_keys: set[tuple[str, str]] | None = None,
    hard_positive_keys: set[tuple[str, str]] | None = None,
    hard_positive_weight: float | None = None,
    seed_namespace: int = 0,
):
    predictions = []
    rates = []
    hard_negative_counts = []

    for model_number, seed in enumerate(seeds, start=1):
        sample_seed = int(seed + fold_number * 1000 + seed_namespace)
        sampled, sample_info = resample_with_forced_negatives(
            fold_train,
            target_rate,
            sample_seed,
            forced_negative_keys,
        )
        model = fit_single_catboost(
            sampled,
            int(seed),
            hard_positive_keys,
            hard_positive_weight,
        )
        predictions.append(predict_single(model, fold_val))
        rates.append(unit_prevalence(sampled))
        hard_negative_counts.append(sample_info["hard_negative_units_kept"])
        del model, sampled
        log(
            f"  fold {fold_number}: fitted bag {model_number}/{len(seeds)} "
            f"at {100*rates[-1]:.3f}% unit prevalence"
        )

    hard_positive_count = 0
    if hard_positive_keys:
        fold_keys = key_set(unit_labels(fold_train))
        hard_positive_count = len(fold_keys & hard_positive_keys)

    return predictions, {
        "effective_training_unit_positive_rate_mean": float(np.mean(rates)),
        "hard_negative_units": int(max(hard_negative_counts, default=0)),
        "hard_positive_units": int(hard_positive_count),
    }


def fit_predict_candidate_fold(
    config: dict,
    fold_train: pd.DataFrame,
    fold_val: pd.DataFrame,
    fold_number: int,
    mining: dict | None = None,
):
    kind = config["kind"]
    mining = mining or {}

    if kind == "natural":
        model = fit_single_catboost(fold_train, RANDOM_SEED)
        pred = predict_single(model, fold_val)
        del model
        return pred, {
            "effective_training_unit_positive_rate_mean": unit_prevalence(fold_train),
            "hard_negative_units": 0,
            "hard_positive_units": 0,
        }

    if kind == "hard_positive":
        hard_keys = mining.get("hard_positive_keys", set())
        model = fit_single_catboost(
            fold_train,
            RANDOM_SEED,
            hard_keys,
            config["hard_positive_weight"],
        )
        pred = predict_single(model, fold_val)
        del model
        return pred, {
            "effective_training_unit_positive_rate_mean": unit_prevalence(fold_train),
            "hard_negative_units": 0,
            "hard_positive_units": len(hard_keys & key_set(unit_labels(fold_train))),
        }

    if kind in {"bagging", "hard_negative"}:
        forced = (
            mining.get("hard_negative_keys", set())
            if kind == "hard_negative"
            else None
        )
        bag_predictions, fit_info = fit_predict_bagging_fold(
            fold_train,
            fold_val,
            config["target_rate"],
            config["seeds"],
            fold_number,
            forced_negative_keys=forced,
        )
        return np.mean(np.vstack(bag_predictions), axis=0), fit_info

    if kind == "stage":
        pred = np.full(len(fold_val), np.nan, dtype=float)
        covered = np.zeros(len(fold_val), dtype=int)
        for stage in STAGES:
            train_mask = stage_mask(fold_train, stage)
            val_mask = stage_mask(fold_val, stage).to_numpy()
            model = fit_single_catboost(
                fold_train.loc[train_mask].reset_index(drop=True),
                RANDOM_SEED,
            )
            pred[val_mask] = predict_single(
                model,
                fold_val.loc[val_mask].reset_index(drop=True),
            )
            covered[val_mask] += 1
            del model
        if np.isnan(pred).any() or not np.all(covered == 1):
            raise RuntimeError("Stage routing did not cover every held-out row exactly once")
        return pred, {
            "effective_training_unit_positive_rate_mean": unit_prevalence(fold_train),
            "hard_negative_units": 0,
            "hard_positive_units": 0,
        }

    raise ValueError(f"Unsupported fold candidate kind: {kind}")


def evaluate_generic_candidate(
    train: pd.DataFrame,
    splits,
    candidate_results: dict,
    candidate_name: str,
    config: dict,
    mining_by_fold: list[dict] | None = None,
):
    oof = np.full(len(train), np.nan, dtype=float)
    fold_rows = []

    for fold_number, (tr_idx, va_idx) in enumerate(splits, start=1):
        log(f"{candidate_name}: outer fold {fold_number}/{len(splits)}")
        fold_train = train.iloc[tr_idx].copy()
        fold_val = train.iloc[va_idx].copy()
        mining = mining_by_fold[fold_number - 1] if mining_by_fold else None
        pred, fit_info = fit_predict_candidate_fold(
            config,
            fold_train,
            fold_val,
            fold_number,
            mining,
        )
        oof[va_idx] = pred
        fold_rows.append(
            fold_metric_row(
                candidate_name,
                config,
                fold_number,
                fold_train,
                fold_val,
                pred,
                fit_info,
            )
        )

    return register_candidate(
        candidate_results,
        candidate_name,
        config,
        oof,
        fold_rows,
        train,
    )


def run_initial_sweep(train: pd.DataFrame, splits, candidate_results: dict):
    natural_config = {
        "kind": "natural",
        "family": "baseline",
        "components": ["natural"],
        "target_rate": None,
    }
    evaluate_generic_candidate(
        train,
        splits,
        candidate_results,
        "natural",
        natural_config,
    )

    bagging_names = []
    for target_rate in BAGGING_RATES:
        rate_label = f"{100*target_rate:.1f}".replace(".", "p")
        name_5 = f"bagging_{rate_label}pct_x5"
        name_7 = f"bagging_{rate_label}pct_x7"
        bagging_names.extend([name_5, name_7])

        config_5 = {
            "kind": "bagging",
            "family": "bagging",
            "components": ["balanced_bagging"],
            "target_rate": target_rate,
            "seeds": list(BAGGING_SEEDS_5),
        }
        config_7 = {
            "kind": "bagging",
            "family": "bagging",
            "components": ["balanced_bagging"],
            "target_rate": target_rate,
            "seeds": list(BAGGING_SEEDS_7),
        }

        oof_5 = np.full(len(train), np.nan, dtype=float)
        oof_7 = np.full(len(train), np.nan, dtype=float)
        rows_5 = []
        rows_7 = []

        log(
            f"Shared bagging sweep at {100*target_rate:.1f}%: "
            "fit x7 once and reuse its first five models for x5"
        )
        for fold_number, (tr_idx, va_idx) in enumerate(splits, start=1):
            fold_train = train.iloc[tr_idx].copy()
            fold_val = train.iloc[va_idx].copy()
            bag_predictions, fit_info = fit_predict_bagging_fold(
                fold_train,
                fold_val,
                target_rate,
                BAGGING_SEEDS_7,
                fold_number,
            )
            pred_5 = np.mean(np.vstack(bag_predictions[:5]), axis=0)
            pred_7 = np.mean(np.vstack(bag_predictions), axis=0)
            oof_5[va_idx] = pred_5
            oof_7[va_idx] = pred_7
            rows_5.append(
                fold_metric_row(
                    name_5,
                    config_5,
                    fold_number,
                    fold_train,
                    fold_val,
                    pred_5,
                    fit_info,
                )
            )
            rows_7.append(
                fold_metric_row(
                    name_7,
                    config_7,
                    fold_number,
                    fold_train,
                    fold_val,
                    pred_7,
                    fit_info,
                )
            )

        register_candidate(
            candidate_results,
            name_5,
            config_5,
            oof_5,
            rows_5,
            train,
        )
        register_candidate(
            candidate_results,
            name_7,
            config_7,
            oof_7,
            rows_7,
            train,
        )

    return bagging_names


# ============================================================
# LEAKAGE-SAFE HARD-EXAMPLE MINING
# ============================================================

def mine_hard_examples(df: pd.DataFrame, source_oof: np.ndarray):
    source_df = df.copy()
    source_df["score"] = np.asarray(source_oof, dtype=float)
    source_scored = add_policy_scores(source_df, "score")

    source_policy, source_cfg, _, _ = evaluate_all_policies(
        source_df,
        "mining_source",
    )

    _, raw_units = unit_policy_table(source_scored, "score")
    negatives = raw_units[raw_units["y"].eq(0)].reset_index()
    negatives["_run_sort"] = negatives["run_id"].astype(str)
    negatives["_unit_sort"] = negatives["unit_id"].astype(str)
    negatives = negatives.sort_values(
        ["max_score", "_run_sort", "_unit_sort"],
        ascending=[False, True, True],
        kind="stable",
    )
    hard_negative_count = int(math.ceil(HARD_NEGATIVE_FRACTION * len(negatives)))
    selected_negative = negatives.head(hard_negative_count)
    hard_negative_keys = {
        normalize_key(r, u)
        for r, u in selected_negative[["run_id", "unit_id"]].itertuples(
            index=False,
            name=None,
        )
    }
    hard_negative_score_cutoff = (
        float(selected_negative["max_score"].min())
        if len(selected_negative)
        else None
    )

    source_column = POLICY_COLUMNS[source_policy]
    _, policy_units = unit_policy_table(source_scored, source_column)
    hit = policy_units["max_score"].ge(source_cfg["threshold"]).fillna(False)
    hard_positive_index = policy_units.index[policy_units["y"].eq(1) & ~hit]
    hard_positive_keys = {
        normalize_key(r, u)
        for r, u in hard_positive_index.to_list()
    }

    return {
        "hard_negative_keys": hard_negative_keys,
        "hard_positive_keys": hard_positive_keys,
        "metadata": {
            "source_candidate": "bagging_5p0pct_x5",
            "source_policy": source_policy,
            "source_alert_threshold": source_cfg["threshold"],
            "source_unit_recall": source_cfg["unit_recall"],
            "source_false_warning_rate": source_cfg["false_warning_rate"],
            "hard_negative_fraction": HARD_NEGATIVE_FRACTION,
            "hard_negative_score_cutoff": hard_negative_score_cutoff,
            "hard_negative_units": len(hard_negative_keys),
            "hard_positive_units": len(hard_positive_keys),
        },
    }


def nested_mining_source_oof(outer_train: pd.DataFrame, outer_fold_number: int):
    inner_splits = grouped_splits(outer_train)
    inner_oof = np.full(len(outer_train), np.nan, dtype=float)
    for inner_fold_number, (tr_idx, va_idx) in enumerate(inner_splits, start=1):
        log(
            f"Mining source outer fold {outer_fold_number}: "
            f"inner fold {inner_fold_number}/{len(inner_splits)}"
        )
        inner_train = outer_train.iloc[tr_idx].copy()
        inner_val = outer_train.iloc[va_idx].copy()
        predictions, _ = fit_predict_bagging_fold(
            inner_train,
            inner_val,
            MINING_SOURCE_RATE,
            MINING_SOURCE_SEEDS,
            inner_fold_number,
            seed_namespace=outer_fold_number * 100_000,
        )
        inner_oof[va_idx] = np.mean(np.vstack(predictions), axis=0)
    if np.isnan(inner_oof).any():
        raise RuntimeError("Nested mining source left rows without OOF predictions")
    return inner_oof


def build_outer_mining_tags(train: pd.DataFrame, splits):
    tags = []
    for outer_fold_number, (tr_idx, _) in enumerate(splits, start=1):
        outer_train = train.iloc[tr_idx].copy().reset_index(drop=True)
        nested_oof = nested_mining_source_oof(outer_train, outer_fold_number)
        mined = mine_hard_examples(outer_train, nested_oof)
        tags.append(mined)
        log(
            f"Outer fold {outer_fold_number} mining: "
            f"{len(mined['hard_negative_keys'])} hard negatives, "
            f"{len(mined['hard_positive_keys'])} hard positives"
        )
    return tags


# ============================================================
# FIXED-WEIGHT COMBINATION AND CALIBRATION
# ============================================================

def register_fixed_blend(
    train: pd.DataFrame,
    splits,
    candidate_results: dict,
    branch_names: list[str],
):
    if len(branch_names) != 2:
        raise ValueError("V5 only permits a fixed two-branch blend")
    name = f"blend_50_50__{branch_names[0]}__{branch_names[1]}"
    left = candidate_results[branch_names[0]]
    right = candidate_results[branch_names[1]]
    raw_oof = 0.5 * left["raw_oof"] + 0.5 * right["raw_oof"]
    config = {
        "kind": "blend",
        "family": "controlled_combination",
        "components": branch_names,
        "weights": [0.5, 0.5],
        "branches": [left["config"], right["config"]],
        "target_rate": None,
    }

    fold_rows = []
    for fold_number, (tr_idx, va_idx) in enumerate(splits, start=1):
        fold_train = train.iloc[tr_idx].copy()
        fold_val = train.iloc[va_idx].copy()
        left_row = left["fold_rows"][fold_number - 1]
        right_row = right["fold_rows"][fold_number - 1]
        rates = [
            row["effective_training_unit_positive_rate_mean"]
            for row in (left_row, right_row)
            if row["effective_training_unit_positive_rate_mean"] is not None
        ]
        fit_info = {
            "effective_training_unit_positive_rate_mean": float(np.mean(rates)),
            "hard_negative_units": max(
                left_row.get("hard_negative_units", 0),
                right_row.get("hard_negative_units", 0),
            ),
            "hard_positive_units": max(
                left_row.get("hard_positive_units", 0),
                right_row.get("hard_positive_units", 0),
            ),
        }
        fold_rows.append(
            fold_metric_row(
                name,
                config,
                fold_number,
                fold_train,
                fold_val,
                raw_oof[va_idx],
                fit_info,
            )
        )

    register_candidate(
        candidate_results,
        name,
        config,
        raw_oof,
        fold_rows,
        train,
    )
    return name


def calibration_comparison(
    y: np.ndarray,
    groups: np.ndarray,
    candidate_name: str,
    raw_oof: np.ndarray,
):
    scores = {
        "none": np.asarray(raw_oof, dtype=float),
        "platt": crossfit_calibration(y, raw_oof, groups, "platt"),
    }
    metrics = {method: probability_metrics(y, values) for method, values in scores.items()}
    none = metrics["none"]
    platt = metrics["platt"]
    pr_damage = float(none["pr_auc"] - platt["pr_auc"])
    roc_damage = float((none["roc_auc"] or 0.0) - (platt["roc_auc"] or 0.0))
    calibration_improvements = {
        metric: platt[metric] < none[metric]
        for metric in ("brier", "ece15", "log_loss")
    }
    improved_metric_count = sum(calibration_improvements.values())
    calibration_improved = (
        calibration_improvements["brier"] and improved_metric_count >= 2
    )
    ranking_guard_pass = (
        pr_damage <= MAX_PLATT_PR_AUC_DAMAGE + 1e-15
        and roc_damage <= MAX_PLATT_ROC_AUC_DAMAGE + 1e-15
    )
    selected = "platt" if calibration_improved and ranking_guard_pass else "none"

    rows = []
    for method in ("none", "platt"):
        row = {
            "scope": "best_bagging" if candidate_name.startswith("bagging_") else "final_candidate",
            "candidate": candidate_name,
            "method": method,
            **metrics[method],
            "pr_auc_delta_vs_none": metrics[method]["pr_auc"] - none["pr_auc"],
            "roc_auc_delta_vs_none": (
                (metrics[method]["roc_auc"] or 0.0) - (none["roc_auc"] or 0.0)
            ),
            "calibration_improved": calibration_improved if method == "platt" else None,
            "calibration_metrics_improved": (
                improved_metric_count if method == "platt" else None
            ),
            "ranking_guard_pass": ranking_guard_pass if method == "platt" else None,
            "selected": method == selected,
        }
        rows.append(row)

    decision = {
        "candidate": candidate_name,
        "selected": selected,
        "calibration_improved": calibration_improved,
        "calibration_improvements": calibration_improvements,
        "calibration_metrics_improved": improved_metric_count,
        "ranking_guard_pass": ranking_guard_pass,
        "platt_pr_auc_damage": pr_damage,
        "platt_roc_auc_damage": roc_damage,
        "max_allowed_pr_auc_damage": MAX_PLATT_PR_AUC_DAMAGE,
        "max_allowed_roc_auc_damage": MAX_PLATT_ROC_AUC_DAMAGE,
        "metrics": metrics,
    }
    return selected, scores[selected], rows, decision


# ============================================================
# FINAL FULL-TRAIN MODEL BUNDLE
# ============================================================

def fit_final_branch(train: pd.DataFrame, config: dict, mining: dict):
    kind = config["kind"]

    if kind == "natural":
        model = fit_single_catboost(train, RANDOM_SEED)
        return {
            "kind": "ensemble",
            "models": [model],
        }, {
            "models": 1,
            "unit_positive_rate_per_sample": [unit_prevalence(train)],
            "rows_per_sample": [int(len(train))],
            "units_per_sample": [int(unit_labels(train).shape[0])],
            "hard_negative_units": 0,
            "hard_positive_units": 0,
        }

    if kind == "hard_positive":
        hard_keys = mining["hard_positive_keys"]
        model = fit_single_catboost(
            train,
            RANDOM_SEED,
            hard_keys,
            config["hard_positive_weight"],
        )
        return {
            "kind": "ensemble",
            "models": [model],
        }, {
            "models": 1,
            "unit_positive_rate_per_sample": [unit_prevalence(train)],
            "rows_per_sample": [int(len(train))],
            "units_per_sample": [int(unit_labels(train).shape[0])],
            "hard_negative_units": 0,
            "hard_positive_units": len(hard_keys),
            "hard_positive_weight": config["hard_positive_weight"],
        }

    if kind in {"bagging", "hard_negative"}:
        models = []
        rows = []
        units = []
        rates = []
        hard_negative_counts = []
        forced = mining["hard_negative_keys"] if kind == "hard_negative" else None
        for model_number, seed in enumerate(config["seeds"], start=1):
            sampled, sample_info = resample_with_forced_negatives(
                train,
                config["target_rate"],
                int(seed),
                forced,
            )
            model = fit_single_catboost(sampled, int(seed))
            models.append(model)
            rows.append(int(len(sampled)))
            units.append(int(unit_labels(sampled).shape[0]))
            rates.append(unit_prevalence(sampled))
            hard_negative_counts.append(sample_info["hard_negative_units_kept"])
            log(f"Final branch fitted bag {model_number}/{len(config['seeds'])}")
        return {
            "kind": "ensemble",
            "models": models,
        }, {
            "models": len(models),
            "unit_positive_rate_per_sample": rates,
            "rows_per_sample": rows,
            "units_per_sample": units,
            "hard_negative_units": int(max(hard_negative_counts, default=0)),
            "hard_positive_units": 0,
        }

    if kind == "stage":
        models_by_stage = {}
        for stage in STAGES:
            subset = train.loc[stage_mask(train, stage)].reset_index(drop=True)
            models_by_stage[stage] = [fit_single_catboost(subset, RANDOM_SEED)]
            log(f"Final stage model fitted: {stage}")
        return {
            "kind": "stage_ensemble",
            "models_by_stage": models_by_stage,
        }, {
            "models": len(STAGES),
            "unit_positive_rate_per_sample": [unit_prevalence(train)] * len(STAGES),
            "rows_per_sample": [
                int(stage_mask(train, stage).sum()) for stage in STAGES
            ],
            "units_per_sample": [int(unit_labels(train).shape[0])] * len(STAGES),
            "hard_negative_units": 0,
            "hard_positive_units": 0,
        }

    if kind == "blend":
        branches = []
        branch_info = []
        for branch_config in config["branches"]:
            branch, info = fit_final_branch(train, branch_config, mining)
            branches.append(branch)
            branch_info.append(info)
        all_rates = [
            rate
            for info in branch_info
            for rate in info["unit_positive_rate_per_sample"]
        ]
        return {
            "kind": "blend",
            "weights": config["weights"],
            "branches": branches,
        }, {
            "models": sum(info["models"] for info in branch_info),
            "unit_positive_rate_per_sample": all_rates,
            "rows_per_sample": [
                rows for info in branch_info for rows in info["rows_per_sample"]
            ],
            "units_per_sample": [
                units for info in branch_info for units in info["units_per_sample"]
            ],
            "hard_negative_units": max(
                info["hard_negative_units"] for info in branch_info
            ),
            "hard_positive_units": max(
                info["hard_positive_units"] for info in branch_info
            ),
            "branches": branch_info,
        }

    raise ValueError(f"Unsupported final candidate kind: {kind}")


def predict_bundle(bundle: dict, df: pd.DataFrame):
    kind = bundle["kind"]
    if kind == "ensemble":
        return v3_predict_models(bundle["models"], df)

    if kind == "stage_ensemble":
        pred = np.full(len(df), np.nan, dtype=float)
        covered = np.zeros(len(df), dtype=int)
        for stage, models in bundle["models_by_stage"].items():
            mask = stage_mask(df, stage).to_numpy()
            pred[mask] = v3_predict_models(
                models,
                df.loc[mask].reset_index(drop=True),
            )
            covered[mask] += 1
        if np.isnan(pred).any() or not np.all(covered == 1):
            raise RuntimeError("Final stage bundle did not route every row exactly once")
        return pred

    if kind == "blend":
        predictions = [predict_bundle(branch, df) for branch in bundle["branches"]]
        weights = np.asarray(bundle["weights"], dtype=float)
        weights = weights / weights.sum()
        return np.average(np.vstack(predictions), axis=0, weights=weights)

    raise ValueError(f"Unknown model bundle kind: {kind}")


# ============================================================
# OUTPUT / REPORT HELPERS
# ============================================================

def save_development_tables(candidate_results: dict, selected_name: str | None):
    comparison = comparison_frame(candidate_results, selected_name)
    comparison.to_csv(RESULTS_DIR / "v5_candidate_comparison.csv", index=False)

    fold_rows = [
        row
        for result in candidate_results.values()
        for row in result["fold_rows"]
    ]
    pd.DataFrame(fold_rows).to_csv(
        RESULTS_DIR / "v5_cv_fold_metrics.csv",
        index=False,
    )

    policy_rows = [
        dict(row)
        for result in candidate_results.values()
        for row in result["policy_rows"]
    ]
    for row in policy_rows:
        result = candidate_results[row["candidate"]]
        row["selected_for_candidate"] = (
            row["policy"] == result["selected_raw_alert_policy"]
        )
        row["selected_final"] = (
            row["candidate"] == selected_name
            and row["policy"] == result["selected_raw_alert_policy"]
        )
    pd.DataFrame(policy_rows).to_csv(
        RESULTS_DIR / "v5_alert_policy_comparison.csv",
        index=False,
    )


def candidate_report(result: dict):
    return {
        "config": result["config"],
        "number_of_models": candidate_model_count(result["config"]),
        "effective_training_unit_positive_rate": result[
            "effective_training_unit_positive_rate"
        ],
        "mean_fold_pr_auc": result["mean_fold_pr_auc"],
        "std_fold_pr_auc": result["std_fold_pr_auc"],
        "min_fold_pr_auc": result["min_fold_pr_auc"],
        "raw_probability_metrics": result["raw_probability_metrics"],
        "selected_raw_alert_policy": result["selected_raw_alert_policy"],
        "selected_raw_alert_policy_config": result[
            "selected_raw_alert_policy_config"
        ],
        "raw_alert_policies": result["raw_alert_policies"],
    }


def validation_per_run(
    scored_validation: pd.DataFrame,
    probability_col: str,
    selected_policy: str,
    alert_threshold: float,
):
    probability = per_run_probability_metrics(scored_validation, probability_col)
    unit_rows = []
    policy_col = POLICY_COLUMNS[selected_policy]
    for run_id, group in scored_validation.groupby("run_id", sort=True):
        metrics = evaluate_unit_policy_all_units(group, policy_col, alert_threshold)
        unit_rows.append(
            {
                "run_id": run_id,
                "units": metrics["positive_units"] + metrics["negative_units"],
                "positive_units": metrics["positive_units"],
                "negative_units": metrics["negative_units"],
                "unit_recall": metrics["unit_recall"],
                "false_warning_rate": metrics["false_warning_rate"],
                "unit_precision": metrics["unit_precision"],
                "median_first_alert_station_index": metrics[
                    "median_first_alert_station_index"
                ],
                "alerted_positive_units": metrics["alerted_positive_units"],
                "alerted_negative_units": metrics["alerted_negative_units"],
            }
        )
    return probability.merge(pd.DataFrame(unit_rows), on="run_id", how="left")


def extract_validation_comparison(version: str, report: dict):
    probability = report["probability_metrics"]
    f1 = report["row_metrics_at_frozen_f1_threshold"]
    f2 = report["row_metrics_at_frozen_f2_threshold"]
    unit = report["unit_metrics_at_frozen_alert_policy"]
    return {
        "version": version,
        "validation_pr_auc": probability["pr_auc"],
        "validation_roc_auc": probability["roc_auc"],
        "validation_brier": probability["brier"],
        "validation_precision": f1["precision"],
        "validation_recall": f1["recall"],
        "validation_f1": f1["f1"],
        "validation_f2": f2["f2"],
        "validation_unit_recall": unit["unit_recall"],
        "validation_false_warning_rate": unit["false_warning_rate"],
        "validation_unit_precision": unit["unit_precision"],
        "median_first_alert_station_index": unit[
            "median_first_alert_station_index"
        ],
    }


def load_prior_validation_comparison(v5_validation_report: dict):
    # Explicit allowlist: validation-only reports. Never glob results/.
    historical = [
        ("V2", RESULTS_DIR / "validation_report.json"),
        ("V3", RESULTS_DIR / "v3_validation_report.json"),
        ("V4", RESULTS_DIR / "v4_validation_report.json"),
    ]
    rows = []
    for version, path in historical:
        if path.exists():
            rows.append(
                extract_validation_comparison(
                    version,
                    json.loads(path.read_text()),
                )
            )
        else:
            log(f"Prior validation report missing; comparison will skip {version}: {path.name}")
    rows.append(extract_validation_comparison("V5", v5_validation_report))
    return rows

def print_final_summary(summary: dict, comparison_rows: list[dict]):
    print("\n" + "=" * 100)
    print("V5 FINAL FROZEN VALIDATION SUMMARY")
    print("=" * 100)
    ordered = [
        ("Candidate", summary["candidate_name"]),
        ("Number of models", summary["number_of_models"]),
        (
            "Effective training unit prevalence",
            summary["effective_training_unit_positive_rate"],
        ),
        ("OOF PR-AUC (reported probability)", summary["oof_pr_auc"]),
        ("OOF PR-AUC (raw selection score)", summary["oof_raw_pr_auc"]),
        ("Mean CV PR-AUC", summary["mean_cv_pr_auc"]),
        ("Std CV PR-AUC", summary["std_cv_pr_auc"]),
        ("Minimum fold PR-AUC", summary["minimum_fold_pr_auc"]),
        ("OOF ROC-AUC (reported probability)", summary["oof_roc_auc"]),
        ("OOF ROC-AUC (raw selection score)", summary["oof_raw_roc_auc"]),
        ("OOF Brier (reported probability)", summary["oof_brier"]),
        ("OOF Brier (raw selection score)", summary["oof_raw_brier"]),
        ("Selected calibration", summary["selected_calibration"]),
        ("Selected alert policy", summary["selected_alert_policy"]),
        ("Alert threshold", summary["alert_threshold"]),
        ("OOF unit recall", summary["oof_unit_recall"]),
        ("OOF false-warning rate", summary["oof_false_warning_rate"]),
        ("OOF unit precision", summary["oof_unit_precision"]),
        ("Validation PR-AUC", summary["validation_pr_auc"]),
        ("Validation ROC-AUC", summary["validation_roc_auc"]),
        ("Validation Brier", summary["validation_brier"]),
        ("Validation precision", summary["validation_precision_at_f1_threshold"]),
        ("Validation recall", summary["validation_recall_at_f1_threshold"]),
        ("Validation F1", summary["validation_f1"]),
        ("Validation F2", summary["validation_f2_at_f2_threshold"]),
        ("Validation unit recall", summary["validation_unit_recall"]),
        (
            "Validation false-warning rate",
            summary["validation_false_warning_rate"],
        ),
        ("Validation unit precision", summary["validation_unit_precision"]),
        (
            "Median first warning station index",
            summary["validation_median_first_alert_station_index"],
        ),
    ]
    for label, value in ordered:
        if isinstance(value, float):
            print(f"{label}: {value:.8f}")
        else:
            print(f"{label}: {value}")

    print("\n" + "=" * 100)
    print("V2 vs V3 vs V4 vs V5 VALIDATION")
    print("=" * 100)
    display_columns = [
        "version",
        "validation_pr_auc",
        "validation_roc_auc",
        "validation_brier",
        "validation_unit_recall",
        "validation_false_warning_rate",
        "validation_unit_precision",
        "median_first_alert_station_index",
    ]
    print(pd.DataFrame(comparison_rows)[display_columns].to_string(index=False))


# ============================================================
# MAIN EXPERIMENT
# ============================================================

def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if not TRAIN_PATH.exists() or not VALIDATION_PATH.exists():
        raise FileNotFoundError(
            "Missing generated_features/train.pkl or validation.pkl. "
            "V5 does not regenerate features."
        )

    # Development begins with train only. Validation is deliberately loaded
    # after candidate/calibration/policy selection and final fitting are frozen.
    train = pd.read_pickle(TRAIN_PATH)
    train = train[train[TARGET_COLUMN].notna()].reset_index(drop=True)
    validate_frame(train, "train")

    log("=" * 90)
    log("DEFECT MODEL V5 - CONTROLLED TRAIN-OOF EXPERIMENT")
    log("=" * 90)
    log(f"Train rows={len(train):,}, runs={train.run_id.nunique()}, units={len(unit_labels(train)):,}")
    log(f"Natural train unit defect prevalence={100*unit_prevalence(train):.3f}%")
    log("Exactly 30 corrected V5 causal features; no test access")

    y = train[TARGET_COLUMN].astype(int).to_numpy()
    groups = train["run_id"].astype(str).to_numpy()
    splits = grouped_splits(train)
    for tr_idx, va_idx in splits:
        train_runs = set(groups[tr_idx])
        heldout_runs = set(groups[va_idx])
        if not train_runs.isdisjoint(heldout_runs):
            raise RuntimeError("GroupKFold leaked a run across train and holdout")

    candidate_results = {}

    # --------------------------------------------------------
    # 1-2. Natural baseline and shared x5/x7 bagging grid
    # --------------------------------------------------------
    bagging_names = run_initial_sweep(train, splits, candidate_results)
    best_bagging = max(bagging_names, key=lambda n: candidate_rank(candidate_results[n]))
    log(f"Best bagging candidate from train OOF: {best_bagging}")
    save_development_tables(candidate_results, None)

    # --------------------------------------------------------
    # 3-5. Nested OOF mining, hard negatives, hard positives
    # --------------------------------------------------------
    outer_mining = build_outer_mining_tags(train, splits)

    hard_negative_name = "hard_negative_top10_bagging_5p0pct_x5"
    hard_negative_config = {
        "kind": "hard_negative",
        "family": "hard_negative",
        "components": ["balanced_bagging", "hard_negative_top10"],
        "target_rate": MINING_SOURCE_RATE,
        "seeds": list(MINING_SOURCE_SEEDS),
        "hard_negative_fraction": HARD_NEGATIVE_FRACTION,
        "mining_source": "bagging_5p0pct_x5_nested_group_oof",
    }
    evaluate_generic_candidate(
        train,
        splits,
        candidate_results,
        hard_negative_name,
        hard_negative_config,
        outer_mining,
    )

    hard_positive_names = []
    for weight in HARD_POSITIVE_WEIGHTS:
        weight_label = str(weight).replace(".", "p")
        name = f"hard_positive_w{weight_label}_natural"
        config = {
            "kind": "hard_positive",
            "family": "hard_positive",
            "components": ["natural", f"hard_positive_weight_{weight}"],
            "target_rate": None,
            "hard_positive_weight": weight,
            "mining_source": "bagging_5p0pct_x5_nested_group_oof",
        }
        evaluate_generic_candidate(
            train,
            splits,
            candidate_results,
            name,
            config,
            outer_mining,
        )
        hard_positive_names.append(name)

    # --------------------------------------------------------
    # 6. Natural stage-specialized CatBoost
    # --------------------------------------------------------
    stage_name = "stage_specialized_natural"
    stage_config = {
        "kind": "stage",
        "family": "stage_specialized",
        "components": ["stage_specialized"],
        "target_rate": None,
        "stage_boundaries": STAGES,
    }
    evaluate_generic_candidate(
        train,
        splits,
        candidate_results,
        stage_name,
        stage_config,
    )

    # --------------------------------------------------------
    # 7. Combine only if an enhancer strictly beats best bagging
    # --------------------------------------------------------
    # Per the pre-registered gate, only hard-negative mining or stage
    # specialization may trigger a combined candidate. Hard-positive weighting
    # remains a standalone controlled experiment.
    enhancer_names = [hard_negative_name, stage_name]
    helpful_enhancers = [
        name
        for name in enhancer_names
        if candidate_rank(candidate_results[name])
        > candidate_rank(candidate_results[best_bagging])
    ]
    combined_name = None
    if helpful_enhancers:
        best_enhancer = max(
            helpful_enhancers,
            key=lambda n: candidate_rank(candidate_results[n]),
        )
        combined_name = register_fixed_blend(
            train,
            splits,
            candidate_results,
            [best_bagging, best_enhancer],
        )
        combined_decision = {
            "created": True,
            "reason": "At least one enhancer strictly outranked best bagging on the frozen OOF objective",
            "best_bagging": best_bagging,
            "helpful_enhancers": helpful_enhancers,
            "selected_enhancer": best_enhancer,
            "combined_candidate": combined_name,
            "weights": [0.5, 0.5],
        }
    else:
        combined_decision = {
            "created": False,
            "reason": "No hard-example or stage candidate strictly outranked best bagging on train OOF",
            "best_bagging": best_bagging,
            "helpful_enhancers": [],
        }
        log("Combination gate closed: no enhancer beat best bagging")

    # Every model-selection decision below is still train OOF only.
    selected_candidate = max(
        candidate_results,
        key=lambda name: candidate_rank(candidate_results[name]),
    )
    selected_result = candidate_results[selected_candidate]
    log(f"Frozen V5 training candidate: {selected_candidate}")

    # Compare none vs Platt for the best bagging candidate, and repeat for the
    # final winner if it is different. Alerts remain in raw-score space.
    calibration_rows = []
    _, _, rows, best_bag_calibration_decision = calibration_comparison(
        y,
        groups,
        best_bagging,
        candidate_results[best_bagging]["raw_oof"],
    )
    calibration_rows.extend(rows)

    if selected_candidate == best_bagging:
        selected_calibration = best_bag_calibration_decision["selected"]
        selected_calibrated_oof = (
            selected_result["raw_oof"]
            if selected_calibration == "none"
            else crossfit_calibration(
                y,
                selected_result["raw_oof"],
                groups,
                "platt",
            )
        )
        final_calibration_decision = best_bag_calibration_decision
    else:
        (
            selected_calibration,
            selected_calibrated_oof,
            rows,
            final_calibration_decision,
        ) = calibration_comparison(
            y,
            groups,
            selected_candidate,
            selected_result["raw_oof"],
        )
        calibration_rows.extend(rows)

    pd.DataFrame(calibration_rows).to_csv(
        RESULTS_DIR / "v5_calibration_comparison.csv",
        index=False,
    )

    raw_oof = selected_result["raw_oof"]
    oof_probability = probability_metrics(y, selected_calibrated_oof)
    final_calibrator = fit_final_calibrator(y, raw_oof, selected_calibration)

    # Raw score space is deliberately frozen for thresholds and alert policies.
    # This keeps OOF thresholds on the exact scale produced by final models.
    row_thresholds = choose_row_thresholds(y, raw_oof)
    selected_policy = selected_result["selected_raw_alert_policy"]
    selected_policy_cfg = selected_result["selected_raw_alert_policy_config"]

    # The global 5%x5 OOF source is safe for the final full-train mining tags:
    # every train row was predicted without its run, and validation is untouched.
    global_mining = mine_hard_examples(
        train,
        candidate_results["bagging_5p0pct_x5"]["raw_oof"],
    )

    final_bundle, final_fit_info = fit_final_branch(
        train,
        selected_result["config"],
        global_mining,
    )
    effective_final_rate = float(
        np.mean(final_fit_info["unit_positive_rate_per_sample"])
    )

    model_artifact = {
        "version": "v5",
        "selected_candidate": selected_candidate,
        "feature_order": DEFECT_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "bundle": final_bundle,
    }
    joblib.dump(model_artifact, MODEL_DIR / "defect_v5_models.joblib")
    joblib.dump(final_calibrator, MODEL_DIR / "defect_v5_calibrator.joblib")

    config = {
        "version": "v5",
        "feature_count": 30,
        "features": DEFECT_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "catboost_params": CATBOOST_PARAMS,
        "selected_candidate": selected_candidate,
        "selected_candidate_config": selected_result["config"],
        "number_of_models": candidate_model_count(selected_result["config"]),
        "effective_training_unit_positive_rate": effective_final_rate,
        "selected_calibration": selected_calibration,
        "calibration_applies_to_probability_reporting": True,
        "alert_score_space": "raw_probability",
        "row_threshold_score_space": "raw_probability",
        "row_thresholds": row_thresholds,
        "selected_alert_policy": selected_policy,
        "selected_alert_score_column": POLICY_COLUMNS[selected_policy],
        "selected_alert_threshold": selected_policy_cfg["threshold"],
        "false_warning_cap": FWR_CAP,
        "group_kfold_splits": N_SPLITS,
        "bagging_rates": BAGGING_RATES,
        "bagging_seeds_5": BAGGING_SEEDS_5,
        "bagging_seeds_7": BAGGING_SEEDS_7,
        "hard_example_mining": global_mining["metadata"],
        "combination_decision": combined_decision,
        "random_seed": RANDOM_SEED,
        "old_consumed_test_accessed": False,
    }
    write_json(MODEL_DIR / "defect_v5_config.json", config)

    # Save all train-side outputs before opening validation.
    save_development_tables(candidate_results, selected_candidate)
    fold_assignments = [
        {
            "fold": fold_number,
            "train_runs": sorted(set(groups[tr_idx])),
            "heldout_runs": sorted(set(groups[va_idx])),
        }
        for fold_number, (tr_idx, va_idx) in enumerate(splits, start=1)
    ]
    training_report = {
        "version": "v5",
        "feature_count": 30,
        "train_rows": int(len(train)),
        "train_runs": int(train["run_id"].nunique()),
        "train_units": int(unit_labels(train).shape[0]),
        "train_positive_units": int(unit_labels(train)[TARGET_COLUMN].sum()),
        "natural_train_unit_positive_rate": unit_prevalence(train),
        "selection_objective": [
            "maximum unit recall subject to false_warning_rate <= 0.05",
            "pooled PR-AUC",
            "minimum-fold PR-AUC",
            "ROC-AUC",
            "unit precision",
            "earlier median first warning",
            "Brier",
        ],
        "fold_assignments": fold_assignments,
        "candidate_results": {
            name: candidate_report(result)
            for name, result in candidate_results.items()
        },
        "best_bagging_candidate": best_bagging,
        "nested_mining": {
            "source": "fixed bagging_5p0pct_x5",
            "outer_fold_metadata": [item["metadata"] for item in outer_mining],
            "final_full_train_metadata": global_mining["metadata"],
        },
        "combination_decision": combined_decision,
        "selected_candidate": selected_candidate,
        "selected_calibration": selected_calibration,
        "best_bagging_calibration_decision": best_bag_calibration_decision,
        "final_calibration_decision": final_calibration_decision,
        "oof_probability_metrics_after_selected_calibration": oof_probability,
        "row_thresholds_on_raw_oof": row_thresholds,
        "selected_alert_policy": selected_policy,
        "selected_alert_policy_config": selected_policy_cfg,
        "final_fit_info": final_fit_info,
        "validation_used_for_selection": False,
        "old_consumed_test_accessed": False,
    }

    selected_oof_scored = train.copy()
    selected_oof_scored["score"] = raw_oof
    selected_oof_scored["probability"] = selected_calibrated_oof
    selected_oof_scored = add_policy_scores(selected_oof_scored, "score")
    selected_oof_per_run = validation_per_run(
        selected_oof_scored,
        "probability",
        selected_policy,
        selected_policy_cfg["threshold"],
    )
    selected_oof_per_run.to_csv(
        RESULTS_DIR / "v5_per_run_oof_metrics.csv",
        index=False,
    )
    training_report["selected_candidate_oof_per_run"] = (
        selected_oof_per_run.where(pd.notna(selected_oof_per_run), None)
        .to_dict(orient="records")
    )
    write_json(RESULTS_DIR / "v5_training_report.json", training_report)

    # --------------------------------------------------------
    # FROZEN VALIDATION: first and only V5 validation prediction
    # --------------------------------------------------------
    log("Train-side system frozen. Loading validation for one final evaluation.")
    validation = pd.read_pickle(VALIDATION_PATH)
    validation = validation[validation[TARGET_COLUMN].notna()].reset_index(drop=True)
    validate_frame(validation, "validation")
    if not set(train["run_id"].astype(str)).isdisjoint(
        set(validation["run_id"].astype(str))
    ):
        raise RuntimeError("Train and validation run IDs overlap")

    y_val = validation[TARGET_COLUMN].astype(int).to_numpy()
    val_raw = predict_bundle(model_artifact["bundle"], validation)
    val_probability_score = apply_calibrator(
        final_calibrator,
        val_raw,
        selected_calibration,
    )
    val_raw_probability = probability_metrics(y_val, val_raw)
    val_probability = probability_metrics(y_val, val_probability_score)

    val_scored = validation.copy()
    val_scored["score"] = val_raw
    val_scored["probability"] = val_probability_score
    val_scored = add_policy_scores(val_scored, "score")

    val_f1 = row_metrics_at_threshold(
        y_val,
        val_raw,
        row_thresholds["max_f1"]["threshold"],
    )
    val_f2 = row_metrics_at_threshold(
        y_val,
        val_raw,
        row_thresholds["max_f2"]["threshold"],
    )
    val_unit = evaluate_unit_policy_all_units(
        val_scored,
        POLICY_COLUMNS[selected_policy],
        selected_policy_cfg["threshold"],
    )

    val_per_run = validation_per_run(
        val_scored,
        "probability",
        selected_policy,
        selected_policy_cfg["threshold"],
    )
    val_per_run.to_csv(
        RESULTS_DIR / "v5_validation_per_run.csv",
        index=False,
    )

    validation_report = {
        "version": "v5",
        "feature_count": 30,
        "selected_candidate": selected_candidate,
        "selected_calibration": selected_calibration,
        "probability_score_space": (
            "platt_calibrated_probability"
            if selected_calibration == "platt"
            else "raw_probability"
        ),
        "alert_score_space": "raw_probability",
        "row_threshold_score_space": "raw_probability",
        "selected_alert_policy": selected_policy,
        "selected_alert_threshold": selected_policy_cfg["threshold"],
        "validation_rows": int(len(validation)),
        "validation_runs": int(validation["run_id"].nunique()),
        "validation_units": int(unit_labels(validation).shape[0]),
        "validation_row_positive_rate": float(validation[TARGET_COLUMN].mean()),
        "validation_unit_positive_rate": unit_prevalence(validation),
        "raw_probability_metrics": val_raw_probability,
        "probability_metrics": val_probability,
        "row_metrics_at_frozen_f1_threshold": val_f1,
        "row_metrics_at_frozen_f2_threshold": val_f2,
        "unit_metrics_at_frozen_alert_policy": val_unit,
        "selection_used_validation": False,
        "old_consumed_test_accessed": False,
    }

    comparison_rows = load_prior_validation_comparison(validation_report)
    validation_report["v2_v3_v4_v5_validation_comparison"] = comparison_rows
    write_json(RESULTS_DIR / "v5_validation_report.json", validation_report)

    selected_prob = selected_result["raw_probability_metrics"]
    selected_oof_unit = selected_result["selected_raw_alert_policy_config"]
    summary = {
        "version": "v5",
        "feature_count": 30,
        "candidate_name": selected_candidate,
        "selected_training_strategy": selected_candidate,
        "number_of_models": candidate_model_count(selected_result["config"]),
        "effective_training_unit_positive_rate": effective_final_rate,
        "oof_pr_auc": oof_probability["pr_auc"],
        "oof_raw_pr_auc": selected_prob["pr_auc"],
        "pooled_oof_pr_auc_raw": selected_prob["pr_auc"],
        "mean_cv_pr_auc": selected_result["mean_fold_pr_auc"],
        "std_cv_pr_auc": selected_result["std_fold_pr_auc"],
        "minimum_fold_pr_auc": selected_result["min_fold_pr_auc"],
        "oof_roc_auc": oof_probability["roc_auc"],
        "oof_raw_roc_auc": selected_prob["roc_auc"],
        "oof_brier": oof_probability["brier"],
        "oof_raw_brier": selected_prob["brier"],
        "selected_calibration": selected_calibration,
        "selected_alert_policy": selected_policy,
        "alert_score_space": "raw_probability",
        "alert_threshold": selected_policy_cfg["threshold"],
        "oof_unit_recall": selected_oof_unit["unit_recall"],
        "oof_false_warning_rate": selected_oof_unit["false_warning_rate"],
        "oof_unit_precision": selected_oof_unit["unit_precision"],
        "oof_median_first_alert_station_index": selected_oof_unit[
            "median_first_alert_station_index"
        ],
        "validation_pr_auc": val_probability["pr_auc"],
        "validation_raw_pr_auc": val_raw_probability["pr_auc"],
        "validation_roc_auc": val_probability["roc_auc"],
        "validation_raw_roc_auc": val_raw_probability["roc_auc"],
        "validation_brier": val_probability["brier"],
        "validation_raw_brier": val_raw_probability["brier"],
        "validation_precision_at_f1_threshold": val_f1["precision"],
        "validation_recall_at_f1_threshold": val_f1["recall"],
        "validation_f1": val_f1["f1"],
        "validation_f2_at_f2_threshold": val_f2["f2"],
        "validation_unit_recall": val_unit["unit_recall"],
        "validation_false_warning_rate": val_unit["false_warning_rate"],
        "validation_unit_precision": val_unit["unit_precision"],
        "validation_median_first_alert_station_index": val_unit[
            "median_first_alert_station_index"
        ],
        "validation_primary_objective_improves_over_v4": (
            (
                val_unit["unit_recall"]
                > next(
                    (
                        row["validation_unit_recall"]
                        for row in comparison_rows
                        if row["version"] == "V4"
                    ),
                    float("inf"),
                )
            )
            and val_unit["false_warning_rate"] <= FWR_CAP
        ),
        "old_consumed_test_accessed": False,
    }
    pd.DataFrame([summary]).to_csv(
        RESULTS_DIR / "v5_model_summary.csv",
        index=False,
    )

    print_final_summary(summary, comparison_rows)
    print("\nV5 DEVELOPMENT COMPLETE.")
    print("Validation was evaluated only after the train-side system was frozen.")
    print("The old consumed test set was not accessed. Stop before any new test evaluation.")


if __name__ == "__main__":
    main()
