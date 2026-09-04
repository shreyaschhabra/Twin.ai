from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    fbeta_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold

from feature_schema import CATEGORICAL_FEATURES, DEFECT_FEATURES, TARGET_COLUMN

warnings.filterwarnings("ignore")

# ============================================================
# PATHS / CONSTANTS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
FEATURE_DIR = ROOT / "generated_features"
RESULTS_DIR = ROOT / "results"
MODEL_DIR = ROOT / "saved_models"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

RANDOM_SEED = 42
N_SPLITS = 5
FWR_CAP = 0.05

# Five independent negative-unit samples for balanced bagging.
BAGGING_SEEDS = [42, 52, 62, 72, 82]

CATBOOST_PARAMS = dict(
    depth=4,
    learning_rate=0.05,
    iterations=500,
    l2_leaf_reg=5,
    loss_function="Logloss",
    random_seed=RANDOM_SEED,
    verbose=False,
    allow_writing_files=False,
    thread_count=-1,
)

# IMPORTANT:
# No class weighting in V3.
# The V2 experiment already showed that unweighted CatBoost was better.
CANDIDATES = {
    "natural": {
        "target_unit_positive_rate": None,
        "bagging": False,
    },
    "resample_4pct": {
        "target_unit_positive_rate": 0.04,
        "bagging": False,
    },
    "resample_5pct": {
        "target_unit_positive_rate": 0.05,
        "bagging": False,
    },
    "resample_6pct": {
        "target_unit_positive_rate": 0.06,
        "bagging": False,
    },
    "bagging_5pct_x5": {
        "target_unit_positive_rate": 0.05,
        "bagging": True,
    },
}

assert len(DEFECT_FEATURES) == 30, (
    f"Expected exactly 30 features, got {len(DEFECT_FEATURES)}"
)
assert TARGET_COLUMN not in DEFECT_FEATURES


# ============================================================
# BASIC DATA / MODEL HELPERS
# ============================================================

def prepare_X(df: pd.DataFrame):
    X = df[DEFECT_FEATURES].copy()

    cat_cols = [c for c in CATEGORICAL_FEATURES if c in X.columns]
    for c in cat_cols:
        X[c] = X[c].fillna("MISSING").astype(str)

    cat_idx = [X.columns.get_loc(c) for c in cat_cols]
    return X, cat_idx


def fit_single_catboost(df: pd.DataFrame, seed: int):
    X, cat_idx = prepare_X(df)
    y = df[TARGET_COLUMN].astype(int).to_numpy()

    params = dict(CATBOOST_PARAMS)
    params["random_seed"] = int(seed)

    model = CatBoostClassifier(**params)
    model.fit(
        X,
        y,
        cat_features=cat_idx,
    )
    return model


def predict_models(models, df: pd.DataFrame):
    X, _ = prepare_X(df)

    if not isinstance(models, (list, tuple)):
        models = [models]

    preds = [
        model.predict_proba(X)[:, 1]
        for model in models
    ]

    return np.mean(np.vstack(preds), axis=0)


def safe_pr_auc(y, p):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)

    if len(np.unique(y)) <= 1:
        return float(np.mean(y))

    return float(average_precision_score(y, p))


def safe_roc_auc(y, p):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)

    if len(np.unique(y)) <= 1:
        return None

    return float(roc_auc_score(y, p))


def ece(y, p, bins=15):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)

    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0

    for i in range(bins):
        if i < bins - 1:
            mask = (p >= edges[i]) & (p < edges[i + 1])
        else:
            mask = (p >= edges[i]) & (p <= edges[i + 1])

        if mask.any():
            total += (
                mask.mean()
                * abs(float(y[mask].mean()) - float(p[mask].mean()))
            )

    return float(total)


def probability_metrics(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-8, 1 - 1e-8)

    return {
        "pr_auc": safe_pr_auc(y, p),
        "roc_auc": safe_roc_auc(y, p),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece15": ece(y, p, bins=15),
        "mean_predicted_probability": float(np.mean(p)),
        "actual_positive_rate": float(np.mean(y)),
    }


# ============================================================
# UNIT-LEVEL RESAMPLING
# ============================================================

def unit_labels(df: pd.DataFrame):
    """
    One label per independent manufacturing unit.

    A unit is positive if any of its labelled station-entry rows has y_defect=1.
    Because y_defect is final-QA failure, all labelled rows for a unit should
    agree, but max() is a safe aggregation.
    """
    return (
        df.groupby(["run_id", "unit_id"], as_index=False)[TARGET_COLUMN]
        .max()
    )


def unit_prevalence(df: pd.DataFrame):
    u = unit_labels(df)
    if len(u) == 0:
        return float("nan")
    return float(u[TARGET_COLUMN].mean())


