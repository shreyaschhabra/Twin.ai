from __future__ import annotations

import numpy as np
import pandas as pd

from light_zone.light_zone_runtime import (
    BOTTLENECK_FEATURES,
    LightZoneRuntimeFeatureBuilder,
)
from training.build_causal_datasets import bottleneck_rows


def _stations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "station_id": "S02",
                "archetype": "AUTOMATED",
                "base_cycle_time_ms": 34_000,
                "cycle_time_std_ms": 3_400,
                "buffer_capacity": 12,
                "sensor_coverage": "NORMAL",
            }
        ]
    )


def _events() -> pd.DataFrame:
    # The timestamps deliberately cross both the recent 10-minute and previous
    # 10-minute boundaries so this catches accidental window changes.
    rows = [
        (0, "UNIT_ARRIVED", 1, np.nan),
        (100_000, "PROCESSING_STARTED", 1, np.nan),
        (240_000, "PROCESSING_COMPLETED", 0, 33_000),
        (420_000, "UNIT_ARRIVED", 2, np.nan),
        (610_000, "PROCESSING_STARTED", 2, np.nan),
        (780_000, "PROCESSING_COMPLETED", 1, 35_000),
        (1_010_000, "UNIT_ARRIVED", 3, np.nan),
        (1_220_000, "PROCESSING_STARTED", 3, np.nan),
        (1_390_000, "PROCESSING_COMPLETED", 2, 34_500),
    ]
    frame = pd.DataFrame(
        rows,
        columns=["timestamp_ms", "event_type", "queue_length_after", "cycle_time_ms"],
    )
    frame["station_id"] = "S02"
    frame["unit_id"] = [f"U{i // 3 + 1}" for i in range(len(frame))]
    frame["event_id"] = [f"EV{i:03d}" for i in range(len(frame))]
    frame["previous_state"] = None
    frame["new_state"] = None
    frame["event_sequence"] = np.arange(len(frame), dtype=int)
    frame["station_index"] = 1
    return frame


def test_runtime_light_matches_frozen_offline_builder_exactly() -> None:
    stations = _stations()
    events = _events()

    offline_stations = stations.copy()
    offline_stations["station_index"] = 1
    offline = bottleneck_rows("TEST", offline_stations, events.copy())

    runtime = LightZoneRuntimeFeatureBuilder(stations)
    runtime_rows = []
    for row in events.itertuples(index=False):
        X = runtime.process_event(row._asdict())
        runtime_rows.append(X.iloc[0].to_dict())
    runtime_frame = pd.DataFrame(runtime_rows, columns=BOTTLENECK_FEATURES)

    assert list(runtime_frame.columns) == BOTTLENECK_FEATURES
    assert len(BOTTLENECK_FEATURES) == 28

    for feature in BOTTLENECK_FEATURES:
        left = offline[feature]
        right = runtime_frame[feature]
        if feature in {"station_id", "station_archetype"}:
            assert left.astype(str).tolist() == right.astype(str).tolist()
        else:
            np.testing.assert_allclose(
                pd.to_numeric(left, errors="coerce").to_numpy(dtype=float),
                pd.to_numeric(right, errors="coerce").to_numpy(dtype=float),
                rtol=0.0,
                atol=0.0,
                equal_nan=True,
                err_msg=f"Feature mismatch: {feature}",
            )
