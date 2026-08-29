"""
Flow dataset pipeline orchestration (Step 5). Builds the station-minute
grid, computes features, constructs labels, and returns the assembled
table — the single place that wires bottleneck_events -> labels and
features together against the same observable event table.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.features import build_features
from backend.flow.labels import label_rows

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


def build_flow_dataset(events: pd.DataFrame, config, sensor_models: Dict) -> Dict[str, pd.DataFrame]:
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)

    impacts = detect_bottleneck_events(events, config)
    labeled = label_rows(grid, impacts)
    full = build_features(labeled, events, config, sensor_models)

    return {"flow_station_minutes": full, "bottleneck_events": impacts}