def resample_training_units(
    df: pd.DataFrame,
    target_rate: float | None,
    seed: int,
):
    """
    IMPORTANT:
    Resampling happens by WHOLE UNIT, never by station row.

    - Keep every defective unit.
    - Randomly sample PASS units until the selected unit dataset reaches
      approximately target_rate.
    - Keep every station row belonging to every selected unit.
    - If target_rate is None, return the original fold unchanged.
    """

    if target_rate is None:
        return df.copy().reset_index(drop=True)

    if not (0.0 < target_rate < 1.0):
        raise ValueError(f"Invalid target_rate={target_rate}")

    labels = unit_labels(df)

    positive = labels[labels[TARGET_COLUMN].eq(1)].copy()
    negative = labels[labels[TARGET_COLUMN].eq(0)].copy()

    n_pos = len(positive)
    n_neg = len(negative)

    if n_pos == 0:
        raise ValueError("Training fold contains zero defective units")

    # target_rate = n_pos / (n_pos + n_neg_needed)
    n_neg_needed = int(
        round(n_pos * (1.0 - target_rate) / target_rate)
    )

    # If requested prevalence is <= natural prevalence,
    # no undersampling is required.
    if n_neg_needed >= n_neg:
        return df.copy().reset_index(drop=True)

    rng = np.random.default_rng(seed)
    chosen_idx = rng.choice(
        n_neg,
        size=n_neg_needed,
        replace=False,
    )

    chosen_negative = negative.iloc[chosen_idx]

    selected_units = pd.concat(
        [
            positive[["run_id", "unit_id"]],
            chosen_negative[["run_id", "unit_id"]],
        ],
        ignore_index=True,
    )

    out = df.merge(
        selected_units,
        on=["run_id", "unit_id"],
        how="inner",
        validate="many_to_one",
    )

    # Safety: every positive unit from original fold must still exist.
    original_positive_keys = set(
        map(tuple, positive[["run_id", "unit_id"]].to_numpy())
    )

    output_labels = unit_labels(out)
    output_positive = output_labels[output_labels[TARGET_COLUMN].eq(1)]

    output_positive_keys = set(
        map(tuple, output_positive[["run_id", "unit_id"]].to_numpy())
    )

    assert original_positive_keys == output_positive_keys, (
        "A defective unit was accidentally dropped during resampling"
    )

    return out.reset_index(drop=True)


# ============================================================
# FIT ONE CANDIDATE
# ============================================================

def fit_candidate_models(
    fold_train: pd.DataFrame,
    candidate_name: str,
    fold_number: int,
):
    cfg = CANDIDATES[candidate_name]
    target_rate = cfg["target_unit_positive_rate"]

    if not cfg["bagging"]:
        seed = RANDOM_SEED + fold_number * 100

        sampled = resample_training_units(
            fold_train,
            target_rate=target_rate,
            seed=seed,
        )

        model = fit_single_catboost(
            sampled,
            seed=RANDOM_SEED,
        )

        return [model], {
            "training_rows_per_model": [int(len(sampled))],
            "training_units_per_model": [
                int(unit_labels(sampled).shape[0])
            ],
            "training_unit_positive_rate_per_model": [
                unit_prevalence(sampled)
            ],
        }

    # Balanced bagging:
    # every model sees ALL defective units but a different PASS subset.
    models = []
    rows = []
    units = []
    rates = []

    for bag_seed in BAGGING_SEEDS:
        # Fold offset ensures deterministic but different samples per CV fold.
        effective_seed = bag_seed + fold_number * 1000

        sampled = resample_training_units(
            fold_train,
            target_rate=target_rate,
            seed=effective_seed,
        )

        model = fit_single_catboost(
            sampled,
            seed=bag_seed,
        )

        models.append(model)
        rows.append(int(len(sampled)))
        units.append(int(unit_labels(sampled).shape[0]))
        rates.append(unit_prevalence(sampled))

    return models, {
        "training_rows_per_model": rows,
        "training_units_per_model": units,
        "training_unit_positive_rate_per_model": rates,
    }


# ============================================================
# GROUPED OOF FOR ONE CANDIDATE
# ============================================================

def grouped_oof_candidate(train: pd.DataFrame, candidate_name: str):
    y = train[TARGET_COLUMN].astype(int).to_numpy()
    groups = train["run_id"].astype(str).to_numpy()

    unique_runs = np.unique(groups)
    n_splits = min(N_SPLITS, len(unique_runs))

    splitter = GroupKFold(n_splits=n_splits)

    oof = np.full(len(train), np.nan, dtype=float)
    fold_rows = []

    dummy_X = np.zeros((len(train), 1))

    for fold, (tr_idx, va_idx) in enumerate(
        splitter.split(dummy_X, y, groups),
        start=1,
    ):
        fold_train = train.iloc[tr_idx].copy()
        fold_val = train.iloc[va_idx].copy()

        train_runs = sorted(fold_train["run_id"].astype(str).unique())
        val_runs = sorted(fold_val["run_id"].astype(str).unique())

        assert set(train_runs).isdisjoint(val_runs)

        models, fit_info = fit_candidate_models(
            fold_train,
            candidate_name=candidate_name,
            fold_number=fold,
        )

        pred = predict_models(models, fold_val)
        oof[va_idx] = pred

        m = probability_metrics(
            fold_val[TARGET_COLUMN].astype(int).to_numpy(),
            pred,
        )

        fold_rows.append(
            {
                "candidate": candidate_name,
                "fold": fold,
                "train_runs": "|".join(train_runs),
                "validation_runs": "|".join(val_runs),
                "natural_fold_train_unit_positive_rate": unit_prevalence(
                    fold_train
                ),
                "effective_training_unit_positive_rate_mean": float(
                    np.mean(
                        fit_info[
                            "training_unit_positive_rate_per_model"
                        ]
                    )
                ),
                "models_in_candidate": len(models),
                "heldout_row_positive_rate": float(
                    fold_val[TARGET_COLUMN].mean()
                ),
                **m,
            }
        )

        print(
            f"[{candidate_name}] fold {fold}/{n_splits} | "
            f"PR-AUC={m['pr_auc']:.5f} | "
            f"ROC-AUC={m['roc_auc'] if m['roc_auc'] is not None else 'NA'} | "
            f"Brier={m['brier']:.5f} | "
            f"effective train unit defects="
            f"{100*np.mean(fit_info['training_unit_positive_rate_per_model']):.2f}%",
            flush=True,
        )

    if np.isnan(oof).any():
        raise RuntimeError(
            f"Some rows received no OOF prediction for {candidate_name}"
        )

    return oof, pd.DataFrame(fold_rows)


