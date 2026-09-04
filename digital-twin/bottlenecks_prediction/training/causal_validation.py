"""Independent post-build leakage, schema, provenance, and state-replay validation."""
from __future__ import annotations

from collections import Counter, defaultdict
from numbers import Number
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from .validate_causal_dataset_contract import DEFECT_FEATURES, BOTTLENECK_FEATURES
except ImportError:  # Direct script execution: python training/causal_validation.py
    from validate_causal_dataset_contract import DEFECT_FEATURES, BOTTLENECK_FEATURES

RECENT_MS = 600_000
HORIZON_MS = 1_800_000
DEFECT_META = {"run_id", "unit_id", "prediction_station", "prediction_time", "prediction_event_sequence", "topology_configuration_version", "label_completeness_status", "y_defect"}
BOTTLENECK_META = {"run_id", "station_id_buffer_id", "prediction_time", "prediction_event_sequence", "capacity", "topology_configuration_version", "currently_at_capacity", "target_eligibility_status", "y_bottleneck"}


def station_index(value: str) -> int:
    return int(str(value).replace("S", "")) - 1


def equal(left, right) -> bool:
    """Compare feature scalars while preserving their value types."""
    left_missing = pd.isna(left)
    right_missing = pd.isna(right)
    if left_missing or right_missing:
        return bool(left_missing and right_missing)
    if isinstance(left, (bool, np.bool_)) or isinstance(right, (bool, np.bool_)):
        return isinstance(left, (bool, np.bool_)) and isinstance(right, (bool, np.bool_)) and bool(left) == bool(right)
    if isinstance(left, Number) and isinstance(right, Number):
        return bool(np.isclose(left, right, equal_nan=True))
    return left == right


def stats(values):
    values = pd.to_numeric(values, errors="coerce").dropna()
    return {"mean": values.mean() if len(values) else np.nan, "std": values.std(ddof=1) if len(values)>1 else np.nan, "max": values.max() if len(values) else np.nan}


def check_values(row, expected, feature_names, violations, category, prefix):
    for name in feature_names:
        if not equal(getattr(row, name), expected[name]):
            violations[category].append(f"{prefix}:{name}")


