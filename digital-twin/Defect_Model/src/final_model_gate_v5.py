from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import zipfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_schema import DEFECT_FEATURES, TARGET_COLUMN
from train_catboost_v5 import (
    POLICY_COLUMNS,
    add_policy_scores,
    evaluate_unit_policy_all_units,
    predict_bundle,
)


def safe_json(value):
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(safe_json(payload), indent=2) + "\n")


def wilson_interval(k: int, n: int, z: float = 1.959963984540054):
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return center - half, center + half


def unit_alert_summary(scored: pd.DataFrame, policy_col: str, threshold: float):
    pre = scored[
        scored["prediction_station_index"] < scored["final_station_index"]
    ].copy()
    rows = []
    for (run_id, unit_id), g in pre.groupby(["run_id", "unit_id"], sort=False):
        y = int(g[TARGET_COLUMN].max())
        alerted = g[g[policy_col] >= threshold]
        rows.append(
            {
                "run_id": str(run_id),
                "unit_id": str(unit_id),
                "y": y,
                "alert": int(not alerted.empty),
                "first_alert_station": (
                    float(alerted["prediction_station_index"].min())
                    if not alerted.empty
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def run_block_bootstrap(
    val: pd.DataFrame,
    pred: np.ndarray,
    unit_summary: pd.DataFrame,
    iterations: int,
    seed: int,
):
    rng = np.random.default_rng(seed)
    runs = list(val["run_id"].astype(str).unique())
    run_values = val["run_id"].astype(str).to_numpy()
    y_all = val[TARGET_COLUMN].astype(int).to_numpy()

    row_idx = {r: np.flatnonzero(run_values == r) for r in runs}
    unit_blocks = {
        r: unit_summary[unit_summary["run_id"].eq(r)].copy() for r in runs
    }

    rows = []
    for _ in range(iterations):
        picked = rng.choice(runs, size=len(runs), replace=True)
        idx = np.concatenate([row_idx[r] for r in picked])
        y = y_all[idx]
        p = pred[idx]

        units = pd.concat([unit_blocks[r] for r in picked], ignore_index=True)
        uy = units["y"].to_numpy(dtype=int)
        ua = units["alert"].to_numpy(dtype=int)
        first = units["first_alert_station"].to_numpy(dtype=float)

        positive_alert_mask = (uy == 1) & (ua == 1)
        rows.append(
            {
                "pr_auc": average_precision_score(y, p),
                "roc_auc": roc_auc_score(y, p),
                "brier": brier_score_loss(y, p),
                "unit_recall": ua[uy == 1].mean(),
                "false_warning_rate": ua[uy == 0].mean(),
                "unit_precision": uy[ua == 1].mean(),
                "median_first_alert_station_index": (
                    float(np.nanmedian(first[positive_alert_mask]))
                    if positive_alert_mask.any()
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def ci_from_bootstrap(frame: pd.DataFrame, points: dict):
    out = {}
    for col in frame.columns:
        values = pd.to_numeric(frame[col], errors="coerce").dropna().to_numpy(float)
        out[col] = {
            "point_estimate": float(points[col]),
            "lower_95": float(np.quantile(values, 0.025)),
            "upper_95": float(np.quantile(values, 0.975)),
            "bootstrap_iterations": int(len(values)),
        }
    return out


def threshold_robustness(scored, policy_col: str, frozen_threshold: float):
    thresholds = sorted(
        set(
            [
                0.10,
                0.11,
                0.12,
                0.125,
                0.13,
                0.135,
                float(frozen_threshold),
                0.145,
                0.15,
                0.155,
                0.16,
                0.17,
                0.18,
            ]
        )
    )

    rows = []
    for threshold in thresholds:
        m = evaluate_unit_policy_all_units(scored, policy_col, threshold)
        rows.append(
            {
                "threshold": threshold,
                "is_frozen_threshold": bool(
                    abs(threshold - frozen_threshold) < 1e-12
                ),
                "unit_recall": m["unit_recall"],
                "false_warning_rate": m["false_warning_rate"],
                "unit_precision": m["unit_precision"],
                "median_first_alert_station_index": m[
                    "median_first_alert_station_index"
                ],
                "alerted_positive_units": m["alerted_positive_units"],
                "alerted_negative_units": m["alerted_negative_units"],
                "fwr_under_5pct": bool(m["false_warning_rate"] <= 0.05),
            }
        )
    return pd.DataFrame(rows)


def runtime_parity(
    validation: pd.DataFrame,
    model_bundle,
    model_path: Path,
    config_path: Path,
    calibrator_path: Path,
    validation_output_dir: Path,
):
    try:
        from defect_main import iter_replay_records
        from ml.defect_model_runtime import DefectModelRuntime
        from runtime.defect_feature_runtime import DefectRuntimeFeatureBuilder
    except Exception as exc:
        return {
            "status": "SKIP",
            "reason": (
                "Runtime files are not installed in the project root. "
                "Copy the corrected defect runtime bundle first."
            ),
            "import_error": repr(exc),
        }

    candidates = sorted(validation_output_dir.glob("*.zip"))
    if not candidates:
        return {
            "status": "SKIP",
            "reason": f"No raw validation output ZIPs found in {validation_output_dir}",
        }

    raw_zip = candidates[0]
    run_id = raw_zip.stem

    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        with zipfile.ZipFile(raw_zip, "r") as zf:
            zf.extractall(run_dir)

        builder = DefectRuntimeFeatureBuilder(
            run_dir / "stations.csv",
            run_dir / "units.csv",
            run_id=run_id,
        )

        runtime_rows = []
        for raw_record in iter_replay_records(run_dir):
            record = dict(raw_record)
            stream = record.pop("stream")

            if stream == "station_event":
                packet = builder.process_station_event(record)
                if packet is not None:
                    runtime_rows.append(
                        {
                            "run_id": packet.run_id,
                            "unit_id": packet.unit_id,
                            "prediction_station": packet.station_id,
                            "prediction_time": packet.prediction_time_ms,
                            "prediction_event_sequence": packet.event_sequence,
                            **packet.features_30,
                        }
                    )
            elif stream == "sensor_reading":
                builder.process_sensor_reading(record)
            elif stream == "manual_check":
                builder.process_manual_check(record)

        runtime_df = pd.DataFrame(runtime_rows)

    offline = validation[validation["run_id"].astype(str).eq(run_id)].copy()
    offline["offline_probability"] = predict_bundle(model_bundle, offline)

    runtime_model = DefectModelRuntime(model_path, config_path, calibrator_path)
    runtime_df["runtime_probability"] = runtime_model.predict_feature_rows(
        runtime_df[DEFECT_FEATURES]
    )["defect_probability"].to_numpy(float)

    keys = [
        "run_id",
        "unit_id",
        "prediction_station",
        "prediction_time",
        "prediction_event_sequence",
    ]

    merged = offline[
        keys + DEFECT_FEATURES + ["offline_probability"]
    ].merge(
        runtime_df[keys + DEFECT_FEATURES + ["runtime_probability"]],
        on=keys,
        how="outer",
        suffixes=("_offline", "_runtime"),
        indicator=True,
    )

    numeric_mismatches = 0
    categorical_mismatches = 0
    max_numeric_abs_diff = 0.0
    feature_mismatches = {}

    for feature in DEFECT_FEATURES:
        a = merged[f"{feature}_offline"]
        b = merged[f"{feature}_runtime"]

        if feature in {"supplier_batch", "vehicle_model"}:
            equal = (
                a.fillna("__NA__").astype(str).to_numpy()
                == b.fillna("__NA__").astype(str).to_numpy()
            )
            count = int((~equal).sum())
            categorical_mismatches += count
        else:
            av = pd.to_numeric(a, errors="coerce").to_numpy(float)
            bv = pd.to_numeric(b, errors="coerce").to_numpy(float)
            equal = np.isclose(
                av, bv, rtol=1e-12, atol=1e-12, equal_nan=True
            )
            count = int((~equal).sum())
            numeric_mismatches += count
            if count:
                diff = np.abs(av - bv)
                finite = diff[np.isfinite(diff)]
                if len(finite):
                    max_numeric_abs_diff = max(
                        max_numeric_abs_diff, float(finite.max())
                    )

        feature_mismatches[feature] = count

    op = merged["offline_probability"].to_numpy(float)
    rp = merged["runtime_probability"].to_numpy(float)
    p_equal = np.isclose(op, rp, rtol=1e-12, atol=1e-12, equal_nan=True)
    p_diff = np.abs(op - rp)
    finite_p = p_diff[np.isfinite(p_diff)]

    report = {
        "status": "PASS",
        "run_id": run_id,
        "offline_rows": int(len(offline)),
        "runtime_rows": int(len(runtime_df)),
        "matched_rows": int((merged["_merge"] == "both").sum()),
        "offline_only_rows": int((merged["_merge"] == "left_only").sum()),
        "runtime_only_rows": int((merged["_merge"] == "right_only").sum()),
        "numeric_feature_mismatches": int(numeric_mismatches),
        "categorical_feature_mismatches": int(categorical_mismatches),
        "feature_mismatches": feature_mismatches,
        "max_numeric_feature_absolute_difference": float(max_numeric_abs_diff),
        "probability_mismatches": int((~p_equal).sum()),
        "max_probability_absolute_difference": (
            float(finite_p.max()) if len(finite_p) else 0.0
        ),
        "builder_diagnostics": builder.diagnostics(),
    }

    if (
        report["offline_rows"] != report["runtime_rows"]
        or report["offline_only_rows"] != 0
        or report["runtime_only_rows"] != 0
        or report["numeric_feature_mismatches"] != 0
        or report["categorical_feature_mismatches"] != 0
        or report["probability_mismatches"] != 0
    ):
        report["status"] = "FAIL"

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validation",
        type=Path,
        default=ROOT / "generated_features_v5" / "validation.pkl",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "saved_models" / "defect_v5_models.joblib",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "saved_models" / "defect_v5_config.json",
    )
    parser.add_argument(
        "--calibrator",
        type=Path,
        default=ROOT / "saved_models" / "defect_v5_calibrator.joblib",
    )
    parser.add_argument(
        "--validation-output-dir",
        type=Path,
        default=(
            ROOT
            / "factory_defect_prediction_v2_pack"
            / "validation"
            / "outputs"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results" / "final_gate_v5",
    )
    parser.add_argument("--run-bootstrap-iterations", type=int, default=750)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # Keep TWO views:
    #   val_all     -> exact offline↔runtime parity, including censored rows
    #   val_labeled -> model metrics / confidence intervals only
    #
    # The previous gate script incorrectly passed only labelled rows into the
    # parity audit. The runtime correctly emits predictions for censored units
    # too, so those valid runtime rows appeared as "runtime_only".
    val_all = pd.read_pickle(args.validation).copy().reset_index(drop=True)
    val = val_all[val_all[TARGET_COLUMN].notna()].copy().reset_index(drop=True)

    artifact = joblib.load(args.model)
    config = json.loads(args.config.read_text())

    if artifact.get("version") != "v5" or config.get("version") != "v5":
        raise RuntimeError("Expected finalized V5 artifacts")

    bundle = artifact["bundle"]
    pred = predict_bundle(bundle, val)
    y = val[TARGET_COLUMN].astype(int).to_numpy()

    scored = val.copy()
    scored["score"] = pred
    scored = add_policy_scores(scored, "score")

    policy = str(config["selected_alert_policy"])
    threshold = float(config["selected_alert_threshold"])
    policy_col = POLICY_COLUMNS[policy]

    alert = evaluate_unit_policy_all_units(scored, policy_col, threshold)
    units = unit_alert_summary(scored, policy_col, threshold)

    point_metrics = {
        "pr_auc": float(average_precision_score(y, pred)),
        "roc_auc": float(roc_auc_score(y, pred)),
        "brier": float(brier_score_loss(y, pred)),
        "unit_recall": float(alert["unit_recall"]),
        "false_warning_rate": float(alert["false_warning_rate"]),
        "unit_precision": float(alert["unit_precision"]),
        "median_first_alert_station_index": float(
            alert["median_first_alert_station_index"]
        ),
    }

    run_boot = run_block_bootstrap(
        val,
        pred,
        units,
        args.run_bootstrap_iterations,
        args.seed,
    )
    run_boot.to_csv(args.output / "run_block_bootstrap_draws.csv", index=False)
    run_ci = ci_from_bootstrap(run_boot, point_metrics)

    # Unit-level exact/Wilson uncertainty for the main operational rates.
    positive_units = int(alert["positive_units"])
    negative_units = int(alert["negative_units"])
    tp = int(alert["alerted_positive_units"])
    fp = int(alert["alerted_negative_units"])
    total_alerts = tp + fp

    recall_lo, recall_hi = wilson_interval(tp, positive_units)
    fwr_lo, fwr_hi = wilson_interval(fp, negative_units)
    precision_lo, precision_hi = wilson_interval(tp, total_alerts)

    # Median first-warning bootstrap across detected positive units.
    detected_positive = units[
        units["y"].eq(1) & units["alert"].eq(1)
    ]["first_alert_station"].dropna().to_numpy(float)
    rng = np.random.default_rng(args.seed)
    medians = np.asarray(
        [
            np.median(
                rng.choice(
                    detected_positive,
                    size=len(detected_positive),
                    replace=True,
                )
            )
            for _ in range(10000)
        ],
        dtype=float,
    )

    confidence = {
        "point_metrics": point_metrics,
        "unit_level_95_intervals": {
            "unit_recall": {
                "numerator_detected_defects": tp,
                "denominator_defective_units": positive_units,
                "point_estimate": point_metrics["unit_recall"],
                "method": "Wilson binomial interval",
                "lower_95": recall_lo,
                "upper_95": recall_hi,
            },
            "false_warning_rate": {
                "numerator_false_warned_normal_units": fp,
                "denominator_normal_units": negative_units,
                "point_estimate": point_metrics["false_warning_rate"],
                "method": "Wilson binomial interval",
                "lower_95": fwr_lo,
                "upper_95": fwr_hi,
            },
            "unit_precision": {
                "numerator_true_alerts": tp,
                "denominator_all_alerted_units": total_alerts,
                "point_estimate": point_metrics["unit_precision"],
                "method": "Wilson binomial interval",
                "lower_95": precision_lo,
                "upper_95": precision_hi,
            },
            "median_first_alert_station_index": {
                "detected_positive_units": int(len(detected_positive)),
                "point_estimate": point_metrics[
                    "median_first_alert_station_index"
                ],
                "method": "10,000 unit bootstrap draws",
                "lower_95": float(np.quantile(medians, 0.025)),
                "upper_95": float(np.quantile(medians, 0.975)),
            },
        },
        "run_block_95_intervals": run_ci,
        "run_block_note": (
            "This is deliberately conservative scenario-level uncertainty. "
            "There are only five validation runs, so these intervals are wide."
        ),
    }
    write_json(args.output / "confidence_intervals.json", confidence)

    robustness = threshold_robustness(scored, policy_col, threshold)
    robustness.to_csv(args.output / "threshold_robustness.csv", index=False)

    parity = runtime_parity(
        val_all,
        bundle,
        args.model,
        args.config,
        args.calibrator,
        args.validation_output_dir,
    )
    write_json(args.output / "runtime_parity_report.json", parity)

    # Local threshold stability around the frozen setting, NOT retuning.
    local = robustness[
        robustness["threshold"].between(0.135, 0.155, inclusive="both")
    ]
    local_recall_span = (
        float(local["unit_recall"].max() - local["unit_recall"].min())
        if len(local)
        else np.nan
    )
    local_fwr_span = (
        float(
            local["false_warning_rate"].max()
            - local["false_warning_rate"].min()
        )
        if len(local)
        else np.nan
    )

    final_gate = {
        "version": "v5",
        "purpose": "final model audit only; no retraining or retuning",
        "selected_alert_policy": policy,
        "frozen_alert_threshold": threshold,
        "point_metrics": point_metrics,
        "confidence_intervals_file": "confidence_intervals.json",
        "threshold_robustness_file": "threshold_robustness.csv",
        "runtime_parity_file": "runtime_parity_report.json",
        "threshold_local_stability": {
            "window": [0.135, 0.155],
            "unit_recall_span": local_recall_span,
            "false_warning_rate_span": local_fwr_span,
            "interpretation": (
                "PASS"
                if local_recall_span <= 0.05 and local_fwr_span <= 0.02
                else "WARN"
            ),
        },
        "checks": {
            "runtime_parity": parity.get("status"),
            "frozen_threshold_below_5pct_fwr": (
                "PASS" if point_metrics["false_warning_rate"] <= 0.05 else "FAIL"
            ),
            "threshold_not_on_local_cliff": (
                "PASS"
                if local_recall_span <= 0.05 and local_fwr_span <= 0.02
                else "WARN"
            ),
        },
        "important_limitation": (
            "A brand-new untouched simulator test realization was not run. "
            "The original consumed test is not used in this audit."
        ),
    }
    write_json(args.output / "final_gate_summary.json", final_gate)

    print("=" * 92)
    print("FINAL V5 DEFECT MODEL GATE")
    print("=" * 92)
    print(f"PR-AUC: {point_metrics['pr_auc']:.6f}")
    print(f"ROC-AUC: {point_metrics['roc_auc']:.6f}")
    print(f"Brier: {point_metrics['brier']:.6f}")
    print(
        "Unit recall: "
        f"{100*point_metrics['unit_recall']:.2f}% "
        f"[Wilson 95% {100*recall_lo:.2f}%, {100*recall_hi:.2f}%]"
    )
    print(
        "FWR: "
        f"{100*point_metrics['false_warning_rate']:.2f}% "
        f"[Wilson 95% {100*fwr_lo:.2f}%, {100*fwr_hi:.2f}%]"
    )
    print(
        "Unit precision: "
        f"{100*point_metrics['unit_precision']:.2f}% "
        f"[Wilson 95% {100*precision_lo:.2f}%, {100*precision_hi:.2f}%]"
    )
    print(
        "Median first alert station: "
        f"{point_metrics['median_first_alert_station_index']:.1f} "
        f"[bootstrap 95% {np.quantile(medians, .025):.1f}, "
        f"{np.quantile(medians, .975):.1f}]"
    )
    print(f"Runtime parity: {parity.get('status')}")
    print(
        "Threshold local stability: "
        f"{final_gate['checks']['threshold_not_on_local_cliff']}"
    )
    print(f"Artifacts: {args.output}")


if __name__ == "__main__":
    main()