# ============================================================
# CALIBRATION
# ============================================================

def crossfit_calibration(y, raw_oof, groups, method: str):
    if method == "none":
        return np.asarray(raw_oof, dtype=float).copy()

    y = np.asarray(y, dtype=int)
    raw_oof = np.asarray(raw_oof, dtype=float)
    groups = np.asarray(groups)

    out = np.full(len(y), np.nan, dtype=float)

    splitter = GroupKFold(
        n_splits=min(N_SPLITS, len(np.unique(groups)))
    )

    for tr_idx, va_idx in splitter.split(
        raw_oof.reshape(-1, 1),
        y,
        groups,
    ):
        if method == "platt":
            calibrator = LogisticRegression(
                C=1e6,
                max_iter=1000,
                random_state=RANDOM_SEED,
            )
            calibrator.fit(
                raw_oof[tr_idx].reshape(-1, 1),
                y[tr_idx],
            )
            out[va_idx] = calibrator.predict_proba(
                raw_oof[va_idx].reshape(-1, 1)
            )[:, 1]

        elif method == "isotonic":
            calibrator = IsotonicRegression(
                out_of_bounds="clip"
            )
            calibrator.fit(
                raw_oof[tr_idx],
                y[tr_idx],
            )
            out[va_idx] = calibrator.transform(
                raw_oof[va_idx]
            )

        else:
            raise ValueError(method)

    if np.isnan(out).any():
        raise RuntimeError(
            f"Cross-fitted calibration failed for {method}"
        )

    return np.clip(out, 1e-8, 1 - 1e-8)


def fit_final_calibrator(y, raw_oof, method: str):
    if method == "none":
        return None

    if method == "platt":
        calibrator = LogisticRegression(
            C=1e6,
            max_iter=1000,
            random_state=RANDOM_SEED,
        )
        calibrator.fit(
            np.asarray(raw_oof).reshape(-1, 1),
            y,
        )
        return calibrator

    if method == "isotonic":
        calibrator = IsotonicRegression(
            out_of_bounds="clip"
        )
        calibrator.fit(
            raw_oof,
            y,
        )
        return calibrator

    raise ValueError(method)


def apply_calibrator(calibrator, raw_pred, method: str):
    raw_pred = np.asarray(raw_pred, dtype=float)

    if method == "none":
        return raw_pred

    if method == "platt":
        return calibrator.predict_proba(
            raw_pred.reshape(-1, 1)
        )[:, 1]

    if method == "isotonic":
        return calibrator.transform(raw_pred)

    raise ValueError(method)


# ============================================================
# ROW THRESHOLDS
# ============================================================

def choose_row_thresholds(y, score):
    precision, recall, thresholds = precision_recall_curve(
        y,
        score,
    )

    out = {}

    for beta, name in [
        (1.0, "max_f1"),
        (2.0, "max_f2"),
    ]:
        f = (
            (1 + beta**2)
            * precision
            * recall
            / (
                beta**2 * precision
                + recall
                + 1e-15
            )
        )

        valid_f = f[:-1]
        idx = int(np.nanargmax(valid_f))
        th = float(thresholds[idx])

        pred = (score >= th).astype(int)

        out[name] = {
            "threshold": th,
            "precision": float(
                precision_score(
                    y,
                    pred,
                    zero_division=0,
                )
            ),
            "recall": float(
                recall_score(
                    y,
                    pred,
                    zero_division=0,
                )
            ),
            "f1": float(
                f1_score(
                    y,
                    pred,
                    zero_division=0,
                )
            ),
            "f2": float(
                fbeta_score(
                    y,
                    pred,
                    beta=2,
                    zero_division=0,
                )
            ),
        }

    return out


def row_metrics_at_threshold(y, score, threshold):
    pred = (
        np.asarray(score, dtype=float) >= threshold
    ).astype(int)

    return {
        "threshold": float(threshold),
        "precision": float(
            precision_score(
                y,
                pred,
                zero_division=0,
            )
        ),
        "recall": float(
            recall_score(
                y,
                pred,
                zero_division=0,
            )
        ),
        "f1": float(
            f1_score(
                y,
                pred,
                zero_division=0,
            )
        ),
        "f2": float(
            fbeta_score(
                y,
                pred,
                beta=2,
                zero_division=0,
            )
        ),
    }


# ============================================================
# POST-ML ALERT POLICIES
# ============================================================

def add_post_ml_scores(df: pd.DataFrame, score_col="score"):
    x = df.sort_values(
        [
            "run_id",
            "unit_id",
            "prediction_station_index",
            "prediction_time",
            "prediction_event_sequence",
        ],
        kind="stable",
    ).copy()

    group = x.groupby(
        ["run_id", "unit_id"],
        sort=False,
    )[score_col]

    for alpha in [0.3, 0.5, 0.7]:
        x[f"ema_{alpha}"] = group.transform(
            lambda s: s.ewm(
                alpha=alpha,
                adjust=False,
            ).mean()
        )

    x["_prev_score"] = group.shift(1)

    # Two consecutive rows both need to exceed a threshold.
    # Therefore min(current, previous) >= threshold.
    x["two_consecutive"] = np.minimum(
        x[score_col],
        x["_prev_score"],
    )

    def second_highest_last_three(s: pd.Series):
        a = s.to_numpy(dtype=float)
        out = np.full(len(a), np.nan, dtype=float)

        for i in range(len(a)):
            w = a[max(0, i - 2): i + 1]
            w = w[np.isfinite(w)]

            if len(w) >= 2:
                out[i] = np.partition(w, -2)[-2]

        return pd.Series(
            out,
            index=s.index,
        )

    x["two_of_three"] = (
        x.groupby(
            ["run_id", "unit_id"],
            sort=False,
        )[score_col]
        .transform(second_highest_last_three)
    )

    return x


