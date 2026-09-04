"""Fail-fast preflight for the causal feature-dataset contract.

This deliberately runs before feature calculation.  It derives available raw signals
from every generated run and refuses to materialize a frozen schema when a required
feature has no source.  That prevents a later caller from silently replacing a
missing signal with a proxy or a future-derived aggregate.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


DEFECT_FEATURES = [
    "torque_delta_recent_vs_history", "manual_fail_count_cum", "prediction_station_index",
    "torque_mean_history", "line_fraction", "last_manual_fail", "manual_check_count_cum",
    "torque_mean_recent", "queue_history_mean", "current_mean_recent",
    "current_missing_recent", "vibration_delta_recent_vs_history", "current_mean_history",
    "torque_max_recent", "temperature_mean_history", "torque_max_history", "supplier_batch",
    "current_max_history", "cycle_history_max", "temperature_max_recent",
    "vibration_mean_history", "temperature_max_history", "stations_since_last_manual_fail",
    "vehicle_model", "vibration_max_history", "vibration_max_recent", "temperature_mean_recent",
    "torque_std_history", "queue_history_std", "cycle_history_std",
]

BOTTLENECK_FEATURES = [
    "capacity_headroom", "station_id", "base_cycle_time_ms", "station_archetype",
    "configured_cycle_std_ms", "station_index", "buffer_capacity", "line_fraction",
    "queue_max_10m", "queue_mean_10m", "current_occupancy", "queue_std_10m",
    "capacity_utilization", "arrival_rate_per_min_prev10m", "service_rate_per_min_prev10m",
    "service_rate_per_min_10m", "arrival_rate_per_min_10m", "utilization_headroom",
    "cycle_max_10m", "flow_pressure_10m", "queue_delta_10m", "cycle_mean_10m",
    "queue_slope_10m", "net_flow_rate_10m", "cycle_std_10m",
    "state_confidence", "progress_std", "eta_std",
]

# Every raw sensor needed by the frozen defect feature names.  The feature builder
# must read this declaration before it aggregates anything.
REQUIRED_SENSOR_SIGNALS = {"TORQUE", "VIBRATION", "TEMPERATURE", "CURRENT"}


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as stream:
        return next(csv.reader(stream), [])


def values(path: Path, column: str) -> set[str]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {row[column].strip().upper() for row in csv.DictReader(stream) if row.get(column)}


def git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def inspect_run(run: Path) -> dict:
    required = {
        "station_events.csv", "sensor_readings.csv", "manual_checks.csv",
        "inspection_results.csv", "stations.csv", "units.csv", "run_metadata.json",
    }
    missing_files = sorted(name for name in required if not (run / name).is_file())
    data = {"run_id": run.name, "path": str(run), "missing_files": missing_files}
    if missing_files:
        return data

    sensor_header = csv_header(run / "sensor_readings.csv")
    station_header = csv_header(run / "station_events.csv")
    station_ids = values(run / "stations.csv", "station_id")
    sensor_signals = values(run / "sensor_readings.csv", "sensor_type")
    # Read only TORQUE rows with the stdlib so the preflight has no hidden ML/data dependency.
    torque_rows = 0; torque_stations: set[str] = set(); torque_times: list[int] = []; invalid_torque = 0
    with (run / "sensor_readings.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("sensor_type", "").strip().upper() != "TORQUE":
                continue
            torque_rows += 1
            try:
                timestamp = int(row["timestamp_ms"]); float(row["value"])
                if not row.get("station_id"): raise ValueError("missing station")
            except (KeyError, TypeError, ValueError):
                invalid_torque += 1; continue
            torque_stations.add(row["station_id"]); torque_times.append(timestamp)
    event_types = values(run / "station_events.csv", "event_type")
    with (run / "run_metadata.json").open(encoding="utf-8") as stream:
        metadata = json.load(stream)
    data.update({
        "metadata_run_id": metadata.get("run_id"),
        "metadata_station_count": metadata.get("station_count"),
        "station_count_discovered": len(station_ids),
        "station_ids": sorted(station_ids),
        "sensor_columns": sensor_header,
        "station_event_columns": station_header,
        "sensor_signals": sorted(sensor_signals),
        "torque_audit": {"row_count": torque_rows, "station_count": len(torque_stations),
                         "station_ids": sorted(torque_stations), "timestamp_min_ms": min(torque_times) if torque_times else None,
                         "timestamp_max_ms": max(torque_times) if torque_times else None,
                         "invalid_or_missing_value_rows": invalid_torque,
                         "usable": torque_rows > 0 and invalid_torque == 0},
        "station_event_types": sorted(event_types),
    })
    return data


def build_report(root: Path, input_dir: Path) -> dict:
    runs = [inspect_run(path) for path in sorted(input_dir.glob("run_*")) if path.is_dir()]
    all_signals = set().union(*(set(run.get("sensor_signals", [])) for run in runs)) if runs else set()
    missing_signal_runs = {
        signal: [run["run_id"] for run in runs if signal not in set(run.get("sensor_signals", []))]
        for signal in sorted(REQUIRED_SENSOR_SIGNALS)
    }
    violations: list[dict] = []
    if not runs:
        violations.append({"rule": "raw-run-discovery", "severity": "ERROR", "detail": "No run_* directories found."})
    for run in runs:
        if run["missing_files"]:
            violations.append({"rule": "raw-schema", "severity": "ERROR", "run_id": run["run_id"],
                               "detail": "Missing required raw file(s): " + ", ".join(run["missing_files"])})
    for signal, absent in missing_signal_runs.items():
        if absent:
            affected = [name for name in DEFECT_FEATURES if name.startswith(signal.lower())]
            violations.append({
                "rule": "frozen-defect-feature-source", "severity": "ERROR", "signal": signal,
                "affected_features": affected, "runs": absent,
                "detail": (
                    f"Raw sensor_readings.csv for this input run does not export usable {signal}. "
                    "No causal proxy or substituted signal is permitted."
                ),
            })
    station_counts = Counter(run.get("station_count_discovered") for run in runs if "station_count_discovered" in run)
    return {
        "dataset_version": "pre-ml-causal-contract-v1",
        "feature_schema_version": "defect-30-v1 / bottleneck-28-v1",
        "causal_rule_version": "station-and-event-time-v1",
        "target_definition_version": "downstream-qa-v1 / future-overflow-30m-v1",
        "build_timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(root),
        "input_root": str(input_dir),
        "runs_discovered": len(runs),
        "topology_summary": {"station_counts_discovered": dict(station_counts), "fixed_station_assumption": False},
        "required_defect_feature_count": len(DEFECT_FEATURES),
        "required_bottleneck_feature_count": len(BOTTLENECK_FEATURES),
        "available_sensor_signals_union": sorted(all_signals),
        "runs": runs,
        "causal_violations": violations,
        "materialization_permitted": not any(item["severity"] == "ERROR" for item in violations),
        "next_required_action": (
            "Materialize the causal datasets from these validated raw runs."
            if not violations else "Correct the listed raw-data contract violations before materialization."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate raw data against frozen causal ML schemas.")
    parser.add_argument("--input", type=Path, default=Path("output"))
    parser.add_argument("--report", type=Path, default=Path("causal_audit_report.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = build_report(root, args.input.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["materialization_permitted"]:
        print(f"BLOCKED: frozen schema cannot be materialized; see {args.report}", file=sys.stderr)
        return 2
    print("Preflight passed. Feature materialization may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