def validate(dataset_dir: Path, raw_root: Path) -> dict:
    defect = pd.read_parquet(dataset_dir / "defect_causal_features.parquet")
    bottleneck = pd.read_parquet(dataset_dir / "bottleneck_causal_features.parquet")
    defect_prov = pd.read_csv(dataset_dir / "defect_feature_provenance.csv")
    bottleneck_prov = pd.read_csv(dataset_dir / "bottleneck_feature_provenance.csv")
    violations: dict[str, list[str]] = defaultdict(list)
    checked = Counter()

    # Materialized-schema checks: no builder constants are trusted here.
    if [x for x in defect.columns if x in DEFECT_FEATURES] != DEFECT_FEATURES:
        violations["schema"].append("defect frozen columns missing, reordered, or extra")
    if [x for x in bottleneck.columns if x in BOTTLENECK_FEATURES] != BOTTLENECK_FEATURES:
        violations["schema"].append("bottleneck frozen columns missing, reordered, or extra")
    if set(defect.columns) - DEFECT_META - set(DEFECT_FEATURES):
        violations["metadata_leakage"].append("unexpected defect column")
    if set(bottleneck.columns) - BOTTLENECK_META - set(BOTTLENECK_FEATURES):
        violations["metadata_leakage"].append("unexpected bottleneck column")
    if set(defect_prov.feature_name) != set(DEFECT_FEATURES) or defect_prov.exact_definition.isna().any():
        violations["provenance"].append("defect provenance incomplete")
    if set(bottleneck_prov.feature_name) != set(BOTTLENECK_FEATURES) or bottleneck_prov.exact_definition.isna().any():
        violations["provenance"].append("bottleneck provenance incomplete")
    checked["features"] = len(DEFECT_FEATURES) + len(BOTTLENECK_FEATURES)
    checked["source_provenance_records"] = len(defect_prov) + len(bottleneck_prov)

    for run_id, rows in defect.groupby("run_id", sort=False):
        run = raw_root / run_id
        ev = pd.read_csv(run / "station_events.csv")
        sensors = pd.read_csv(run / "sensor_readings.csv")
        manual = pd.read_csv(run / "manual_checks.csv")
        qa = pd.read_csv(run / "inspection_results.csv")
        for frame in (ev, sensors, manual, qa):
            frame["station_index"] = frame.station_id.map(station_index)
            frame.timestamp_ms = pd.to_numeric(frame.timestamp_ms)
        entry_keys = set(zip(ev.loc[ev.event_type.eq("UNIT_ARRIVED"), "unit_id"], ev.loc[ev.event_type.eq("UNIT_ARRIVED"), "station_id"], ev.loc[ev.event_type.eq("UNIT_ARRIVED"), "timestamp_ms"]))
        units = pd.read_csv(run / "units.csv").set_index("unit_id")
        final_index = int(ev.station_index.max())
        for row in rows.itertuples(index=False):
            checked["defect_rows"] += 1
            s, t = row.prediction_station_index, row.prediction_time
            if (row.unit_id, row.prediction_station, t) not in entry_keys:
                violations["defect_replay"].append(f"{run_id}: prediction is not station entry")
            # Reconstruct every defect feature directly from raw observations using
            # the strict cutoff.  A mismatch catches builder leakage; this is not a
            # tautological test of a pre-filtered validator frame.
            q = ev[(ev.station_index < s) & (ev.timestamp_ms < t)].queue_length_after.dropna()
            cycles = ev[(ev.unit_id.eq(row.unit_id)) & ev.event_type.eq("PROCESSING_COMPLETED") & (ev.station_index < s) & (ev.timestamp_ms < t)].cycle_time_ms.dropna()
            checks = manual[(manual.unit_id.eq(row.unit_id)) & (manual.station_index < s) & (manual.timestamp_ms < t)]
            expected = {"prediction_station_index":s,"line_fraction":s / max(1, ev.station_index.max()),"manual_fail_count_cum":int(checks.result.eq("FAIL").sum()),"manual_check_count_cum":len(checks),"last_manual_fail":int(checks.result.eq("FAIL").iloc[-1]) if len(checks) else np.nan,"stations_since_last_manual_fail":s-int(checks[checks.result.eq("FAIL")].station_index.iloc[-1]) if checks.result.eq("FAIL").any() else np.nan,"queue_history_mean":stats(q)["mean"],"queue_history_std":stats(q)["std"],"cycle_history_max":stats(cycles)["max"],"cycle_history_std":stats(cycles)["std"]}
            expected["supplier_batch"] = units.loc[row.unit_id, "supplier_batch"]; expected["vehicle_model"] = units.loc[row.unit_id, "vehicle_model"]
            for sig, prefix in (("TORQUE", "torque"), ("VIBRATION", "vibration"), ("TEMPERATURE", "temperature"), ("CURRENT", "current")):
                hist = sensors[(sensors.sensor_type.eq(sig)) & (sensors.station_index < s) & (sensors.timestamp_ms < t)]
                recent = hist[hist.timestamp_ms >= t - RECENT_MS]
                h, r = stats(hist.value), stats(recent.value)
                expected.update({f"{prefix}_mean_history":h["mean"],f"{prefix}_max_history":h["max"],f"{prefix}_mean_recent":r["mean"],f"{prefix}_max_recent":r["max"]})
                if prefix in {"torque","vibration"}: expected[f"{prefix}_delta_recent_vs_history"] = r["mean"]-h["mean"] if not(pd.isna(r["mean"]) or pd.isna(h["mean"])) else np.nan
                if prefix == "torque": expected["torque_std_history"] = h["std"]
            expected["current_missing_recent"] = int(pd.isna(expected["current_mean_recent"]))
            check_values(row, expected, DEFECT_FEATURES, violations, "defect_replay", run_id)
            # QA is target-only. Reconstruct y_defect independently from the authoritative
            # final-station inspection record, without allowing QA into any X feature.
            final_qa = qa[(qa.unit_id.eq(row.unit_id)) & (qa.station_index.eq(final_index)) & (qa.timestamp_ms >= t)]
            complete = len(final_qa) > 0
            expected_status = "complete" if complete else "censored"
            expected_y = int(final_qa.result.eq("FAIL").any()) if complete else np.nan
            if row.label_completeness_status != expected_status:
                violations["target"].append(f"{run_id}:{row.unit_id}:defect completeness")
            if not equal(row.y_defect, expected_y):
                violations["target"].append(f"{run_id}:{row.unit_id}:defect target")
            if any("inspection_results.csv" in value for value in defect_prov.source_file_table.astype(str)):
                violations["defect_qa_leakage"].append("QA declared as an X source")

    replay = 0
    for run_id, rows in bottleneck.groupby("run_id", sort=False):
        ev = pd.read_csv(raw_root / run_id / "station_events.csv")
        stations = pd.read_csv(raw_root / run_id / "stations.csv").set_index("station_id")
        ev["event_sequence"] = np.arange(len(ev))
        ev.timestamp_ms = pd.to_numeric(ev.timestamp_ms)
        for station, station_rows in rows.groupby("station_id_buffer_id", sort=False):
            history = ev[ev.station_id.eq(station)].sort_values(["timestamp_ms", "event_sequence"])
            max_time = history.timestamp_ms.max()
            for row in station_rows.itertuples(index=False):
                checked["bottleneck_rows"] += 1
                t = row.prediction_time
                # For equal timestamps, retain only station events through this row's canonical event sequence.
                at_time = history[(history.timestamp_ms.eq(t)) & (history.event_sequence.eq(row.prediction_event_sequence))]
                if len(at_time) != 1:
                    violations["bottleneck_replay"].append(f"{run_id}:{station}:missing prediction event")
                    continue
                cutoff_sequence = row.prediction_event_sequence
                prior = history[(history.timestamp_ms < t) | ((history.timestamp_ms == t) & (history.event_sequence <= cutoff_sequence))]
                if (prior.timestamp_ms > t).any(): violations["bottleneck_cutoff"].append(f"{run_id}:{station}:future event")
                queue = prior.queue_length_after.dropna()
                occupancy = float(queue.iloc[-1]) if len(queue) else 0.0
                replay += 1
                if not equal(row.current_occupancy, occupancy):
                    violations["bottleneck_replay"].append(f"{run_id}:{station}:occupancy")
                expected_currently_at_capacity = bool(occupancy >= float(row.capacity))
                if bool(row.currently_at_capacity) != expected_currently_at_capacity:
                    violations["bottleneck_replay"].append(f"{run_id}:{station}:currently_at_capacity")
                ten = prior[(prior.timestamp_ms >= t-RECENT_MS) & (prior.timestamp_ms <= t)]
                previous = prior[(prior.timestamp_ms >= t-2*RECENT_MS) & (prior.timestamp_ms < t-RECENT_MS)]
                tq, pq, tc = stats(ten.queue_length_after), stats(previous.queue_length_after), stats(ten.cycle_time_ms)
                arrivals=(ten.event_type=="UNIT_ARRIVED").sum(); services=(ten.event_type=="PROCESSING_COMPLETED").sum(); prior_services=(previous.event_type=="PROCESSING_COMPLETED").sum()
                slope_data=ten[["timestamp_ms","queue_length_after"]].dropna()
                slope_times=slope_data["timestamp_ms"].to_numpy(dtype=float)
                slope_values=slope_data["queue_length_after"].to_numpy(dtype=float)
                slope=np.nan; slope_std=np.nan
                distinct_slope_times=np.unique(slope_times).size
                if len(slope_times) > 1 and distinct_slope_times > 1:
                    slope_x=slope_times-float(slope_times[0])
                    fit=np.polyfit(slope_x, slope_values, 1); slope=float(fit[0])
                    if distinct_slope_times >= 3:
                        residual=slope_values-(fit[0]*slope_x+fit[1]); dof=len(slope_x)-2
                        sxx=float(np.sum((slope_x-slope_x.mean())**2))
                        if dof>0 and sxx>0:
                            s_err=np.sqrt(np.sum(residual**2)/dof); slope_std=float(s_err/np.sqrt(sxx))

                # Independently reconstruct the three Light-Zone uncertainty features.
                prior_queue=pd.to_numeric(prior.queue_length_after,errors="coerce")
                current_queue=pd.to_numeric(at_time.queue_length_after,errors="coerce").iloc[0]
                if not pd.isna(current_queue):
                    state_confidence=1.0; progress_std=0.0
                else:
                    observed_positions=np.flatnonzero(prior_queue.notna().to_numpy())
                    if not len(observed_positions):
                        state_confidence=0.0; progress_std=np.nan
                    else:
                        oi=int(observed_positions[-1])
                        elapsed=float(t-prior.iloc[oi].timestamp_ms)
                        steps_missing=(len(prior)-1)-oi
                        state_confidence=float(np.exp(-elapsed/RECENT_MS))
                        progress_std=float(tq["std"]*np.sqrt(steps_missing)) if np.isfinite(tq["std"]) else np.nan
                headroom=float(row.capacity)-occupancy
                eta_std=np.nan
                if (np.isfinite(slope) and slope>0 and np.isfinite(headroom)
                        and np.isfinite(slope_std) and np.isfinite(progress_std)):
                    slope_term=(headroom/slope**2)**2 * slope_std**2
                    state_term=(1.0/slope)**2 * progress_std**2
                    eta_std=float(np.sqrt(slope_term+state_term))

                cfg=stations.loc[station]; idx=station_index(station)
                expected={"capacity_headroom":row.capacity-occupancy,"station_id":station,"base_cycle_time_ms":cfg.base_cycle_time_ms,"station_archetype":cfg.archetype,"configured_cycle_std_ms":cfg.cycle_time_std_ms,"station_index":idx,"buffer_capacity":cfg.buffer_capacity,"line_fraction":idx/max(1,len(stations)-1),"queue_max_10m":tq["max"],"queue_mean_10m":tq["mean"],"current_occupancy":occupancy,"queue_std_10m":tq["std"],"capacity_utilization":occupancy/row.capacity if row.capacity else np.nan,"arrival_rate_per_min_prev10m":(previous.event_type=="UNIT_ARRIVED").sum()/10,"service_rate_per_min_prev10m":prior_services/10,"service_rate_per_min_10m":services/10,"arrival_rate_per_min_10m":arrivals/10,"utilization_headroom":1-occupancy/row.capacity if row.capacity else np.nan,"cycle_max_10m":tc["max"],"flow_pressure_10m":arrivals-services,"queue_delta_10m":tq["mean"]-pq["mean"],"cycle_mean_10m":tc["mean"],"queue_slope_10m":slope,"net_flow_rate_10m":(arrivals-services)/10,"cycle_std_10m":tc["std"],"state_confidence":state_confidence,"progress_std":progress_std,"eta_std":eta_std}
                check_values(row, expected, BOTTLENECK_FEATURES, violations, "bottleneck_replay", f"{run_id}:{station}")
                future = history[(history.timestamp_ms > t) & (history.timestamp_ms <= t + HORIZON_MS)].queue_length_after.dropna()
                complete = max_time >= t + HORIZON_MS
                overflow = (future.max() if len(future) else -np.inf) >= row.capacity
                if bool(row.currently_at_capacity) and not pd.isna(row.y_bottleneck): violations["target"].append(f"{run_id}:{station}:already full labelled")
                if not complete and not pd.isna(row.y_bottleneck): violations["target"].append(f"{run_id}:{station}:censored horizon labelled")
                if complete and not bool(row.currently_at_capacity) and not equal(row.y_bottleneck, int(overflow)): violations["bottleneck_replay"].append(f"{run_id}:{station}:target")

    counts = {category: len(items) for category, items in violations.items()}
    return {"validation_executed": True, "rows_checked": dict(checked), "features_checked": checked["features"], "source_provenance_records_checked": checked["source_provenance_records"], "replay_checkpoints": replay, "violations_by_category": counts, "causal_violations": sum(counts.values()), "passed": not counts}