def choose_unit_threshold(
    df: pd.DataFrame,
    score_col: str,
    fwr_cap=FWR_CAP,
):
    # Only pre-final-inspection alerts count.
    pre = df[
        df["prediction_station_index"]
        < df["final_station_index"]
    ].copy()

    unit = (
        pre.groupby(
            ["run_id", "unit_id"],
            sort=False,
        )
        .agg(
            y=(TARGET_COLUMN, "max"),
            max_score=(score_col, "max"),
        )
        .dropna()
    )

    y = unit["y"].astype(int).to_numpy()
    s = unit["max_score"].to_numpy(dtype=float)

    finite = np.isfinite(s)
    y = y[finite]
    s = s[finite]

    if len(s) == 0:
        return None

    # Dense threshold grid selected only on train OOF.
    thresholds = np.unique(
        np.quantile(
            s,
            np.linspace(0.0, 1.0, 2001),
        )
    )

    best = None

    for th in thresholds:
        hit = s >= th

        neg = y == 0
        pos = y == 1

        if not neg.any() or not pos.any():
            continue

        fwr = float(hit[neg].mean())

        if fwr > fwr_cap:
            continue

        recall = float(hit[pos].mean())

        precision = (
            float(y[hit].mean())
            if hit.any()
            else 0.0
        )

        rank = (
            recall,
            precision,
            -fwr,
        )

        if best is None or rank > best["_rank"]:
            best = {
                "threshold": float(th),
                "unit_recall": recall,
                "false_warning_rate": fwr,
                "unit_precision": precision,
                "_rank": rank,
            }

    if best is None:
        return None

    th = best["threshold"]

    alerted_rows = pre[
        np.isfinite(pre[score_col])
        & (pre[score_col] >= th)
    ]

    first = (
        alerted_rows.groupby(
            ["run_id", "unit_id"]
        )["prediction_station_index"]
        .min()
    )

    positive_units = set(
        unit[unit["y"].eq(1)].index
    )

    first_positive = [
        value
        for key, value in first.items()
        if key in positive_units
    ]

    best["median_first_alert_station_index"] = (
        float(np.median(first_positive))
        if first_positive
        else None
    )

    best["detected_before_final_inspection"] = (
        best["unit_recall"]
    )

    del best["_rank"]
    return best


def evaluate_unit_policy(
    df: pd.DataFrame,
    score_col: str,
    threshold: float,
):
    pre = df[
        df["prediction_station_index"]
        < df["final_station_index"]
    ].copy()

    unit = (
        pre.groupby(
            ["run_id", "unit_id"],
            sort=False,
        )
        .agg(
            y=(TARGET_COLUMN, "max"),
            max_score=(score_col, "max"),
        )
        .dropna()
    )

    y = unit["y"].astype(int)
    hit = unit["max_score"] >= threshold

    neg = y.eq(0)
    pos = y.eq(1)

    alerted_rows = pre[
        np.isfinite(pre[score_col])
        & (pre[score_col] >= threshold)
    ]

    first = (
        alerted_rows.groupby(
            ["run_id", "unit_id"]
        )["prediction_station_index"]
        .min()
    )

    positive_units = set(
        unit[pos].index
    )

    first_positive = [
        value
        for key, value in first.items()
        if key in positive_units
    ]

    return {
        "unit_recall": (
            float(hit[pos].mean())
            if pos.any()
            else None
        ),
        "false_warning_rate": (
            float(hit[neg].mean())
            if neg.any()
            else None
        ),
        "unit_precision": (
            float(y[hit].mean())
            if hit.any()
            else 0.0
        ),
        "median_first_alert_station_index": (
            float(np.median(first_positive))
            if first_positive
            else None
        ),
        "detected_before_final_inspection": (
            float(hit[pos].mean())
            if pos.any()
            else None
        ),
    }


def best_alert_policy(df: pd.DataFrame):
    policy_columns = [
        "score",
        "ema_0.3",
        "ema_0.5",
        "ema_0.7",
        "two_consecutive",
        "two_of_three",
    ]

    policy_configs = {}

    for col in policy_columns:
        cfg = choose_unit_threshold(
            df,
            col,
            FWR_CAP,
        )

        if cfg is not None:
            policy_configs[col] = cfg

    if not policy_configs:
        raise RuntimeError(
            "No alert policy satisfied the false-warning constraint"
        )

    winner = max(
        policy_configs,
        key=lambda p: (
            policy_configs[p]["unit_recall"],
            policy_configs[p]["unit_precision"],
            -policy_configs[p]["false_warning_rate"],
            -(
                policy_configs[p][
                    "median_first_alert_station_index"
                ]
                or 999
            ),
        ),
    )

    return winner, policy_configs[winner], policy_configs


# ============================================================
# PER-RUN METRICS
# ============================================================

