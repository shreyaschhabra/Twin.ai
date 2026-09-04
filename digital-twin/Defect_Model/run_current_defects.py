"""Live defect consumer for the shared simulator public event bus.

The simulator is an independent process. This module tails the same ordered
``runtime_events.csv`` used by bottlenecks and consumes only causal records
needed by the V5 defect model:

* STATION  -> station-event state / UNIT_ARRIVED prediction trigger
* SENSOR   -> sensor telemetry
* MANUAL   -> manual PASS/FAIL observations
* EVIDENCE -> fed to the defect DARK PF mirror (RFID/POWER only)

``inspection_results.csv`` is ground truth and is NEVER consumed by this live
path. The consumer stops only after ``run_metadata.json`` appears and the bus
has drained.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DEFAULT_RUN_DIR = PROJECT_ROOT / "bottlenecks_prediction" / "data" / "input" / "current_run"
DEFAULT_OUTPUT = ROOT / "data" / "output" / "defect_predictions.jsonl"
DEFAULT_ARTIFACT_ROOT = ROOT / "factory_models"
DEFAULT_HISTORY_ROOT = PROJECT_ROOT / "bottlenecks_prediction" / "data" / "calibration" / "history"
DEFAULT_DARK_ZONE_DIR = PROJECT_ROOT / "bottlenecks_prediction" / "dark_zone"

try:
    from .defect_main import build_pipeline
    from .factory_models import BASE_MODEL_ID, model_paths, selected_model_id, validate_runtime_factory_contract
    from .output.defect_prediction_output import append_jsonl
    from .runtime.dark_zone_adapter import DefectDarkZoneAdapter
except ImportError:  # python Defect_Model/run_current.py
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from Defect_Model.defect_main import build_pipeline
    from Defect_Model.factory_models import BASE_MODEL_ID, model_paths, selected_model_id, validate_runtime_factory_contract
    from Defect_Model.output.defect_prediction_output import append_jsonl
    from Defect_Model.runtime.dark_zone_adapter import DefectDarkZoneAdapter
from Defect_Model.runtime.public_bus import (
    REQUIRED_BUS_COLUMNS, checkpoint_progress_map, runtime_row_to_record,
)

# Backward-compatible test/import aliases.
_runtime_row_to_record = runtime_row_to_record
_checkpoint_progress_map = checkpoint_progress_map


def _wait_for_inputs(run_dir: Path, timeout_s: float, poll_s: float) -> dict[str, Path]:
    required = {
        "stations": run_dir / "stations.csv",
        "units": run_dir / "units.csv",
        "bus": run_dir / "runtime_events.csv",
        "dz": run_dir / "dz.csv",
        "station_checkpoints": run_dir / "station_checkpoints.csv",
    }
    deadline = time.monotonic() + float(timeout_s)
    while True:
        missing = [name for name, path in required.items() if not path.is_file()]
        if not missing:
            return required
        if time.monotonic() >= deadline:
            raise FileNotFoundError(
                "Timed out waiting for simulator defect-live files: " + ", ".join(missing)
            )
        time.sleep(poll_s)



def _history_runs(root: Path, current_run: Path) -> list[Path]:
    if not root.is_dir():
        return []
    current = current_run.resolve()
    out: list[Path] = []
    for run in sorted(root.iterdir()):
        if not run.is_dir() or run.resolve() == current:
            continue
        if all((run / name).is_file() for name in ("stations.csv", "units.csv", "station_events.csv")):
            out.append(run)
    return out


def _resolve_model(model_id: str | None, artifact_root: Path, stations_csv: Path) -> dict:
    chosen = str(model_id or selected_model_id(artifact_root))
    paths = model_paths(chosen, artifact_root)
    if chosen != BASE_MODEL_ID:
        validate_runtime_factory_contract(paths, Path(stations_csv).expanduser().resolve().parent)
    return {"id": chosen, **paths}


def _validate_output(path: Path, *, explain_mode: str) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Defect output not created: {path}")
    rows = warnings = explained = 0
    max_risk = 0.0
    max_shap_error = 0.0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            p = float(row["defect_probability"])
            raw = float(row["raw_defect_probability"])
            risk = float(row["defect_risk_percent"])
            threshold = float(row["decision_threshold"])
            if not (math.isfinite(p) and 0.0 <= p <= 1.0):
                raise RuntimeError(f"Invalid defect_probability on output line {line_no}")
            if not (math.isfinite(raw) and 0.0 <= raw <= 1.0):
                raise RuntimeError(f"Invalid raw_defect_probability on output line {line_no}")
            if abs(risk - 100.0 * p) > 1e-8:
                raise RuntimeError(f"Risk percent mismatch on output line {line_no}")
            score = row.get("alert_policy_score")
            expected_crossed = bool(
                score is not None and math.isfinite(float(score)) and float(score) >= threshold
            )
            if bool(row["threshold_crossed"]) != expected_crossed:
                raise RuntimeError(f"Threshold decision mismatch on output line {line_no}")
            expected_warning = expected_crossed and (
                str(row["station_id"]) != str(row["final_inspection_station"])
            )
            if bool(row["warning"]) != expected_warning:
                raise RuntimeError(f"Warning decision mismatch on output line {line_no}")

            warning = bool(row["warning"])
            has_explanation = bool(row.get("explanation_available"))
            if warning:
                warnings += 1
            if has_explanation:
                explained += 1
                err = row.get("shap_probability_reconstruction_error")
                if err is None or not math.isfinite(float(err)) or float(err) > 1e-10:
                    raise RuntimeError(f"Invalid CatBoost SHAP reconstruction on line {line_no}")
                max_shap_error = max(max_shap_error, float(err))
            if explain_mode == "all" and not has_explanation:
                raise RuntimeError(f"Missing requested SHAP explanation on line {line_no}")
            if explain_mode == "warnings" and warning and not has_explanation:
                raise RuntimeError(f"Warning without SHAP explanation on line {line_no}")
            max_risk = max(max_risk, p)

    if rows == 0:
        raise RuntimeError("Live defect pipeline produced zero predictions")
    return {
        "predictions": rows,
        "warnings": warnings,
        "explained": explained,
        "max_defect_probability": max_risk,
        "max_shap_reconstruction_error": max_shap_error,
    }


def run_live(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    poll_s = max(0.01, float(args.poll_ms) / 1000.0)
    files = _wait_for_inputs(run_dir, args.wait_seconds, poll_s)
    contract = _resolve_model(args.model_id, args.artifact_root, files["stations"])
    artifact_dwell = contract.get("historical_dwell")
    artifact_residence = contract.get("corridor_residence")
    history = [] if artifact_dwell is not None else _history_runs(
        Path(args.history_root).expanduser().resolve(), run_dir
    )
    dark_adapter = DefectDarkZoneAdapter(
        stations_csv=files["stations"],
        dz_csv=files["dz"],
        units_csv=files["units"],
        history_runs=history,
        runtime_dir=ROOT / ".runtime" / "dark_zone",
        dark_zone_dir=args.dark_zone_dir,
        historical_dwell_csv=artifact_dwell,
        corridor_residence_csv=artifact_residence,
        run_id=args.run_id,
        corridor_particles=args.particles,
        transition_confidence=args.dark_transition_confidence,
        sensor_assignment_confidence=args.sensor_assignment_confidence,
    )

    pipeline = build_pipeline(
        stations_csv=files["stations"],
        units_csv=files["units"],
        model_artifact_path=contract["model"],
        config_path=contract["config"],
        calibrator_path=contract["calibrator"],
        run_id=args.run_id,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
        dark_adapter=dark_adapter,
    )

    progress_map = checkpoint_progress_map(files["station_checkpoints"])
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    print("\n" + "=" * 72)
    print("LIVE DEFECT CONSUMER")
    print("=" * 72)
    print(f"Simulator folder : {run_dir}")
    print(f"Defect model     : {contract['id']}")
    print(f"Explain mode     : {args.explain_mode}")
    print(f"DARK stations    : {', '.join(sorted(dark_adapter.dark_station_ids)) if dark_adapter.dark_station_ids else 'NONE'}")
    print(f"DARK particles   : {args.particles}")
    print(
        "DARK calibration : "
        + ("selected factory artifact" if artifact_dwell is not None else f"prior-history only ({len(history)} run(s))")
    )
    print("Ground truth     : inspection_results.csv is NOT consumed")
    print("Simulator process: external (defect consumer does NOT launch it)")

    records = evidence_records = predictions = 0
    expected_sequence = 1
    completion_seen_at: float | None = None

    with files["bus"].open("r", encoding="utf-8", newline="") as handle:
        header_line = handle.readline()
        if not header_line:
            raise RuntimeError("runtime_events.csv exists but has no header")
        header = next(csv.reader([header_line]))
        missing = REQUIRED_BUS_COLUMNS - set(header)
        if missing:
            raise RuntimeError(
                "Simulator runtime_events.csv is too old for live defect inference; missing: "
                + ", ".join(sorted(missing))
            )

        while True:
            burst: list[dict[str, str]] = []
            while len(burst) < max(1, int(args.live_batch_size)):
                position = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith("\n"):
                    handle.seek(position)
                    break
                burst.append(next(csv.DictReader([line], fieldnames=header)))

            if burst:
                completion_seen_at = None
                pipeline.refresh_units(files["units"])
                for row in burst:
                    seq = int(row["sequence"])
                    if seq != expected_sequence:
                        raise RuntimeError(
                            f"Public runtime bus sequence gap/reorder: expected {expected_sequence}, got {seq}"
                        )
                    expected_sequence += 1
                    record = runtime_row_to_record(row, progress_map)
                    records += 1
                    if record is None:
                        continue
                    if record.get("stream") == "evidence":
                        evidence_records += 1
                    batch = pipeline.process_record(record)
                    if batch:
                        predictions += append_jsonl(output, batch)
                continue

            if (run_dir / "run_metadata.json").is_file():
                if completion_seen_at is None:
                    completion_seen_at = time.monotonic()
                elif time.monotonic() - completion_seen_at >= max(0.2, 2 * poll_s):
                    break
            time.sleep(poll_s)

    summary = _validate_output(output, explain_mode=args.explain_mode)
    print("\nLIVE DEFECT VALIDATION: PASS")
    print(f"Public records       : {records}")
    print(f"DARK evidence        : {evidence_records} consumed by defect PF mirror")
    print(f"Predictions          : {predictions}")
    print(f"Warnings             : {summary['warnings']}")
    print(f"SHAP explanations    : {summary['explained']}")
    print(f"Output               : {output}")
    print("Inspection/ground-truth leakage: NONE")
    return 0



def _pace_delay_seconds(
    timestamp_ms: int, delivered_timestamp_ms: int | None, mult: float
) -> float:
    """Wall-clock delay before delivering an event paced at ``mult``x simulated speed.

    The same delivery-timing formula as the bottleneck consumer's replay pacing (itself
    matching ``main.py``'s ``replay_command``): proportional to the gap between this
    event's ``timestamp_ms`` and the last delivered one, scaled by ``1 / mult``. Zero
    before any event has been delivered, and never negative since causal order already
    guarantees ``timestamp_ms`` is non-decreasing.
    """
    if delivered_timestamp_ms is None:
        return 0.0
    return max(0, timestamp_ms - delivered_timestamp_ms) / (1000.0 * mult)


def run_replay(args: argparse.Namespace) -> int:
    """Replay a completed run's public bus through the defect pipeline.

    ``--pace``/``--mult`` mirror the bottleneck consumer's replay pacing (itself the
    same delivery-timing mechanism as the bottleneck-only ``main.py`` replay path): a
    delay is slept between events proportional to the gap between their
    ``timestamp_ms`` values, scaled by ``1 / mult``, so this consumer advances through
    simulated time in step with its bottleneck sibling on the same run.
    """
    if args.pace and args.mult <= 0:
        raise ValueError("--mult must be positive when --pace is enabled")
    run_dir = Path(args.run_dir).expanduser().resolve()
    required = {
        "stations": run_dir / "stations.csv",
        "units": run_dir / "units.csv",
        "bus": run_dir / "runtime_events.csv",
        "dz": run_dir / "dz.csv",
        "station_checkpoints": run_dir / "station_checkpoints.csv",
        "metadata": run_dir / "run_metadata.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Completed defect replay requires simulator-v2.1 files; missing: {', '.join(missing)}"
        )
    contract = _resolve_model(args.model_id, args.artifact_root, required["stations"])
    artifact_dwell = contract.get("historical_dwell")
    artifact_residence = contract.get("corridor_residence")
    history = [] if artifact_dwell is not None else _history_runs(
        Path(args.history_root).expanduser().resolve(), run_dir
    )
    dark_adapter = DefectDarkZoneAdapter(
        stations_csv=required["stations"],
        dz_csv=required["dz"],
        units_csv=required["units"],
        history_runs=history,
        runtime_dir=ROOT / ".runtime" / "dark_zone_replay",
        dark_zone_dir=args.dark_zone_dir,
        historical_dwell_csv=artifact_dwell,
        corridor_residence_csv=artifact_residence,
        run_id=args.run_id or run_dir.name,
        corridor_particles=args.particles,
        transition_confidence=args.dark_transition_confidence,
        sensor_assignment_confidence=args.sensor_assignment_confidence,
    )
    pipeline = build_pipeline(
        stations_csv=required["stations"],
        units_csv=required["units"],
        model_artifact_path=contract["model"],
        config_path=contract["config"],
        calibrator_path=contract["calibrator"],
        run_id=args.run_id or run_dir.name,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
        dark_adapter=dark_adapter,
    )
    progress_map = checkpoint_progress_map(required["station_checkpoints"])
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    records = evidence_records = predictions = 0
    expected_sequence = 1
    delivered_timestamp_ms: int | None = None
    with required["bus"].open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_bus = REQUIRED_BUS_COLUMNS - set(reader.fieldnames or [])
        if missing_bus:
            raise RuntimeError(
                "Simulator runtime_events.csv is too old for defect replay; missing: "
                + ", ".join(sorted(missing_bus))
            )
        for row in reader:
            seq = int(row["sequence"])
            if seq != expected_sequence:
                raise RuntimeError(
                    f"Public runtime bus sequence gap/reorder: expected {expected_sequence}, got {seq}"
                )
            expected_sequence += 1
            timestamp_ms = int(row["timestamp_ms"])
            if args.pace:
                delay_seconds = _pace_delay_seconds(timestamp_ms, delivered_timestamp_ms, args.mult)
                if delay_seconds:
                    time.sleep(delay_seconds)
            delivered_timestamp_ms = timestamp_ms
            record = runtime_row_to_record(row, progress_map)
            records += 1
            if record is None:
                continue
            if record.get("stream") == "evidence":
                evidence_records += 1
            batch = pipeline.process_record(record)
            if batch:
                predictions += append_jsonl(output, batch)

    summary = _validate_output(output, explain_mode=args.explain_mode)
    print("\nDEFECT PRESCRIBED REPLAY: PASS")
    print(f"Public records       : {records}")
    print(f"DARK evidence        : {evidence_records}")
    print(f"Predictions          : {predictions}")
    print(f"Warnings             : {summary['warnings']}")
    print(f"SHAP explanations    : {summary['explained']}")
    print(f"Model                : {contract['id']}")
    print(
        "DARK calibration     : "
        + ("selected factory artifact" if artifact_dwell is not None else f"prior-history only ({len(history)} run(s))")
    )
    print("Inspection leakage   : NONE")
    print(f"Output               : {output}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run V5 defect prediction from the simulator public bus")
    p.add_argument("--mode", choices=("live", "replay"), default="live")
    p.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--run-id", default="CURRENT_RUN")
    p.add_argument("--model-id")
    p.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    p.add_argument("--history-root", type=Path, default=DEFAULT_HISTORY_ROOT)
    p.add_argument("--dark-zone-dir", type=Path, default=DEFAULT_DARK_ZONE_DIR)
    p.add_argument("--particles", type=int, default=3000)
    p.add_argument("--dark-transition-confidence", type=float, default=0.55)
    p.add_argument("--sensor-assignment-confidence", type=float, default=0.55)
    p.add_argument("--explain-mode", choices=("off", "warnings", "all"), default="warnings")
    p.add_argument("--shap-top-k", type=int, default=3)
    p.add_argument("--wait-seconds", type=float, default=120.0)
    p.add_argument("--poll-ms", type=float, default=50.0)
    p.add_argument("--live-batch-size", type=int, default=256)
    p.add_argument(
        "--pace", action="store_true",
        help="Replay mode only: deliver events against wall-clock time at --mult "
             "instead of as fast as possible.",
    )
    p.add_argument(
        "--mult", type=float, default=1.0,
        help="Simulation-time to event-delivery multiplier when --pace is enabled.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return run_replay(args) if args.mode == "replay" else run_live(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
