"""
Quality feature engineering (Section 16). Strictly point-in-time per
vehicle: every feature at a snapshot (vehicle_id, snapshot_time) uses only
that vehicle's own events with simulation_time <= snapshot_time, plus (for
the two cohort features) OTHER vehicles' ALREADY-RECORDED QC outcomes with
qc_time < snapshot_time -- never this vehicle's own future, never a QC
result that happens later in simulated time than the snapshot itself.

~25 features across 5 groups (Section 16): vehicle context, process-
history summary, sensor-history summary, quality-relevant process
evidence, genealogy/material context. Deliberately compact -- no raw
batch_key used as a category (that would let the model memorize
"S05::B1002 -> defective" instead of learning a real signal).
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

TORQUE_SENSORS = {"torque_value", "torque_angle"}
DIMENSIONAL_SENSORS = {"laser_scan", "vision_camera"}
PAINT_SENSORS = {"booth_temperature", "booth_humidity", "film_thickness", "oven_temperature", "belt_speed", "humidity"}
SEALING_SENSORS = {"adhesive_flow_rate"}
ABNORMAL_Z_THRESHOLD = 2.0
SLOW_VISIT_RELATIVE_THRESHOLD = 0.20

NUMERIC_FEATURES = [
    "production_stage", "stations_completed", "elapsed_production_time",
    "mean_cycle_deviation", "max_cycle_deviation", "cycle_deviation_std", "recent_cycle_deviation_3",
    "count_slow_visits", "waiting_time_total", "waiting_time_mean",
    "max_standardized_deviation", "count_abnormal_readings", "latest_deviation", "mean_abnormality",
    "sensor_coverage", "sensor_missingness", "sensor_freshness",
    "torque_deviation_max", "dimensional_deviation_max", "paint_environment_deviation_max",
    "sealing_deviation_max", "deviation_trend",
    "n_batch_contexts_visited", "cohort_defect_rate_mean", "cohort_sample_size_mean",
]
CATEGORICAL_FEATURES = ["vehicle_variant"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _expected_cycle_time_table(config) -> Dict[tuple, float]:
    table = {}
    for station_id, station_cfg in config.stations.items():
        for variant_id, variant_cfg in config.vehicle_variants.items():
            override = station_cfg.variant_overrides.get(variant_id)
            if override is not None and override.cycle_time_multiplier is not None:
                mult = override.cycle_time_multiplier
            else:
                mult = variant_cfg.processing_time_modifiers.get(station_id, 1.0)
            table[(station_id, variant_id)] = station_cfg.baseline_cycle_time_seconds * mult
    return table


def _sensor_category(sensor_name: str) -> Optional[str]:
    if sensor_name in TORQUE_SENSORS:
        return "torque"
    if sensor_name in DIMENSIONAL_SENSORS:
        return "dimensional"
    if sensor_name in PAINT_SENSORS:
        return "paint_environment"
    if sensor_name in SEALING_SENSORS:
        return "sealing"
    return None


def _build_cohort_index(events_df: pd.DataFrame) -> Dict[str, tuple]:
    """batch_key -> (sorted qc_times array, cumulative defect count array,
    cumulative total count array), built from OTHER vehicles' own
    already-recorded QC outcomes. Looking up with searchsorted at a
    snapshot's own time gives only cohort members whose QC was recorded
    strictly before that snapshot -- never this vehicle's own result
    (which hasn't happened yet pre-S45) and never a future cohort
    outcome."""
    batch_assign = events_df[events_df.event_type == "MATERIAL_BATCH_ASSIGNED"][
        ["vehicle_id", "batch_key"]
    ].drop_duplicates()
    qc = events_df[events_df.event_type == "QC_RESULT_RECORDED"][
        ["vehicle_id", "simulation_time", "qc_result"]
    ].rename(columns={"simulation_time": "qc_time"})
    merged = batch_assign.merge(qc, on="vehicle_id", how="inner")
    merged["is_defect"] = (merged.qc_result == "DEFECT").astype(int)
    merged = merged.sort_values(["batch_key", "qc_time"])

    index = {}
    for batch_key, grp in merged.groupby("batch_key", sort=False):
        times = grp.qc_time.to_numpy()
        cum_defect = np.cumsum(grp.is_defect.to_numpy())
        cum_total = np.arange(1, len(grp) + 1)
        index[batch_key] = (times, cum_defect, cum_total)
    return index


def _cohort_lookup(index, batch_key: str, t: float):
    if batch_key not in index:
        return None
    times, cum_defect, cum_total = index[batch_key]
    idx = np.searchsorted(times, t, side="left") - 1  # strictly before t
    if idx < 0:
        return None
    return float(cum_defect[idx]), float(cum_total[idx])


def build_quality_features(snapshots: pd.DataFrame, events_df: pd.DataFrame, config, sensor_models: Dict) -> pd.DataFrame:
    """snapshots: output of build_vehicle_snapshots(). Returns snapshots
    with the ~25 feature columns appended."""
    expected_cycle = _expected_cycle_time_table(config)
    cohort_index = _build_cohort_index(events_df)

    proc = events_df[events_df.event_type == "STATION_PROCESSING_COMPLETED"][
        ["vehicle_id", "station_id", "simulation_time", "value"]
    ].sort_values(["vehicle_id", "simulation_time"])
    proc_by_vehicle = {k: g for k, g in proc.groupby("vehicle_id", sort=False)}

    arr = events_df[events_df.event_type == "VEHICLE_ENTERED_STATION"][
        ["vehicle_id", "station_id", "simulation_time"]
    ].sort_values(["vehicle_id", "simulation_time"])
    arr_by_vehicle = {k: g for k, g in arr.groupby("vehicle_id", sort=False)}

    sr = events_df[events_df.event_type == "SENSOR_READING"][
        ["vehicle_id", "station_id", "sensor_name", "value", "measurement_status", "simulation_time"]
    ].sort_values(["vehicle_id", "simulation_time"])
    sr_by_vehicle = {k: g for k, g in sr.groupby("vehicle_id", sort=False)}

    batch = events_df[events_df.event_type == "MATERIAL_BATCH_ASSIGNED"][
        ["vehicle_id", "batch_key", "simulation_time"]
    ].sort_values(["vehicle_id", "simulation_time"])
    batch_by_vehicle = {k: g for k, g in batch.groupby("vehicle_id", sort=False)}

    created = events_df[events_df.event_type == "VEHICLE_CREATED"][["vehicle_id", "simulation_time"]]
    entry_time = dict(zip(created.vehicle_id, created.simulation_time))

    out_rows = []
    for vehicle_id, vrows in snapshots.groupby("vehicle_id", sort=False):
        variant = vrows.vehicle_variant.iloc[0]
        v_proc = proc_by_vehicle.get(vehicle_id)
        v_arr = arr_by_vehicle.get(vehicle_id)
        v_sr = sr_by_vehicle.get(vehicle_id)
        v_batch = batch_by_vehicle.get(vehicle_id)
        t0 = entry_time.get(vehicle_id, np.nan)

        for row in vrows.itertuples():
            t = row.snapshot_time
            feats = {}

            proc_so_far = v_proc[v_proc.simulation_time <= t] if v_proc is not None else pd.DataFrame(columns=proc.columns)

            feats["stations_completed"] = len(proc_so_far)
            feats["elapsed_production_time"] = (t - t0) if pd.notna(t0) else np.nan

            if len(proc_so_far):
                expected = proc_so_far.apply(lambda r: expected_cycle.get((r.station_id, variant), np.nan), axis=1)
                dev_rel = (proc_so_far.value.to_numpy() - expected.to_numpy()) / expected.to_numpy()
                feats["mean_cycle_deviation"] = float(np.nanmean(dev_rel))
                feats["max_cycle_deviation"] = float(np.nanmax(dev_rel))
                feats["cycle_deviation_std"] = float(np.nanstd(dev_rel)) if len(dev_rel) > 1 else 0.0
                feats["recent_cycle_deviation_3"] = float(np.nanmean(dev_rel[-3:]))
                feats["count_slow_visits"] = int(np.nansum(dev_rel > SLOW_VISIT_RELATIVE_THRESHOLD))
            else:
                feats.update({"mean_cycle_deviation": np.nan, "max_cycle_deviation": np.nan,
                              "cycle_deviation_std": np.nan, "recent_cycle_deviation_3": np.nan,
                              "count_slow_visits": 0})

            arr_so_far = v_arr[v_arr.simulation_time <= t] if v_arr is not None else pd.DataFrame(columns=arr.columns)
            if len(arr_so_far) > 1 and len(proc_so_far) > 0:
                waits = []
                proc_sorted = proc_so_far.sort_values("simulation_time")
                arr_sorted = arr_so_far.sort_values("simulation_time").reset_index(drop=True)
                completed_times = proc_sorted.simulation_time.to_numpy()
                for i in range(1, min(len(arr_sorted), len(completed_times) + 1)):
                    wait = arr_sorted.simulation_time.iloc[i] - completed_times[i - 1]
                    waits.append(max(0.0, wait))
                feats["waiting_time_total"] = float(sum(waits)) if waits else 0.0
                feats["waiting_time_mean"] = float(np.mean(waits)) if waits else 0.0
            else:
                feats["waiting_time_total"] = 0.0
                feats["waiting_time_mean"] = 0.0

            sr_so_far = v_sr[(v_sr.simulation_time <= t)] if v_sr is not None else pd.DataFrame(columns=sr.columns)
            avail = sr_so_far[sr_so_far.measurement_status == "available"] if len(sr_so_far) else sr_so_far
            if len(avail):
                std_devs = []
                cats = {"torque": [], "dimensional": [], "paint_environment": [], "sealing": []}
                for r in avail.itertuples():
                    sm = sensor_models.get((r.station_id, r.sensor_name))
                    if sm is None or sm.noise_std <= 0:
                        continue
                    z = (r.value - sm.baseline) / sm.noise_std
                    std_devs.append((r.simulation_time, z))
                    cat = _sensor_category(r.sensor_name)
                    if cat:
                        cats[cat].append(abs(z))
                if std_devs:
                    std_devs.sort(key=lambda x: x[0])
                    z_values = np.array([z for _, z in std_devs])
                    feats["max_standardized_deviation"] = float(np.max(np.abs(z_values)))
                    feats["count_abnormal_readings"] = int(np.sum(np.abs(z_values) > ABNORMAL_Z_THRESHOLD))
                    feats["latest_deviation"] = float(z_values[-1])
                    feats["mean_abnormality"] = float(np.mean(np.abs(z_values)))
                    recent = z_values[-5:]
                    feats["deviation_trend"] = float(np.mean(np.abs(recent)) - feats["mean_abnormality"])
                    feats["sensor_freshness"] = float(t - std_devs[-1][0])
                else:
                    feats.update({"max_standardized_deviation": np.nan, "count_abnormal_readings": 0,
                                  "latest_deviation": np.nan, "mean_abnormality": np.nan,
                                  "deviation_trend": np.nan, "sensor_freshness": 9999.0})
                for cat, vals in cats.items():
                    feats[f"{cat}_deviation_max" if cat != "paint_environment" else "paint_environment_deviation_max"] = (
                        float(max(vals)) if vals else np.nan
                    )
            else:
                feats.update({"max_standardized_deviation": np.nan, "count_abnormal_readings": 0,
                              "latest_deviation": np.nan, "mean_abnormality": np.nan,
                              "deviation_trend": np.nan, "sensor_freshness": 9999.0,
                              "torque_deviation_max": np.nan, "dimensional_deviation_max": np.nan,
                              "paint_environment_deviation_max": np.nan, "sealing_deviation_max": np.nan})

            if len(sr_so_far) and feats["stations_completed"] > 0:
                feats["sensor_coverage"] = float(sr_so_far.station_id.nunique() / feats["stations_completed"])
                feats["sensor_missingness"] = float((sr_so_far.measurement_status != "available").mean())
            else:
                feats["sensor_coverage"] = 0.0
                feats["sensor_missingness"] = 1.0 if len(sr_so_far) else 0.0

            batch_so_far = v_batch[v_batch.simulation_time <= t] if v_batch is not None else pd.DataFrame(columns=batch.columns)
            batch_keys = batch_so_far.batch_key.unique().tolist() if len(batch_so_far) else []
            feats["n_batch_contexts_visited"] = len(batch_keys)
            if batch_keys:
                rates, sizes = [], []
                for bk in batch_keys:
                    hit = _cohort_lookup(cohort_index, bk, t)
                    if hit is not None:
                        n_defect, n_total = hit
                        rates.append(n_defect / n_total)
                        sizes.append(n_total)
                feats["cohort_defect_rate_mean"] = float(np.mean(rates)) if rates else np.nan
                feats["cohort_sample_size_mean"] = float(np.mean(sizes)) if sizes else 0.0
            else:
                feats["cohort_defect_rate_mean"] = np.nan
                feats["cohort_sample_size_mean"] = 0.0

            record = {
                "vehicle_id": row.vehicle_id, "shift_id": row.shift_id, "vehicle_variant": variant,
                "checkpoint_station_id": row.checkpoint_station_id, "production_stage": row.production_stage,
                "snapshot_time": t,
            }
            record.update(feats)
            out_rows.append(record)

    return pd.DataFrame(out_rows)
