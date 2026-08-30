"""
Temporal deduplication (Sections 7/8): the station-minute grid (every 60s
per station, reused unchanged from backend.flow.pipeline) is the
CANDIDATE row source -- Option B ("reduced regular sampling"), chosen
over building a new event-driven sampler because it's simpler and reuses
the already-validated grid/feature code exactly, per "choose the simplest
architecture that substantially reduces temporal redundancy."

Deduplication itself never looks at the label: it rounds a small set of
already-computed point-in-time FEATURE columns to coarse buckets and
drops a row when every one of those buckets is identical to the
immediately preceding RETAINED row for the same (shift, station) --
collapsing long stable/healthy stretches while leaving fast-changing
precursor windows (which are, by definition, non-stationary) untouched.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

DEFAULT_DEDUP_FEATURES = {
    "inbound_occupancy_ratio": 0.1,
    "cycle_time_dev_relative": 0.05,
    "prop_blocked_5m": 0.1,
    "prop_starved_5m": 0.1,
    "prop_down_5m": 0.1,
}


def deduplicate_rows(featured: pd.DataFrame, tolerances: Dict[str, float] = None) -> pd.DataFrame:
    tolerances = tolerances or DEFAULT_DEDUP_FEATURES
    cols = [c for c in tolerances if c in featured.columns]
    df = featured.sort_values(["shift_id", "station_id", "window_end_time"]).copy()

    bucket_cols = []
    for c in cols:
        bucket_col = f"__bucket_{c}"
        tol = tolerances[c]
        df[bucket_col] = np.round(df[c].fillna(-999999) / tol).astype(int)
        bucket_cols.append(bucket_col)

    df["__signature"] = list(zip(*[df[c] for c in bucket_cols]))
    df["__changed"] = df.groupby(["shift_id", "station_id"])["__signature"].transform(
        lambda s: s.ne(s.shift(1))
    )
    kept = df[df["__changed"]].drop(columns=bucket_cols + ["__signature", "__changed"])
    return kept.reset_index(drop=True)


def deduplication_report(raw_count: int, final_count: int) -> Dict:
    reduction_pct = (1 - final_count / raw_count) * 100 if raw_count else 0.0
    return {"raw_candidate_rows": raw_count, "final_eligible_rows": final_count, "reduction_percentage": round(reduction_pct, 2)}
