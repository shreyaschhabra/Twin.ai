"""Interactive one-click runner for the final bottleneck prediction pipeline.

Deployment contract
-------------------
1. The simulator runs independently and writes ``data/input/current_run/``.
2. ``runtime_events.csv`` is its ordered public event bus. Bottlenecks consume station + RFID/power records and ignore defect-only SENSOR/MANUAL records.
3. ``run_current.py`` starts ONLY the bottleneck consumer and tails that bus.
4. DARK topology comes from simulator ``dz.csv``; no manual DARK prompt exists.
5. Calibration is built ONLY from prior completed history.

No calibration is learned from ``current_run`` in this launcher.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
CURRENT_RUN = ROOT / "data" / "input" / "current_run"
HISTORY_ROOT = ROOT / "data" / "calibration" / "history"
GENERATED_CALIBRATION = ROOT / "data" / "calibration" / "generated"
CONFIGURED_STATIONS = ROOT / "data" / "input" / "configured_stations.csv"
DEFAULT_OUTPUT = ROOT / "data" / "output" / "predictions.jsonl"
STATION_CHECKPOINTS = ROOT / "config" / "station_checkpoints.csv"
DARK_ZONE_DIR = ROOT / "dark_zone"
RUNTIME_BUS_REQUIRED_COLUMNS = {"sequence", "timestamp_ms", "record_type", "station_id", "event_type"}


def _run(cmd: list[str]) -> None:
    print("\n>", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=ROOT)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}")


def _required_current_files(run_dir: Path = CURRENT_RUN) -> dict[str, Path]:
    run_dir = Path(run_dir).expanduser().resolve()
    files = {
        "stations.csv": run_dir / "stations.csv",
        "units.csv": run_dir / "units.csv",
        "station_events.csv": run_dir / "station_events.csv",
        "dz.csv": run_dir / "dz.csv",
        "run_metadata.json": run_dir / "run_metadata.json",
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Simulator input is incomplete in {run_dir}. Missing: "
            + ", ".join(missing)
        )
    return files


def _validate_input_schema(files: dict[str, Path]) -> pd.DataFrame:
    stations = pd.read_csv(files["stations.csv"])
    units = pd.read_csv(files["units.csv"])
    events = pd.read_csv(files["station_events.csv"], nrows=20)

    station_required = {"station_id"}
    unit_required = {"unit_id", "vehicle_model"}
    event_required = {"timestamp_ms", "station_id", "unit_id", "event_type"}

    for name, frame, required in (
        ("stations.csv", stations, station_required),
        ("units.csv", units, unit_required),
        ("station_events.csv", events, event_required),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{name} missing required columns: {sorted(missing)}")

    stations = stations.copy()
    stations["station_id"] = stations["station_id"].astype(str).str.strip()
    if stations["station_id"].duplicated().any():
        dup = stations.loc[stations["station_id"].duplicated(), "station_id"].tolist()
        raise ValueError(f"Duplicate station IDs in stations.csv: {dup}")
    return stations


def _parse_dark_stations(raw: str, available: list[str]) -> list[str]:
    requested = []
    seen = set()
    for token in str(raw).split(","):
        sid = token.strip()
        if not sid or sid in seen:
            continue
        requested.append(sid)
        seen.add(sid)
    invalid = sorted(set(requested) - set(available))
    if invalid:
        raise ValueError(
            "Invalid DARK station(s): "
            + ", ".join(invalid)
            + ". Available: "
            + ", ".join(available)
        )
    return requested


def _history_runs() -> list[Path]:
    if not HISTORY_ROOT.is_dir():
        return []
    runs = []
    for p in sorted(HISTORY_ROOT.iterdir()):
        if not p.is_dir():
            continue
        if all((p / name).is_file() for name in ("stations.csv", "units.csv", "station_events.csv")):
            runs.append(p)
    return runs


def _build_prior_calibration(dark_stations: list[str]) -> tuple[Path | None, Path | None, dict]:
    """Build DARK calibration strictly from prior completed history.

    This delegates to the same boundary-aware implementation used by factory
    artifacts, so simulator v2.1 history remains causal even though internal
    DARK processing events are intentionally hidden.
    """
    if not dark_stations:
        return None, None, {"history_runs": [], "corridors": []}

    runs = _history_runs()
    if not runs:
        raise FileNotFoundError(
            "DARK stations are configured but no prior calibration runs exist under "
            "data/calibration/history/. Current-run data is never used for calibration."
        )

    from factory_models import build_dark_calibration_files

    GENERATED_CALIBRATION.mkdir(parents=True, exist_ok=True)
    dwell, residence, meta = build_dark_calibration_files(
        runs,
        CONFIGURED_STATIONS,
        GENERATED_CALIBRATION,
        dark_station_ids=set(dark_stations),
    )
    metadata = {
        **meta,
        "history_runs": [p.name for p in runs],
        "dark_stations": list(dark_stations),
        "causality": (
            "Calibration source is data/calibration/history only; current_run is excluded. "
            "Hidden DARK intervals use only observable entry/exit boundaries."
        ),
    }
    (GENERATED_CALIBRATION / "calibration_manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return dwell, residence, metadata


def _validate_output(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Prediction output was not created: {path}")
    required = {
        "schema_version",
        "timestamp_ms",
        "station_id",
        "route",
        "bottleneck_probability",
        "warning",
        "decision_threshold",
    }
    routes = Counter()
    triggers = Counter()
    invalid_probabilities = 0
    unknown_categories = 0
    s01_predictions = 0
    missing_explanations = 0
    bad_shap_additivity = 0
    max_shap_additivity_error = 0.0
    rows = 0

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            rows += 1
            missing = required - set(row)
            if missing:
                raise RuntimeError(f"Output line {line_no} missing fields: {sorted(missing)}")
            p = row.get("bottleneck_probability")
            if not isinstance(p, (int, float)) or not math.isfinite(float(p)) or not (0 <= float(p) <= 1):
                invalid_probabilities += 1
            routes[str(row.get("route"))] += 1
            triggers[str(row.get("prediction_trigger"))] += 1
            if str(row.get("station_id")) == "S01":
                s01_predictions += 1
            diagnostics = row.get("diagnostics") or {}
            if diagnostics.get("unknown_categories"):
                unknown_categories += 1
            explanation = row.get("explanation") or {}
            top_drivers = explanation.get("top_drivers")
            additivity = explanation.get("probability_additivity_error")
            if not isinstance(top_drivers, list) or not top_drivers or additivity is None:
                missing_explanations += 1
            else:
                try:
                    err = float(additivity)
                except (TypeError, ValueError):
                    bad_shap_additivity += 1
                else:
                    if not math.isfinite(err) or err > 1e-5:
                        bad_shap_additivity += 1
                    elif err > max_shap_additivity_error:
                        max_shap_additivity_error = err

    if rows == 0:
        raise RuntimeError("Pipeline produced zero predictions")
    if invalid_probabilities:
        raise RuntimeError(f"Found {invalid_probabilities} invalid probabilities")
    if unknown_categories:
        raise RuntimeError(f"Found {unknown_categories} unknown model-category outputs")
    if s01_predictions:
        raise RuntimeError(f"Found {s01_predictions} invalid S01 predictions")
    if missing_explanations:
        raise RuntimeError(f"Found {missing_explanations} predictions without TreeSHAP explanations")
    if bad_shap_additivity:
        raise RuntimeError(
            f"Found {bad_shap_additivity} TreeSHAP explanations with invalid additivity"
        )

    return {
        "predictions": rows,
        "routes": dict(routes),
        "triggers": dict(triggers),
        "invalid_probabilities": invalid_probabilities,
        "unknown_categories": unknown_categories,
        "s01_predictions": s01_predictions,
        "missing_explanations": missing_explanations,
        "bad_shap_additivity": bad_shap_additivity,
        "max_shap_additivity_error": max_shap_additivity_error,
    }


def _configure_from_simulator_topology(files: dict[str, Path]) -> list[str]:
    from config.configure_stations import configure_from_dz
    configured, dark = configure_from_dz(files["stations.csv"], files["dz.csv"])
    CONFIGURED_STATIONS.parent.mkdir(parents=True, exist_ok=True)
    configured.to_csv(CONFIGURED_STATIONS, index=False)
    return configured.loc[
        configured["sensor_coverage"].astype(str).str.upper().eq("NONE"), "station_id"
    ].astype(str).tolist()


def _resolve_runtime_contract(
    files: dict[str, Path],
    *,
    model_id: str | None,
    artifact_root: str | Path,
) -> dict:
    """Resolve BASE or selected factory artifact without mutating either one.

    BASE uses the current simulator run's authoritative ``dz.csv`` plus prior-only
    calibration history. A factory artifact carries its own immutable topology and
    calibration; the current simulator run must match that contract exactly.
    """
    from factory_models import BASE_MODEL_ID, model_paths, selected_model_id
    from config.configure_stations import validate_runtime_topology_match

    store = Path(artifact_root).expanduser().resolve()
    chosen = str(model_id or selected_model_id(store))
    paths = model_paths(chosen, store)

    if chosen == BASE_MODEL_ID:
        dark_stations = _configure_from_simulator_topology(files)
        dwell, residence, calibration = _build_prior_calibration(dark_stations)
        return {
            "model_id": chosen,
            "configured_stations": CONFIGURED_STATIONS,
            "model_bundle": paths["bundle"],
            "historical_dwell": dwell,
            "corridor_residence": residence,
            "calibration": calibration,
            "dark_stations": dark_stations,
        }

    current, current_dark = validate_runtime_topology_match(
        paths["configured_stations"], files["stations.csv"], files["dz.csv"]
    )
    expected_dark = current.loc[
        current["sensor_coverage"].astype(str).str.upper().eq("NONE"), "station_id"
    ].astype(str).tolist()
    calibration = {
        "source": "selected_factory_artifact",
        "model_id": chosen,
        "current_run_excluded": True,
    }
    return {
        "model_id": chosen,
        "configured_stations": paths["configured_stations"],
        "model_bundle": paths["model_bundle"],
        "historical_dwell": paths.get("historical_dwell"),
        "corridor_residence": paths.get("corridor_residence"),
        "calibration": calibration,
        "dark_stations": expected_dark or sorted(current_dark),
    }


def _wait_for_live_inputs(run_dir: Path, timeout_s: float, poll_s: float) -> dict[str, Path]:
    run_dir = Path(run_dir).expanduser().resolve()
    required = {
        "stations.csv": run_dir / "stations.csv",
        "dz.csv": run_dir / "dz.csv",
        "units.csv": run_dir / "units.csv",
        "runtime_events.csv": run_dir / "runtime_events.csv",
        "station_checkpoints.csv": run_dir / "station_checkpoints.csv",
    }
    deadline = time.monotonic() + float(timeout_s)
    while True:
        missing = [name for name, path in required.items() if not path.is_file()]
        if not missing:
            return required
        if time.monotonic() >= deadline:
            raise FileNotFoundError(
                "Timed out waiting for simulator live files: " + ", ".join(missing)
            )
        time.sleep(poll_s)


def _checkpoint_progress_map(path: Path) -> dict[tuple[str, str], float]:
    frame = pd.read_csv(path)
    return {
        (str(r.station_id), str(r.checkpoint_id)): float(r.nominal_progress_fraction)
        for r in frame.itertuples(index=False)
    }


def _clean_csv_value(value: str | None):
    if value is None or value == "":
        return None
    return value


def _runtime_row_to_event(row: dict[str, str], progress_map: dict[tuple[str, str], float]) -> tuple[str, dict]:
    kind = str(row.get("record_type", "")).upper()
    if kind in {"SENSOR", "MANUAL"}:
        # Public observations for the parallel defect consumer. They are part of
        # the shared ordered bus but do not alter bottleneck state.
        return "ignore", {}
    base = {
        "timestamp_ms": int(row["timestamp_ms"]),
        "station_id": str(row["station_id"]),
        "unit_id": _clean_csv_value(row.get("unit_id")),
        "event_type": str(row["event_type"]).upper(),
        "event_id": _clean_csv_value(row.get("event_id")),
        "event_sequence": int(row["sequence"]),
    }
    if kind == "STATION":
        for name in ("queue_length_after", "cycle_time_ms"):
            value = _clean_csv_value(row.get(name))
            base[name] = float(value) if value is not None else None
        base["previous_state"] = _clean_csv_value(row.get("previous_state"))
        base["new_state"] = _clean_csv_value(row.get("new_state"))
        base["dark_zone_id"] = _clean_csv_value(row.get("dark_zone_id"))
        return "station", base
    if kind == "EVIDENCE":
        checkpoint_id = str(row.get("checkpoint_id", ""))
        key = (base["station_id"], checkpoint_id)
        if key not in progress_map:
            raise ValueError(f"No checkpoint progress definition for {key}")
        base["checkpoint_progress"] = float(progress_map[key])
        return "evidence", base
    raise ValueError(f"Unknown runtime_events.csv record_type: {kind!r}")


def _write_live_predictions(output: Path, predictions) -> int:
    from output.prediction_output import append_jsonl
    return append_jsonl(output, predictions, include_diagnostics=True)


def _run_live(args: argparse.Namespace) -> int:
    poll_s = max(float(args.poll_ms) / 1000.0, 0.01)
    run_dir = Path(args.run_dir).expanduser().resolve()
    files = _wait_for_live_inputs(run_dir, args.wait_seconds, poll_s)
    contract = _resolve_runtime_contract(
        files, model_id=args.model_id, artifact_root=args.artifact_root
    )
    dark_stations = list(contract["dark_stations"])
    calibration_meta = contract["calibration"]

    from main import build_pipeline
    pipeline = build_pipeline(
        configured_stations_csv=contract["configured_stations"],
        units_csv=files["units.csv"],
        historical_dwell_csv=contract["historical_dwell"],
        corridor_residence_csv=contract["corridor_residence"],
        dark_zone_dir=DARK_ZONE_DIR,
        model_bundle_path=contract["model_bundle"],
        run_id=args.run_id,
        corridor_particles=args.particles,
    )
    progress_map = _checkpoint_progress_map(files["station_checkpoints.csv"])
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    print("\n" + "=" * 72)
    print("LIVE BOTTLENECK CONSUMER")
    print("=" * 72)
    try:
        shown_run = run_dir.relative_to(ROOT)
    except ValueError:
        shown_run = run_dir
    print(f"Simulator folder : {shown_run}")
    print(f"Model             : {contract['model_id']}")
    print(f"DARK stations    : {', '.join(dark_stations) if dark_stations else 'NONE'}")
    print(f"Calibration      : {calibration_meta.get('source', calibration_meta.get('history_runs', []))}")
    print(f"Particles        : {args.particles}")
    print("Simulator process: external (run_current.py does NOT launch it)")

    predictions_written = 0
    records = 0
    completion_seen_at: float | None = None
    with files["runtime_events.csv"].open("r", encoding="utf-8", newline="") as handle:
        header_line = handle.readline()
        if not header_line:
            raise RuntimeError("runtime_events.csv exists but has no header")
        header = next(csv.reader([header_line]))
        missing_header = RUNTIME_BUS_REQUIRED_COLUMNS - set(header)
        if missing_header:
            raise RuntimeError(
                "Simulator runtime_events.csv is too old for bottleneck live mode; missing: "
                + ", ".join(sorted(missing_header))
            )
        expected_sequence = 1
        while True:
            batch_rows: list[dict[str, str]] = []
            while len(batch_rows) < max(1, int(args.live_batch_size)):
                position = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith("\n"):
                    # The simulator may be in the middle of flushing a CSV row.
                    # Rewind and retry instead of parsing a torn live record.
                    handle.seek(position)
                    break
                batch_rows.append(next(csv.DictReader([line], fieldnames=header)))

            if batch_rows:
                completion_seen_at = None
                # Units are appended before their first station event; refresh once
                # per visible burst so DARK variant priors stay current.
                pipeline.controller.refresh_units(files["units.csv"])
                packets = []
                for row in batch_rows:
                    seq = int(row["sequence"])
                    if seq != expected_sequence:
                        raise RuntimeError(
                            f"Public runtime bus sequence gap/reorder: expected {expected_sequence}, got {seq}"
                        )
                    expected_sequence += 1
                    kind, event = _runtime_row_to_event(row, progress_map)
                    records += 1
                    if kind == "ignore":
                        continue
                    if kind == "evidence":
                        packets.extend(pipeline.route_evidence_event(event))
                    else:
                        packets.extend(pipeline.route_event(event))
                predictions_written += _write_live_predictions(output, pipeline.score_packets(packets))
                continue

            if (run_dir / "run_metadata.json").is_file():
                if completion_seen_at is None:
                    completion_seen_at = time.monotonic()
                elif time.monotonic() - completion_seen_at >= max(0.2, 2 * poll_s):
                    break
            time.sleep(poll_s)

    summary = _validate_output(output)
    print("\nLIVE PIPELINE VALIDATION: PASS")
    print(f"Runtime records      : {records}")
    print(f"Predictions          : {predictions_written}")
    print(f"Routes               : {summary['routes']}")
    print(f"Unknown categories   : {summary['unknown_categories']}")
    print(f"Output               : {output}")
    print("Current-run calibration leakage: NONE (prior history only).")
    return 0


def _pace_delay_seconds(
    timestamp_ms: int, delivered_timestamp_ms: int | None, mult: float
) -> float:
    """Wall-clock delay before delivering an event paced at ``mult``x simulated speed.

    The same delivery-timing formula as ``main.py``'s ``replay_command``: proportional
    to the gap between this event's ``timestamp_ms`` and the last delivered one, scaled
    by ``1 / mult``. Zero before any event has been delivered -- there is nothing yet to
    delay against -- and never negative, since causal order already guarantees
    ``timestamp_ms`` is non-decreasing.
    """
    if delivered_timestamp_ms is None:
        return 0.0
    return max(0, timestamp_ms - delivered_timestamp_ms) / (1000.0 * mult)


def _run_completed_replay(args: argparse.Namespace) -> int:
    """Replay the exact simulator public bus used by live mode.

    This intentionally avoids the legacy station_events/manual/checkpoint merge so
    completed replay and live deployment see identical observable information.

    ``--pace``/``--mult`` reuse the same delivery-timing mechanism as the
    bottleneck-only replay path (``main.py``'s ``replay_command``): a delay is slept
    between events proportional to the gap between their ``timestamp_ms`` values,
    scaled by ``1 / mult``, so simulated time advances at roughly ``mult`` times
    wall-clock speed while the causal event order is unchanged.
    """
    if args.pace and args.mult <= 0:
        raise ValueError("--mult must be positive when --pace is enabled")
    run_dir = Path(args.run_dir).expanduser().resolve()
    files = _required_current_files(run_dir)
    files["runtime_events.csv"] = run_dir / "runtime_events.csv"
    files["station_checkpoints.csv"] = run_dir / "station_checkpoints.csv"
    missing_public = [
        name for name in ("runtime_events.csv", "station_checkpoints.csv")
        if not files[name].is_file()
    ]
    if missing_public:
        raise FileNotFoundError(
            "Completed bottleneck replay requires simulator-v2.1 public-bus files: "
            + ", ".join(missing_public)
        )
    _validate_input_schema(files)
    contract = _resolve_runtime_contract(
        files, model_id=args.model_id, artifact_root=args.artifact_root
    )

    from main import build_pipeline
    pipeline = build_pipeline(
        configured_stations_csv=contract["configured_stations"],
        units_csv=files["units.csv"],
        historical_dwell_csv=contract["historical_dwell"],
        corridor_residence_csv=contract["corridor_residence"],
        dark_zone_dir=DARK_ZONE_DIR,
        model_bundle_path=contract["model_bundle"],
        run_id=args.run_id,
        corridor_particles=args.particles,
    )
    progress_map = _checkpoint_progress_map(files["station_checkpoints.csv"])
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    records = evidence_records = predictions_written = 0
    expected_sequence = 1
    packets = []
    # Paced replay keeps immediate emission semantics -- like main.py's replay_command,
    # a large batch would hold predictions back until `batch_limit` events had already
    # been slept through, which would defeat live viewing of a paced run.
    batch_limit = 1 if args.pace else max(1, int(args.live_batch_size))
    delivered_timestamp_ms: int | None = None
    with files["runtime_events.csv"].open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_header = RUNTIME_BUS_REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_header:
            raise RuntimeError(
                "Simulator runtime_events.csv is too old for bottleneck replay; missing: "
                + ", ".join(sorted(missing_header))
            )
        pipeline.controller.refresh_units(files["units.csv"])
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
            kind, event = _runtime_row_to_event(row, progress_map)
            records += 1
            if kind == "ignore":
                continue
            if kind == "evidence":
                evidence_records += 1
                packets.extend(pipeline.route_evidence_event(event))
            else:
                packets.extend(pipeline.route_event(event))
            if len(packets) >= batch_limit:
                predictions_written += _write_live_predictions(
                    output, pipeline.score_packets(packets)
                )
                packets = []
        if packets:
            predictions_written += _write_live_predictions(
                output, pipeline.score_packets(packets)
            )

    summary = _validate_output(output)
    print("\nBOTTLENECK PRESCRIBED REPLAY: PASS")
    print(f"Public records       : {records}")
    print(f"DARK evidence        : {evidence_records}")
    print(f"Predictions          : {predictions_written}")
    print(f"Routes               : {summary['routes']}")
    print(f"Model                : {contract['model_id']}")
    print(f"Output               : {output}")
    print("Current-run calibration leakage: NONE (prior history or selected artifact only).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the bottleneck consumer for data/input/current_run/."
    )
    parser.add_argument("--mode", choices=("live", "replay"), default="live",
                        help="live tails simulator runtime_events.csv; replay processes a completed run")
    parser.add_argument("--run-dir", type=Path, default=CURRENT_RUN,
                        help="Simulator run directory. Live mode may start before the simulator creates its files.")
    parser.add_argument("--particles", type=int, default=3000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", default="CURRENT_RUN")
    parser.add_argument(
        "--model-id", default=None,
        help="Model artifact to use; defaults to the repository's selected model pointer",
    )
    parser.add_argument(
        "--artifact-root", type=Path, default=ROOT / "factory_models",
        help="Factory model artifact store used for model selection",
    )
    parser.add_argument("--wait-seconds", type=float, default=120.0,
                        help="How long live mode waits for the simulator to create its public files")
    parser.add_argument("--poll-ms", type=float, default=50.0)
    parser.add_argument("--live-batch-size", type=int, default=128,
                        help="Maximum public runtime records routed before one batched XGBoost/SHAP call")
    parser.add_argument(
        "--pace", action="store_true",
        help="Replay mode only: deliver events against wall-clock time at --mult "
             "instead of as fast as possible.",
    )
    parser.add_argument(
        "--mult", type=float, default=1.0,
        help="Simulation-time to event-delivery multiplier when --pace is enabled.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return _run_live(args) if args.mode == "live" else _run_completed_replay(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
