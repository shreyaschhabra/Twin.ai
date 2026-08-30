"""
Flow station-minute grid construction (Step 5): one row per
(shift_id, station_id, window_end_time), shared by the Flow v2 and
Quality pipelines.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

WINDOW_SECONDS = 60.0


def build_station_minute_grid(events: pd.DataFrame, station_ids: List[str]) -> pd.DataFrame:
    """One row per (shift_id, station_id, window_end_time) from t=60s to
    the shift's last observed event, in 60s steps."""
    shift_max = events.groupby("shift_id").simulation_time.max()
    rows = []
    for shift_id, max_t in shift_max.items():
        n_windows = int(max_t // WINDOW_SECONDS)
        window_ends = np.arange(1, n_windows + 1) * WINDOW_SECONDS
        for station_id in station_ids:
            rows.append(pd.DataFrame({
                "shift_id": shift_id, "station_id": station_id, "window_end_time": window_ends,
            }))
    return pd.concat(rows, ignore_index=True)
