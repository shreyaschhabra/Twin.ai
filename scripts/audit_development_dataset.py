"""
Step 4 EDA + synthetic-data validity + leakage/shortcut audit
(Sections Y-AF). Reads the persisted development_45 dataset and prints a
structured report. Not model training — the one-feature "diagnostic
models" in the shortcut-audit section exist purely to catch trivial
leakage, per instructions.

Usage:
    python scripts/audit_development_dataset.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "development_45"
OBS = BASE / "observable"
LAT = BASE / "latent"


def section(title):
    print(f"\n{'='*90}\n{title}\n{'='*90}")


def main():
    events = pd.read_parquet(OBS / "events.parquet")
    genealogy = pd.read_parquet(OBS / "genealogy.parquet")
    vehicles = pd.read_parquet(OBS / "vehicles.parquet")
    shifts = pd.read_parquet(OBS / "shifts.parquet")
    qc = pd.read_parquet(OBS / "qc_results.parquet")
    sensors = pd.read_parquet(OBS / "sensor_readings.parquet")

    exposure = pd.read_parquet(LAT / "quality_exposure.parquet")
    scenario_truth = pd.read_parquet(LAT / "scenario_truth.parquet")
    generator_truth = pd.read_parquet(LAT / "generator_truth.parquet")

    # ================================================================ Y: FLOW EDA
    section("Y. FLOW EDA")
    print("Vehicles per shift:\n", vehicles.groupby("shift_id").size().describe())
    print("\nVariant distribution:\n", vehicles.variant_id.value_counts(normalize=True))

    time_in_system = (vehicles.completed_at - vehicles.created_at).dropna()
    print(f"\nTotal time in system (s): mean={time_in_system.mean():.1f} "
          f"median={time_in_system.median():.1f} p95={time_in_system.quantile(0.95):.1f}")

    proc = events[events.event_type == "STATION_PROCESSING_COMPLETED"]
    util_by_station = proc.groupby("station_id")["value"].agg(["count", "mean"])
    print("\nProcessing count/mean-time by station (top 5 slowest mean):\n",
          util_by_station.sort_values("mean", ascending=False).head())

    state_changes = events[events.event_type == "STATION_STATE_CHANGED"]
    blocked_events = state_changes[state_changes.to_state == "BLOCKED"]
    down_events = state_changes[state_changes.to_state == "DOWN"]
    print(f"\nBLOCKED transitions: {len(blocked_events)} across {blocked_events.station_id.nunique()} stations")
    print(f"DOWN transitions (micro-stops): {len(down_events)} across {down_events.station_id.nunique()} stations")

    buffer_entries = events[events.event_type == "VEHICLE_ENTERED_BUFFER"].dropna(subset=["occupancy"])
    max_occ = buffer_entries.groupby("buffer_id")["occupancy"].max().sort_values(ascending=False)
    print("\nMax buffer occupancy (top 8):\n", max_occ.head(8))

    print(f"\nShift abnormal flag counts:\n{shifts.is_abnormal.value_counts()}")
    print(f"Throughput by shift: mean={shifts.throughput_vehicles_per_hour.mean():.2f} "
          f"min={shifts.throughput_vehicles_per_hour.min():.2f} max={shifts.throughput_vehicles_per_hour.max():.2f}")

    # ================================================================ Z: SENSOR EDA
    section("Z. SENSOR EDA")
    n_by_station_sensor = sensors.groupby(["station_id", "sensor_name"]).size()
    print(f"Distinct (station, sensor) pairs observed: {len(n_by_station_sensor)}")

    missingness = sensors.groupby("station_id")["measurement_status"].apply(
        lambda s: (s != "available").mean()
    ).sort_values(ascending=False)
    print("\nMissingness by station (top 10):\n", missingness.head(10))

    print("\nMeasurement status counts overall:\n", sensors.measurement_status.value_counts())

    # verify poor stations never expose rich telemetry
    poor_stations = {"S11", "S21", "S22", "S24", "S33", "S38"}
    poor_sensor_names = set(sensors[sensors.station_id.isin(poor_stations)].sensor_name.unique())
    print(f"\nSensor names seen at poor stations: {poor_sensor_names} (expect only checklist_completion)")

    # ================================================================ AA: QUALITY EDA
    section("AA. QUALITY EDA")
    overall_rate = (qc.qc_result == "DEFECT").mean()
    print(f"Overall defect rate: {overall_rate*100:.3f}%  (target band 3.5%-4.5%)")

    qc_v = qc.merge(vehicles[["vehicle_id", "variant_id"]], on="vehicle_id")
    print("\nDefect rate by variant:\n", qc_v.groupby("variant_id").qc_result.apply(lambda s: (s == "DEFECT").mean()))

    qc_shift = qc.merge(shifts[["shift_id", "is_abnormal"]], on="shift_id")
    print("\nDefect rate by shift abnormal flag:\n",
          qc_shift.groupby("is_abnormal").qc_result.apply(lambda s: (s == "DEFECT").mean()))
    print("\nDefect rate per shift (describe):\n",
          qc.groupby("shift_id").qc_result.apply(lambda s: (s == "DEFECT").mean()).describe())

    gt = generator_truth.copy()
    gt["is_defect"] = gt.qc_result == "DEFECT"
    print(f"\nBackground defects (total_exposure == 0 but DEFECT): "
          f"{((gt.total_exposure == 0) & gt.is_defect).sum()} "
          f"of {(gt.total_exposure == 0).sum()} zero-exposure vehicles")
    exposed = gt[gt.total_exposure > 0]
    print(f"Exposed vehicles: {len(exposed)} ({len(exposed)/len(gt)*100:.1f}% of all vehicles)  "
          f"defect rate among exposed: {exposed.is_defect.mean()*100:.2f}%")
    print(f"Exposed-but-PASS: {(~exposed.is_defect).sum()} / {len(exposed)}")
    # quantiles computed WITHIN the exposed subset (quantiles over the
    # whole population are meaningless here since ~89% of vehicles sit at
    # exactly zero exposure)
    high_exposure = exposed[exposed.total_exposure > exposed.total_exposure.quantile(0.9)]
    print(f"Top-decile-of-EXPOSED vehicles (exposure > {exposed.total_exposure.quantile(0.9):.4f}): "
          f"n={len(high_exposure)}, pass rate = {(~high_exposure.is_defect).mean()*100:.1f}% "
          f"(want > 0: probabilistic, not deterministic)")
    low_exposure = exposed[exposed.total_exposure < exposed.total_exposure.quantile(0.3)]
    print(f"Bottom-decile-of-EXPOSED vehicles (exposure < {exposed.total_exposure.quantile(0.3):.4f}): "
          f"n={len(low_exposure)}, defect rate = {low_exposure.is_defect.mean()*100:.1f}% "
          f"(want > 0: low exposure is not automatically safe)")
    print(f"Bottom-decile-of-EXPOSED vehicles that still defected: {low_exposure.is_defect.sum()}")

    # ================================================================ AB. SYNTHETIC SHORTCUT AUDIT
    section("AB. SYNTHETIC SHORTCUT AUDIT")
    y = (qc_v.qc_result == "DEFECT").astype(int)

    def one_feature_auc(feature, name):
        try:
            from sklearn.metrics import roc_auc_score
            return roc_auc_score(y, feature)
        except Exception as e:
            return f"n/a ({e})"

    variant_dummies = pd.get_dummies(qc_v.variant_id)
    for col in variant_dummies.columns:
        print(f"  variant=={col} alone -> AUC {one_feature_auc(variant_dummies[col], col):.4f}"
              if isinstance(one_feature_auc(variant_dummies[col], col), float) else "n/a")

    shift_dummies = pd.get_dummies(qc_shift.shift_id)
    best_shift_auc = max(
        (abs(one_feature_auc(shift_dummies[c], c) - 0.5) for c in shift_dummies.columns
         if isinstance(one_feature_auc(shift_dummies[c], c), float)),
        default=0,
    )
    print(f"  best single-shift-ID |AUC-0.5|: {best_shift_auc:.4f} (want near 0)")

    n_sensor_readings_per_vehicle = sensors.groupby("vehicle_id").size()
    joined = qc.set_index("vehicle_id").join(n_sensor_readings_per_vehicle.rename("n_sensors"), how="left").fillna(0)
    auc_nsensors = one_feature_auc(joined.n_sensors, "n_sensors")
    print(f"  sensor-reading-COUNT alone -> AUC {auc_nsensors:.4f} (want near 0.5)")

    route_len = genealogy.groupby("vehicle_id").size()
    joined2 = qc.set_index("vehicle_id").join(route_len.rename("route_len"), how="left").fillna(0)
    auc_routelen = one_feature_auc(joined2.route_len, "route_len")
    print(f"  route length alone -> AUC {auc_routelen:.4f} (want near 0.5; EV has 44 vs 45)")

    batch_events = events[events.event_type == "MATERIAL_BATCH_ASSIGNED"]
    has_batch = qc.vehicle_id.isin(batch_events.vehicle_id.unique()).astype(int)
    auc_batch_presence = one_feature_auc(has_batch, "has_batch")
    print(f"  batch PRESENCE alone -> AUC {auc_batch_presence:.4f} (want near 0.5)")

    # ================================================================ AC. LEAKAGE AUDIT
    section("AC. LEAKAGE AUDIT")
    from backend.simulation.scenarios.latent import PROHIBITED_OBSERVABLE_FIELDS
    observable_cols = set(events.columns) | set(sensors.columns) | set(qc.columns) | set(genealogy.columns) | set(vehicles.columns) | set(shifts.columns)
    leaked_cols = observable_cols & PROHIBITED_OBSERVABLE_FIELDS
    print(f"Prohibited fields present in observable columns: {leaked_cols or 'NONE'}")

    qc_times = events[events.event_type == "QC_RESULT_RECORDED"][["vehicle_id", "simulation_time"]].rename(
        columns={"simulation_time": "qc_time"}
    )
    pre_qc = genealogy.merge(qc_times, on="vehicle_id")
    violations = pre_qc[pre_qc.exit_time > pre_qc.qc_time]
    # S45 itself is allowed to be <= qc_time (it's recorded right after S45 completes)
    violations = violations[violations.station_id != "S45"]
    print(f"Temporal leakage violations (pre-S45 visit ending after QC time): {len(violations)} (want 0)")

    # ================================================================ AD. QC GENERATOR AUDIT
    section("AD. QC GENERATOR AUDIT")
    corr = gt.total_exposure.corr(gt.probability_used)
    print(f"Correlation(total_exposure, probability_used): {corr:.4f} (want strongly positive)")
    print(f"Zero-exposure defect rate: {gt[gt.total_exposure==0].is_defect.mean()*100:.2f}% (want > 0)")
    print(f"High-exposure (top decile) pass rate: {(~high_exposure.is_defect).mean()*100:.1f}% (want > 0)")

    dropout_family_vehicles = set(exposure[exposure.family == "SENSOR_DROPOUT"].vehicle_id) if "family" in exposure.columns else set()
    print(f"SENSOR_DROPOUT exposure records: {len(exposure[exposure.family=='SENSOR_DROPOUT']) if 'family' in exposure.columns else 0} (want 0 by design)")
    mix_family_records = exposure[exposure.family == "VEHICLE_MIX_OVERLOAD"] if "family" in exposure.columns else pd.DataFrame()
    print(f"VEHICLE_MIX_OVERLOAD exposure records: {len(mix_family_records)} (want 0 by design)")

    family_rates = exposure.groupby("family").contribution.agg(["count", "mean", "sum"])
    print("\nMean/sum latent contribution by family (NOT a defect rate — see Patch 3 below):\n", family_rates)

    # ================================================================ PATCH 3: CONDITIONAL DEFECT RATE BY FAMILY
    section("PATCH 3. CONDITIONAL DEFECT RATE BY SCENARIO FAMILY")
    print("Sanity checks only — these do not establish causality, and a vehicle may")
    print("belong to more than one family's cohort simultaneously (overlap is reported, not hidden).\n")

    is_defect_by_vehicle = gt.set_index("vehicle_id").is_defect

    families_with_exposure = ["EQUIPMENT_DEGRADATION", "BAD_BATCH", "ENVIRONMENTAL_DRIFT", "MANUAL_VARIATION", "RANDOM_QUALITY_EVENT"]
    rows = []
    exposed_vehicle_sets = {}
    for fam in families_with_exposure:
        fam_exposure = exposure[exposure.family == fam]
        exposed_vehicles = set(fam_exposure.vehicle_id.unique())
        exposed_vehicle_sets[fam] = exposed_vehicles
        n_instances = (scenario_truth.family == fam).sum()
        n_exposed = len(exposed_vehicles)
        n_defective = sum(1 for v in exposed_vehicles if is_defect_by_vehicle.get(v, False))
        cond_rate = n_defective / n_exposed if n_exposed else float("nan")
        rows.append({
            "family": fam, "n_instances": n_instances, "n_exposed_vehicles": n_exposed,
            "n_defective": n_defective, "conditional_defect_rate": cond_rate,
            "mean_contribution": fam_exposure.contribution.mean() if n_exposed else float("nan"),
            "median_contribution": fam_exposure.contribution.median() if n_exposed else float("nan"),
        })
    print(pd.DataFrame(rows).to_string(index=False))

    # overlap report: how many vehicles belong to >1 family cohort
    from collections import Counter
    membership_count = Counter()
    for fam, vset in exposed_vehicle_sets.items():
        for v in vset:
            membership_count[v] += 1
    overlap_n = sum(1 for c in membership_count.values() if c > 1)
    print(f"\nVehicles exposed to more than one family's cohort simultaneously: {overlap_n}")

    baseline_rate = gt[gt.total_exposure == 0].is_defect.mean()
    print(f"\nBaseline (zero-exposure) defect rate for comparison: {baseline_rate*100:.2f}%")

    # families configured to contribute ZERO exposure by design: SENSOR_DROPOUT,
    # VEHICLE_MIX_OVERLOAD. No exposure-table membership exists for them, so
    # "affected vehicles" is reconstructed independently: vehicles whose
    # SENSOR_READING was degraded (dropout) or who were CREATED during an
    # active mix-overload window (mix), then checked against baseline rate.
    dropout_scenarios = scenario_truth[scenario_truth.family == "SENSOR_DROPOUT"]
    degraded_readings = sensors[sensors.measurement_status != "available"]
    dropout_affected_vehicles = set(degraded_readings.vehicle_id.unique())
    n_dropout_affected = len(dropout_affected_vehicles)
    dropout_defect_rate = (
        sum(1 for v in dropout_affected_vehicles if is_defect_by_vehicle.get(v, False)) / n_dropout_affected
        if n_dropout_affected else float("nan")
    )
    print(f"\nSENSOR_DROPOUT: {len(dropout_scenarios)} instance(s), "
          f"{n_dropout_affected} vehicle(s) with a degraded reading, "
          f"defect rate among them = {dropout_defect_rate*100:.2f}% "
          f"(compare to baseline {baseline_rate*100:.2f}% — want statistically compatible, not elevated)")

    mix_scenarios = scenario_truth[scenario_truth.family == "VEHICLE_MIX_OVERLOAD"]
    created = events[events.event_type == "VEHICLE_CREATED"][["vehicle_id", "shift_id", "simulation_time"]]
    mix_affected_vehicles = set()
    for _, srow in mix_scenarios.iterrows():
        window = created[created.shift_id == srow.shift_id]
        start, end = srow.start_time, (srow.end_time if pd.notna(srow.end_time) else float("inf"))
        mix_affected_vehicles |= set(window[(window.simulation_time >= start) & (window.simulation_time <= end)].vehicle_id)
    n_mix_affected = len(mix_affected_vehicles)
    mix_defect_rate = (
        sum(1 for v in mix_affected_vehicles if is_defect_by_vehicle.get(v, False)) / n_mix_affected
        if n_mix_affected else float("nan")
    )
    print(f"VEHICLE_MIX_OVERLOAD: {len(mix_scenarios)} instance(s), "
          f"{n_mix_affected} vehicle(s) created during an active window, "
          f"defect rate among them = {mix_defect_rate*100:.2f}% "
          f"(compare to baseline {baseline_rate*100:.2f}% — want statistically compatible, not elevated)")

    # ================================================================ AE/AF: CAUSAL AUDIT
    section("AE/AF. CAUSAL AUDIT (flow + sensor/quality)")
    print(f"Scenario instances scheduled: {len(scenario_truth)} across families:\n",
          scenario_truth.family.value_counts())
    print(f"\nTotal BLOCKED episodes: {len(blocked_events)}; total DOWN (micro-stop) episodes: {len(down_events)}")
    print("These, plus the buffer-occupancy growth already shown in Y, are the evidence Step 5's")
    print("Flow target definition will rely on: scenario -> rate deficit -> queue growth -> blocking.")

    print(f"\nBatch key sample (canonical station_id::batch_id identity):",
          batch_events.batch_key.dropna().unique()[:5] if "batch_key" in batch_events.columns else "n/a")


if __name__ == "__main__":
    main()
