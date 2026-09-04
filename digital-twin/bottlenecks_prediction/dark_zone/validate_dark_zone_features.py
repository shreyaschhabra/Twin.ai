
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from dark_zone_feature_reconstructor import BOTTLENECK_25, FEATURES_28, UNCERTAINTY_3


def metric(a, b):
    x = pd.to_numeric(a, errors="coerce")
    y = pd.to_numeric(b, errors="coerce")
    m = x.notna() & y.notna()
    if m.sum() == 0:
        return 0, np.nan, np.nan, np.nan, np.nan
    e = x[m].to_numpy() - y[m].to_numpy()
    rho = np.nan
    if m.sum() >= 3 and x[m].nunique() > 1 and y[m].nunique() > 1:
        rho = float(spearmanr(x[m], y[m]).statistic)
    return (
        int(m.sum()),
        float(np.mean(np.abs(e))),
        float(np.sqrt(np.mean(e**2))),
        float(np.mean(e)),
        rho,
    )


def validate(pred_csv: str, oracle_csv: str, output_csv: str):
    pred = pd.read_csv(pred_csv)
    oracle = pd.read_csv(oracle_csv)

    required = ["run_id", "vehicle_id", "prediction_time"] + FEATURES_28
    missing = [c for c in required if c not in pred.columns]
    if missing:
        raise ValueError(f"Prediction CSV missing columns: {missing}")

    keys = ["run_id", "vehicle_id", "prediction_time"]
    merged = pred[keys + BOTTLENECK_25].merge(
        oracle[keys + BOTTLENECK_25],
        on=keys,
        how="inner",
        suffixes=("_pred", "_oracle"),
    )

    rows = []
    for f in BOTTLENECK_25:
        n, mae, rmse, bias, rho = metric(
            merged[f + "_pred"], merged[f + "_oracle"]
        )
        rows.append({
            "feature": f,
            "n": n,
            "mae": mae,
            "rmse": rmse,
            "bias": bias,
            "spearman": rho,
        })
    report = pd.DataFrame(rows)
    report.to_csv(output_csv, index=False)
    print(report.to_string(index=False))
    print(f"Matched rows: {len(merged)}")
    print(f"Wrote: {output_csv}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--oracle", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    validate(args.pred, args.oracle, args.output)