def per_run_probability_metrics(df: pd.DataFrame, score_col: str):
    rows = []

    for run_id, g in df.groupby(
        "run_id",
        sort=True,
    ):
        y = g[TARGET_COLUMN].astype(int).to_numpy()
        p = g[score_col].to_numpy(dtype=float)

        rows.append(
            {
                "run_id": run_id,
                "rows": int(len(g)),
                "positive_rate": float(y.mean()),
                **probability_metrics(y, p),
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# FINAL FULL-TRAIN FIT FOR SELECTED CANDIDATE
# ============================================================

def fit_final_candidate(train: pd.DataFrame, candidate_name: str):
    cfg = CANDIDATES[candidate_name]
    target_rate = cfg["target_unit_positive_rate"]

    if not cfg["bagging"]:
        sampled = resample_training_units(
            train,
            target_rate=target_rate,
            seed=RANDOM_SEED,
        )

        model = fit_single_catboost(
            sampled,
            seed=RANDOM_SEED,
        )

        return [model], {
            "rows_per_model": [int(len(sampled))],
            "units_per_model": [
                int(unit_labels(sampled).shape[0])
            ],
            "unit_positive_rate_per_model": [
                unit_prevalence(sampled)
            ],
        }

    models = []
    rows = []
    units = []
    rates = []

    for seed in BAGGING_SEEDS:
        sampled = resample_training_units(
            train,
            target_rate=target_rate,
            seed=seed,
        )

        model = fit_single_catboost(
            sampled,
            seed=seed,
        )

        models.append(model)
        rows.append(int(len(sampled)))
        units.append(int(unit_labels(sampled).shape[0]))
        rates.append(unit_prevalence(sampled))

    return models, {
        "rows_per_model": rows,
        "units_per_model": units,
        "unit_positive_rate_per_model": rates,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    train_path = FEATURE_DIR / "train.pkl"
    validation_path = FEATURE_DIR / "validation.pkl"

    if not train_path.exists() or not validation_path.exists():
        raise FileNotFoundError(
            "Missing generated_features/train.pkl or validation.pkl. "
            "Use the existing V2 generated feature files."
        )

    # NO TEST FILE IS LOADED HERE.
    train = pd.read_pickle(train_path)
    validation = pd.read_pickle(validation_path)

    train = train[
        train[TARGET_COLUMN].notna()
    ].reset_index(drop=True)

    validation = validation[
        validation[TARGET_COLUMN].notna()
    ].reset_index(drop=True)

    assert len(DEFECT_FEATURES) == 30
    assert TARGET_COLUMN not in DEFECT_FEATURES
    assert set(train["run_id"]).isdisjoint(
        set(validation["run_id"])
    )

    required_meta = [
        "run_id",
        "unit_id",
        "prediction_station_index",
        "prediction_time",
        "prediction_event_sequence",
        "final_station_index",
        TARGET_COLUMN,
    ]

    missing_train = [
        c
        for c in required_meta + DEFECT_FEATURES
        if c not in train.columns
    ]

    missing_val = [
        c
        for c in required_meta + DEFECT_FEATURES
        if c not in validation.columns
    ]

    if missing_train:
        raise ValueError(
            f"train.pkl missing columns: {missing_train}"
        )

    if missing_val:
        raise ValueError(
            f"validation.pkl missing columns: {missing_val}"
        )

    print("=" * 90)
    print("DEFECT MODEL V3")
    print("=" * 90)
    print("30 FEATURES ONLY")
    print("CATBOOST ONLY")
    print("NO CLASS WEIGHTING")
    print("TEST DATA IS NOT ACCESSED")
    print()

    print(f"Train rows: {len(train):,}")
    print(f"Train runs: {train.run_id.nunique()}")
    print(
        f"Train row positive rate: "
        f"{100*train[TARGET_COLUMN].mean():.3f}%"
    )
    print(
        f"Train UNIT positive rate: "
        f"{100*unit_prevalence(train):.3f}%"
    )

    print(f"Validation rows: {len(validation):,}")
    print(f"Validation runs: {validation.run_id.nunique()}")
    print(
        f"Validation row positive rate: "
        f"{100*validation[TARGET_COLUMN].mean():.3f}%"
    )
    print(
        f"Validation UNIT positive rate: "
        f"{100*unit_prevalence(validation):.3f}%"
    )
    print()

    y = train[TARGET_COLUMN].astype(int).to_numpy()
    groups = train["run_id"].astype(str).to_numpy()

    # ========================================================
    # 1. COMPARE TRAINING-DISTRIBUTION STRATEGIES
    # ========================================================

    candidate_results = {}
    all_fold_metrics = []
    comparison_rows = []

    for candidate_name in CANDIDATES:
        print()
        print("=" * 90)
        print(f"RUNNING CANDIDATE: {candidate_name}")
        print("=" * 90)

        raw_oof, folds = grouped_oof_candidate(
            train,
            candidate_name,
        )

        all_fold_metrics.append(folds)

        raw_metrics = probability_metrics(
            y,
            raw_oof,
        )

        oof_df = train.copy()
        oof_df["score"] = raw_oof
        oof_df = add_post_ml_scores(
            oof_df,
            "score",
        )

        selected_policy, selected_policy_cfg, all_policies = (
            best_alert_policy(oof_df)
        )

        mean_fold_pr = float(
            folds["pr_auc"].mean()
        )
        std_fold_pr = float(
            folds["pr_auc"].std(ddof=0)
        )
        min_fold_pr = float(
            folds["pr_auc"].min()
        )

        candidate_results[candidate_name] = {
            "raw_oof": raw_oof,
            "folds": folds,
            "raw_probability_metrics": raw_metrics,
            "mean_fold_pr_auc": mean_fold_pr,
            "std_fold_pr_auc": std_fold_pr,
            "min_fold_pr_auc": min_fold_pr,
            "selected_raw_alert_policy": selected_policy,
            "selected_raw_alert_policy_config": selected_policy_cfg,
            "raw_alert_policies": all_policies,
        }

        comparison_rows.append(
            {
                "candidate": candidate_name,
                "target_training_unit_positive_rate": (
                    CANDIDATES[candidate_name][
                        "target_unit_positive_rate"
                    ]
                ),
                "bagging_models": (
                    len(BAGGING_SEEDS)
                    if CANDIDATES[candidate_name]["bagging"]
                    else 1
                ),
                "mean_fold_pr_auc": mean_fold_pr,
                "std_fold_pr_auc": std_fold_pr,
                "minimum_fold_pr_auc": min_fold_pr,
                "pooled_oof_pr_auc": raw_metrics["pr_auc"],
                "pooled_oof_roc_auc": raw_metrics["roc_auc"],
                "pooled_oof_brier": raw_metrics["brier"],
                "selected_raw_alert_policy": selected_policy,
                "raw_alert_threshold": selected_policy_cfg[
                    "threshold"
                ],
                "oof_unit_recall": selected_policy_cfg[
                    "unit_recall"
                ],
                "oof_false_warning_rate": selected_policy_cfg[
                    "false_warning_rate"
                ],
                "oof_unit_precision": selected_policy_cfg[
                    "unit_precision"
                ],
                "oof_median_first_alert_station_index": (
                    selected_policy_cfg[
                        "median_first_alert_station_index"
                    ]
                ),
            }
        )

        print(
            f"{candidate_name}: "
            f"mean fold PR-AUC={mean_fold_pr:.5f} | "
            f"min fold={min_fold_pr:.5f} | "
            f"pooled={raw_metrics['pr_auc']:.5f} | "
            f"unit recall={selected_policy_cfg['unit_recall']:.4f} | "
            f"FWR={selected_policy_cfg['false_warning_rate']:.4f} | "
            f"unit precision={selected_policy_cfg['unit_precision']:.4f}"
        )

    cv_df = pd.concat(
        all_fold_metrics,
        ignore_index=True,
    )

    cv_df.to_csv(
        RESULTS_DIR / "v3_cv_fold_metrics.csv",
        index=False,
    )

    comparison_df = pd.DataFrame(comparison_rows)

    comparison_df.to_csv(
        RESULTS_DIR / "v3_sampling_comparison.csv",
        index=False,
    )

    # Primary deployment objective:
    # all candidate thresholds already satisfy FWR <= 5%.
    #
    # 1. highest unit recall
    # 2. highest pooled OOF PR-AUC
    # 3. highest minimum-fold PR-AUC
    # 4. highest unit precision
    # 5. lower FWR
    selected_candidate = max(
        candidate_results,
        key=lambda c: (
            candidate_results[c][
                "selected_raw_alert_policy_config"
            ]["unit_recall"],
            candidate_results[c][
                "raw_probability_metrics"
            ]["pr_auc"],
            candidate_results[c]["min_fold_pr_auc"],
            candidate_results[c][
                "selected_raw_alert_policy_config"
            ]["unit_precision"],
            -candidate_results[c][
                "selected_raw_alert_policy_config"
            ]["false_warning_rate"],
        ),
    )

    raw_oof = candidate_results[
        selected_candidate
    ]["raw_oof"]

    print()
    print("=" * 90)
    print(f"SELECTED TRAINING STRATEGY: {selected_candidate}")
    print("=" * 90)

    # ========================================================
    # 2. CALIBRATION CHECK ON WINNING CANDIDATE ONLY
    # ========================================================

    calibration_scores = {}
    calibrated_oof = {}
    cal_rows = []

    for method in [
        "none",
        "platt",
        "isotonic",
    ]:
        p = crossfit_calibration(
            y,
            raw_oof,
            groups,
            method,
        )

        calibrated_oof[method] = p

        metrics = probability_metrics(
            y,
            p,
        )

        calibration_scores[method] = metrics

        cal_rows.append(
            {
                "method": method,
                **metrics,
            }
        )

    cal_df = pd.DataFrame(cal_rows)

    cal_df.to_csv(
        RESULTS_DIR / "v3_calibration_comparison.csv",
        index=False,
    )

    # Same rule as V2:
    # Brier first, then ECE, then log loss.
    selected_calibration = min(
        calibration_scores,
        key=lambda method: (
            calibration_scores[method]["brier"],
            calibration_scores[method]["ece15"],
            calibration_scores[method]["log_loss"],
        ),
    )

    train_score = calibrated_oof[
        selected_calibration
    ]

    final_calibrator = fit_final_calibrator(
        y,
        raw_oof,
        selected_calibration,
    )

    print(
        f"Selected calibration: {selected_calibration}"
    )

    # ========================================================
    # 3. ROW THRESHOLDS ON FINAL CROSS-FITTED OOF SCORE
    # ========================================================

    row_thresholds = choose_row_thresholds(
        y,
        train_score,
    )

    pd.DataFrame(
        [
            {
                "objective": name,
                **cfg,
            }
            for name, cfg in row_thresholds.items()
        ]
    ).to_csv(
        RESULTS_DIR / "v3_threshold_comparison.csv",
        index=False,
    )

    # ========================================================
    # 4. FINAL ALERT POLICY ON CALIBRATED OOF SCORE
    # ========================================================

    final_oof_df = train.copy()
    final_oof_df["raw_oof_probability"] = raw_oof
    final_oof_df["score"] = train_score

    final_oof_df = add_post_ml_scores(
        final_oof_df,
        "score",
    )

    (
        selected_policy,
        selected_policy_cfg,
        final_policy_configs,
    ) = best_alert_policy(final_oof_df)

    pd.DataFrame(
        [
            {
                "policy": policy,
                **cfg,
            }
            for policy, cfg in final_policy_configs.items()
        ]
    ).to_csv(
        RESULTS_DIR / "v3_alert_policy_comparison.csv",
        index=False,
    )

    per_run_oof = per_run_probability_metrics(
        final_oof_df,
        "score",
    )

    per_run_oof.to_csv(
        RESULTS_DIR / "v3_per_run_oof_metrics.csv",
        index=False,
    )

    print(
        f"Selected final alert policy: {selected_policy} | "
        f"threshold={selected_policy_cfg['threshold']:.6f} | "
        f"OOF unit recall={selected_policy_cfg['unit_recall']:.4f} | "
        f"OOF FWR={selected_policy_cfg['false_warning_rate']:.4f}"
    )

    # ========================================================
    # 5. FIT WINNING CANDIDATE ON COMPLETE TRAIN SPLIT
    # ========================================================

    final_models, final_fit_info = fit_final_candidate(
        train,
        selected_candidate,
    )

    joblib.dump(
        final_models,
        MODEL_DIR / "defect_v3_models.joblib",
    )

    joblib.dump(
        final_calibrator,
        MODEL_DIR / "defect_v3_calibrator.joblib",
    )

    # ========================================================
    # 6. FROZEN VALIDATION
    # ========================================================

    y_val = validation[
        TARGET_COLUMN
    ].astype(int).to_numpy()

    val_raw = predict_models(
        final_models,
        validation,
    )

    val_score = apply_calibrator(
        final_calibrator,
        val_raw,
        selected_calibration,
    )

    val_df = validation.copy()
    val_df["raw_probability"] = val_raw
    val_df["score"] = val_score

    val_df = add_post_ml_scores(
        val_df,
        "score",
    )

    val_probability = probability_metrics(
        y_val,
        val_score,
    )

    val_f1 = row_metrics_at_threshold(
        y_val,
        val_score,
        row_thresholds["max_f1"]["threshold"],
    )

    val_f2 = row_metrics_at_threshold(
        y_val,
        val_score,
        row_thresholds["max_f2"]["threshold"],
    )

    val_unit = evaluate_unit_policy(
        val_df,
        selected_policy,
        selected_policy_cfg["threshold"],
    )

    val_per_run = per_run_probability_metrics(
        val_df,
        "score",
    )

    val_per_run.to_csv(
        RESULTS_DIR / "v3_validation_per_run.csv",
        index=False,
    )

    # ========================================================
    # 7. SAVE CONFIG / REPORTS
    # ========================================================

    config = {
        "version": "v3",
        "feature_count": 30,
        "features": DEFECT_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "catboost_params": CATBOOST_PARAMS,
        "class_weighting": "none",
        "candidate_training_strategies": CANDIDATES,
        "bagging_seeds": BAGGING_SEEDS,
        "selected_training_strategy": selected_candidate,
        "selected_calibration": selected_calibration,
        "row_thresholds": row_thresholds,
        "selected_alert_policy": selected_policy,
        "selected_alert_threshold": selected_policy_cfg[
            "threshold"
        ],
        "false_warning_cap": FWR_CAP,
        "random_seed": RANDOM_SEED,
        "group_kfold_splits": N_SPLITS,
        "test_data_used": False,
    }

    (
        MODEL_DIR / "defect_v3_config.json"
    ).write_text(
        json.dumps(
            config,
            indent=2,
        )
    )

    training_report = {
        "version": "v3",
        "feature_count": 30,
        "train_rows": int(len(train)),
        "train_runs": int(
            train["run_id"].nunique()
        ),
        "natural_train_row_positive_rate": float(
            train[TARGET_COLUMN].mean()
        ),
        "natural_train_unit_positive_rate": (
            unit_prevalence(train)
        ),
        "candidate_results": {
            name: {
                "mean_fold_pr_auc": result[
                    "mean_fold_pr_auc"
                ],
                "std_fold_pr_auc": result[
                    "std_fold_pr_auc"
                ],
                "min_fold_pr_auc": result[
                    "min_fold_pr_auc"
                ],
                "raw_probability_metrics": result[
                    "raw_probability_metrics"
                ],
                "selected_raw_alert_policy": result[
                    "selected_raw_alert_policy"
                ],
                "selected_raw_alert_policy_config": result[
                    "selected_raw_alert_policy_config"
                ],
            }
            for name, result in candidate_results.items()
        },
        "selected_training_strategy": selected_candidate,
        "calibration_candidates": calibration_scores,
        "selected_calibration": selected_calibration,
        "row_thresholds": row_thresholds,
        "final_oof_alert_policies": final_policy_configs,
        "selected_alert_policy": selected_policy,
        "selected_alert_policy_config": selected_policy_cfg,
        "final_fit_info": final_fit_info,
    }

    (
        RESULTS_DIR / "v3_training_report.json"
    ).write_text(
        json.dumps(
            training_report,
            indent=2,
        )
    )

    validation_report = {
        "version": "v3",
        "feature_count": 30,
        "selected_training_strategy": selected_candidate,
        "selected_calibration": selected_calibration,
        "selected_alert_policy": selected_policy,
        "selected_alert_threshold": selected_policy_cfg[
            "threshold"
        ],
        "validation_rows": int(len(validation)),
        "validation_runs": int(
            validation["run_id"].nunique()
        ),
        "validation_row_positive_rate": float(
            validation[TARGET_COLUMN].mean()
        ),
        "validation_unit_positive_rate": (
            unit_prevalence(validation)
        ),
        "probability_metrics": val_probability,
        "row_metrics_at_frozen_f1_threshold": val_f1,
        "row_metrics_at_frozen_f2_threshold": val_f2,
        "unit_metrics_at_frozen_alert_policy": val_unit,
    }

    (
        RESULTS_DIR / "v3_validation_report.json"
    ).write_text(
        json.dumps(
            validation_report,
            indent=2,
        )
    )

    summary = {
        "feature_count": 30,
        "selected_training_strategy": selected_candidate,
        "selected_calibration": selected_calibration,
        "mean_cv_pr_auc": candidate_results[
            selected_candidate
        ]["mean_fold_pr_auc"],
        "std_cv_pr_auc": candidate_results[
            selected_candidate
        ]["std_fold_pr_auc"],
        "minimum_fold_pr_auc": candidate_results[
            selected_candidate
        ]["min_fold_pr_auc"],
        "pooled_oof_pr_auc_raw": candidate_results[
            selected_candidate
        ]["raw_probability_metrics"]["pr_auc"],
        "oof_brier_after_selected_calibration": (
            calibration_scores[
                selected_calibration
            ]["brier"]
        ),
        "selected_alert_policy": selected_policy,
        "selected_alert_threshold": selected_policy_cfg[
            "threshold"
        ],
        "validation_pr_auc": val_probability["pr_auc"],
        "validation_roc_auc": val_probability["roc_auc"],
        "validation_brier": val_probability["brier"],
        "validation_precision_at_f1_threshold": val_f1[
            "precision"
        ],
        "validation_recall_at_f1_threshold": val_f1[
            "recall"
        ],
        "validation_f1": val_f1["f1"],
        "validation_f2_at_f2_threshold": val_f2["f2"],
        "validation_unit_recall": val_unit["unit_recall"],
        "validation_false_warning_rate": val_unit[
            "false_warning_rate"
        ],
        "validation_unit_precision": val_unit[
            "unit_precision"
        ],
        "validation_median_first_alert_station_index": (
            val_unit["median_first_alert_station_index"]
        ),
    }

    pd.DataFrame(
        [summary]
    ).to_csv(
        RESULTS_DIR / "v3_model_summary.csv",
        index=False,
    )

    # ========================================================
    # 8. TERMINAL SUMMARY
    # ========================================================

    print()
    print("=" * 90)
    print("V3 SAMPLING COMPARISON")
    print("=" * 90)

    display_cols = [
        "candidate",
        "mean_fold_pr_auc",
        "minimum_fold_pr_auc",
        "pooled_oof_pr_auc",
        "oof_unit_recall",
        "oof_false_warning_rate",
        "oof_unit_precision",
    ]

    print(
        comparison_df[
            display_cols
        ].to_string(index=False)
    )

    print()
    print("=" * 90)
    print("V3 FROZEN VALIDATION SUMMARY")
    print("=" * 90)
    print("30 FEATURES ONLY")
    print(
        f"Selected training strategy: {selected_candidate}"
    )
    print(
        f"Selected calibration: {selected_calibration}"
    )
    print(
        f"Selected alert policy: {selected_policy}"
    )
    print(
        f"Alert threshold: "
        f"{selected_policy_cfg['threshold']:.6f}"
    )
    print(
        f"CV PR-AUC: "
        f"{summary['mean_cv_pr_auc']:.5f} ± "
        f"{summary['std_cv_pr_auc']:.5f}"
    )
    print(
        f"Minimum fold PR-AUC: "
        f"{summary['minimum_fold_pr_auc']:.5f}"
    )
    print(
        f"Validation PR-AUC: "
        f"{val_probability['pr_auc']:.5f}"
    )
    print(
        f"Validation ROC-AUC: "
        f"{val_probability['roc_auc']:.5f}"
    )
    print(
        f"Validation Brier: "
        f"{val_probability['brier']:.5f}"
    )
    print(
        f"Frozen F1 threshold -> "
        f"Precision={val_f1['precision']:.4f} "
        f"Recall={val_f1['recall']:.4f} "
        f"F1={val_f1['f1']:.4f} "
        f"F2={val_f1['f2']:.4f}"
    )
    print(
        f"Frozen F2 threshold -> "
        f"Precision={val_f2['precision']:.4f} "
        f"Recall={val_f2['recall']:.4f} "
        f"F1={val_f2['f1']:.4f} "
        f"F2={val_f2['f2']:.4f}"
    )
    print(
        f"Unit recall="
        f"{val_unit['unit_recall']:.4f} | "
        f"FWR="
        f"{val_unit['false_warning_rate']:.4f} | "
        f"Unit precision="
        f"{val_unit['unit_precision']:.4f} | "
        f"Median first station index="
        f"{val_unit['median_first_alert_station_index']}"
    )

    print()
    print("V3 DEVELOPMENT COMPLETE.")
    print("OLD TEST SET WAS NOT ACCESSED BY THIS SCRIPT.")
    print(
        "DO NOT RE-EVALUATE V3 ON THE OLD CONSUMED TEST SET "
        "FOR FINAL MODEL CLAIMS."
    )
    print(
        "If V3 clearly beats V2 on OOF + validation, "
        "generate a NEW unseen final test set."
    )


if __name__ == "__main__":
    main()
