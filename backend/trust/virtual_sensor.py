"""
Virtual sensor estimator (Section 32): a simple numerical fallback, not
deep-learning imputation. Three-level hierarchy, tried in order:

  1. same-station recent rolling median (last N available readings at
     this exact station+sensor)
  2. same-station-type mean (across all stations sharing this station's
     type, for the same sensor family, recent window)
  3. operational-state estimate (the sensor's own configured baseline --
     "assume healthy" as the last-resort, least-confident estimate)

Never claims an inferred value is measured -- callers must carry the
returned `method` alongside the value and route it through
backend.trust.data_state as INFERRED, not LIVE.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

METHOD_SAME_STATION = "same_station_recent"
METHOD_SAME_TYPE = "same_station_type"
METHOD_OPERATIONAL_BASELINE = "operational_baseline"


def estimate_virtual_sensor_value(
    station_id: str,
    sensor_name: str,
    station_type: str,
    recent_readings_by_station: Dict[Tuple[str, str], list],
    recent_readings_by_type: Dict[Tuple[str, str], list],
    sensor_models: Dict,
) -> Tuple[Optional[float], str, bool]:
    """Returns (estimated_value, method, reliable). `reliable=False` means
    the caller should treat this as insufficient for INFERRED (fall
    through to UNKNOWN) -- e.g. an empty same-station-type pool with no
    baseline at all."""
    same_station = recent_readings_by_station.get((station_id, sensor_name), [])
    if len(same_station) >= 3:
        return float(np.median(same_station)), METHOD_SAME_STATION, True

    same_type = recent_readings_by_type.get((station_type, sensor_name), [])
    if len(same_type) >= 5:
        return float(np.mean(same_type)), METHOD_SAME_TYPE, True

    sm = sensor_models.get((station_id, sensor_name))
    if sm is not None:
        return float(sm.baseline), METHOD_OPERATIONAL_BASELINE, True

    return None, METHOD_OPERATIONAL_BASELINE, False


def evaluate_virtual_sensor(
    readings_df: pd.DataFrame, sensor_models: Dict, mask_fraction: float = 0.2, seed: int = 20240002,
) -> dict:
    """Artificially masks a random subset of known-available sensor
    readings and scores the virtual-sensor estimate against the true
    (masked-out) value. readings_df must have columns: station_id,
    sensor_name, station_type, value, simulation_time, measurement_status
    (only 'available' rows are eligible to be masked/scored)."""
    rng = np.random.RandomState(seed)
    available = readings_df[readings_df.measurement_status == "available"].reset_index(drop=True)
    n_mask = int(len(available) * mask_fraction)
    mask_idx = rng.choice(len(available), size=n_mask, replace=False)

    errors = []
    error_by_maturity = {}
    for idx in mask_idx:
        row = available.iloc[idx]
        history = available[
            (available.station_id == row.station_id) & (available.sensor_name == row.sensor_name)
            & (available.simulation_time < row.simulation_time)
        ].value.tolist()
        type_history = available[
            (available.station_type == row.station_type) & (available.sensor_name == row.sensor_name)
            & (available.simulation_time < row.simulation_time)
        ].value.tolist()

        est, method, reliable = estimate_virtual_sensor_value(
            row.station_id, row.sensor_name, row.station_type,
            {(row.station_id, row.sensor_name): history[-10:]},
            {(row.station_type, row.sensor_name): type_history[-50:]},
            sensor_models,
        )
        if est is None:
            continue
        err = abs(est - row.value)
        errors.append(err)
        maturity = getattr(row, "sensor_maturity", "unknown")
        error_by_maturity.setdefault(maturity, []).append(err)

    errors = np.array(errors)
    return {
        "n_masked": n_mask, "n_scored": len(errors),
        "mae": float(np.mean(errors)) if len(errors) else None,
        "rmse": float(np.sqrt(np.mean(errors ** 2))) if len(errors) else None,
        "error_by_maturity": {k: float(np.mean(v)) for k, v in error_by_maturity.items()},
    }
