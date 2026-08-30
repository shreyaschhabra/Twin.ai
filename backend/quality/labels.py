"""
Attaches each vehicle's own EVENTUAL final-QC outcome (Section 14/17) as
the label -- never a feature. QC_RESULT_RECORDED only ever exists at S45,
strictly after every one of that vehicle's 5 pre-EOL snapshots in
simulation time, so this merge cannot leak into the feature columns it's
joined against (verified structurally: labels.py never touches
events_df before S45, and features.py -- called separately, upstream --
never reads QC_RESULT_RECORDED at all).
"""

from __future__ import annotations

import pandas as pd


def attach_final_qc_labels(featured_snapshots: pd.DataFrame, events_df: pd.DataFrame) -> pd.DataFrame:
    qc = events_df[events_df.event_type == "QC_RESULT_RECORDED"][["vehicle_id", "qc_result"]]
    merged = featured_snapshots.merge(qc, on="vehicle_id", how="left")
    merged["target"] = (merged.qc_result == "DEFECT").astype(int)
    return merged
