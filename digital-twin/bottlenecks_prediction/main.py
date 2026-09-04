"""Single entry point for the Digital Twin bottleneck backend.

Commands
--------
configure
    Create a configured station CSV with LIGHT=NORMAL and DARK=NONE.

replay
    Replay a completed ``station_events.csv`` through the exact runtime pipeline:
    event -> Light/Dark controller -> 28 features -> XGBoost -> dashboard output.
    With ``--run-dir`` it also auto-discovers manual/checkpoint configuration,
    auto-builds replay dwell/corridor-residence calibration when explicit
    historical files are not supplied, and merges optional Dark evidence into
    the causal event timeline.

live
    Read one JSON station event per line from stdin (or a JSONL file), process it
    through the same persistent runtime pipeline, and emit dashboard-ready JSON.

The upstream engineer does not need to call Light Zone, Dark Zone, or XGBoost
modules directly.  For an application integration they may also import
``build_pipeline`` from this module and call ``pipeline.process_event(event)``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, TextIO

import pandas as pd

# Support both:
#   python main.py ...
# and imports when digital_twin is on PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.configure_stations import (  # noqa: E402
    configure_sensor_coverage,
    load_and_configure_stations,
    print_configuration,
)
from output.prediction_output import format_prediction  # noqa: E402
from runtime.digital_twin_pipeline import DigitalTwinBottleneckPipeline  # noqa: E402


DEFAULT_DARK_ZONE_DIR = PROJECT_ROOT / "dark_zone"
DEFAULT_MODEL_BUNDLE = (
    PROJECT_ROOT
    / "ml"
    / "bottleneck_model"
    / "bottleneck_model_artifacts"
    / "bottleneck_model_bundle.joblib"
)
DEFAULT_CONFIGURED_STATIONS = PROJECT_ROOT / "data" / "input" / "configured_stations.csv"
DEFAULT_OUTPUT_JSONL = PROJECT_ROOT / "data" / "output" / "predictions.jsonl"
DEFAULT_GENERATED_DIR = PROJECT_ROOT / "data" / "output" / "generated"


def _existing_file(path: str | Path, label: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"{label} not found: {p}")
    return p


def _existing_dir(path: str | Path, label: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"{label} directory not found: {p}")
    return p


def _optional_existing_file(path: Optional[str | Path], label: str) -> Optional[Path]:
    if path is None:
        return None
    return _existing_file(path, label)


def build_pipeline(
    *,
    configured_stations_csv: str | Path,
    units_csv: str | Path,
    historical_dwell_csv: Optional[str | Path] = None,
    corridor_residence_csv: Optional[str | Path] = None,
    dark_zone_dir: str | Path = DEFAULT_DARK_ZONE_DIR,
    model_bundle_path: str | Path = DEFAULT_MODEL_BUNDLE,
    run_id: str = "LIVE",
    prediction_interval_s: float = 60.0,
    corridor_particles: int = 3000,
    random_seed: Optional[int] = None,
) -> DigitalTwinBottleneckPipeline:
    """Construct the persistent production pipeline once.

    This helper is the recommended integration point for another Python service.
    After construction, feed events in nondecreasing timestamp order using
    ``pipeline.process_event(event)``.  During long periods with no station event,
    call ``pipeline.advance_time(timestamp_ms)`` so Dark PF heartbeats can fire.
    """
    configured = _existing_file(configured_stations_csv, "configured stations CSV")
    units = _existing_file(units_csv, "units.csv")
    dark_dir = _existing_dir(dark_zone_dir, "Dark Zone")
    model = _existing_file(model_bundle_path, "XGBoost model bundle")
    historical = _optional_existing_file(historical_dwell_csv, "historical_dwell.csv")
    corridor = _optional_existing_file(
        corridor_residence_csv, "corridor residence calibration CSV"
    )

    return DigitalTwinBottleneckPipeline(
        configured_stations_csv=configured,
        units_csv=units,
        dark_zone_dir=dark_dir,
        model_bundle_path=model,
        historical_dwell_csv=historical,
        corridor_residence_csv=corridor,
        run_id=run_id,
        prediction_interval_s=prediction_interval_s,
        corridor_particles=corridor_particles,
        random_seed=random_seed,
    )


def _write_payload(handle: TextIO, payload: Mapping[str, Any]) -> None:
    handle.write(json.dumps(dict(payload), ensure_ascii=False, allow_nan=False) + "\n")
    handle.flush()


def _emit_predictions(
    predictions: Iterable[Any],
    *,
    output_handle: Optional[TextIO],
    print_handle: Optional[TextIO],
    include_diagnostics: bool,
) -> int:
    count = 0
    for prediction in predictions:
        payload = format_prediction(
            prediction,
            include_diagnostics=include_diagnostics,
        )
        if output_handle is not None:
            _write_payload(output_handle, payload)
        if print_handle is not None:
            _write_payload(print_handle, payload)
        count += 1
    return count


def configure_command(args: argparse.Namespace) -> int:
    """Create configured_stations.csv without touching the raw station file."""
    raw_path = _existing_file(args.stations, "stations.csv")
    output_path = Path(args.output).expanduser().resolve()

    if args.dark_stations is None:
        configured, dark_stations = load_and_configure_stations(raw_path)
    else:
        stations = pd.read_csv(raw_path)
        if "station_id" not in stations.columns:
            raise ValueError("stations.csv must contain a 'station_id' column")
        stations["station_id"] = stations["station_id"].astype(str).str.strip()
        duplicates = stations.loc[
            stations["station_id"].duplicated(), "station_id"
        ].tolist()
        if duplicates:
            raise ValueError(f"Duplicate station IDs found: {duplicates}")

        available = set(stations["station_id"])
        dark_stations = {
            item.strip()
            for item in str(args.dark_stations).split(",")
            if item.strip()
        }
        invalid = dark_stations - available
        if invalid:
            raise ValueError(
                "Invalid DARK station(s): "
                + ", ".join(sorted(invalid))
                + ". Available stations: "
                + ", ".join(sorted(available))
            )
        configured = configure_sensor_coverage(stations, dark_stations)
        print_configuration(configured, dark_stations)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    configured.to_csv(output_path, index=False)
    print(f"\nConfigured stations written to: {output_path}")
    print(f"Dark stations: {len(dark_stations)}")
    return 0


def _resolve_replay_inputs(args: argparse.Namespace) -> tuple[Path, Path, Optional[Path]]:
    if args.run_dir is not None:
        run_dir = _existing_dir(args.run_dir, "run directory")
        units = run_dir / "units.csv"
        events = run_dir / "station_events.csv"
    else:
        run_dir = None
        if args.units is None or args.events is None:
            raise ValueError(
                "Replay requires either --run-dir, or both --units and --events"
            )
        units = Path(args.units)
        events = Path(args.events)

    return (
        _existing_file(units, "units.csv"),
        _existing_file(events, "station_events.csv"),
        run_dir,
    )


def _load_dark_zone_replay_helpers(dark_zone_dir: str | Path):
    """Import the existing flat Dark-Zone CSV helpers without duplicating them."""
    dark_dir = _existing_dir(dark_zone_dir, "Dark Zone")
    text = str(dark_dir)
    if text not in sys.path:
        sys.path.insert(0, text)

    from csv_adapter import (  # type: ignore
        derive_historical_dwell_csv,
        load_checkpoint_events,
        load_manual_checks_as_andon_events,
    )
    from generate_checkpoint_events import generate_checkpoint_events  # type: ignore
    from build_corridor_residence_calibration import build_one_run as build_corridor_residence_one_run  # type: ignore

    return {
        "derive_historical_dwell_csv": derive_historical_dwell_csv,
        "load_checkpoint_events": load_checkpoint_events,
        "load_manual_checks_as_andon_events": load_manual_checks_as_andon_events,
        "generate_checkpoint_events": generate_checkpoint_events,
        "build_corridor_residence_one_run": build_corridor_residence_one_run,
    }


def _configured_dark_station_ids(configured_stations_csv: str | Path) -> set[str]:
    configured = pd.read_csv(_existing_file(configured_stations_csv, "configured stations CSV"))
    required = {"station_id", "sensor_coverage"}
    missing = required - set(configured.columns)
    if missing:
        raise ValueError(
            "configured stations CSV is missing: " + ", ".join(sorted(missing))
        )
    coverage = configured["sensor_coverage"].astype(str).str.strip().str.upper()
    return set(
        configured.loc[coverage.eq("NONE"), "station_id"].astype(str).str.strip()
    )


def _configured_corridors(configured_stations_csv: str | Path) -> dict[str, Any]:
    """Return runtime corridor definitions from the configured station topology."""
    from runtime.runtime_controller import derive_dark_topology

    configured = pd.read_csv(
        _existing_file(configured_stations_csv, "configured stations CSV")
    )
    _, corridors = derive_dark_topology(configured)
    return corridors


def _generated_replay_dir(run_dir: Optional[Path], events_csv: Path) -> Path:
    name = run_dir.name if run_dir is not None else events_csv.parent.name or "replay"
    out = DEFAULT_GENERATED_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def _prepare_replay_calibration(
    *,
    args: argparse.Namespace,
    units_csv: Path,
    events_csv: Path,
    run_dir: Optional[Path],
    dark_station_ids: set[str],
    helpers: Mapping[str, Any],
) -> Optional[Path]:
    """Resolve or auto-build processing-dwell calibration before Dark PF startup."""
    if not dark_station_ids:
        return None
    if args.historical_dwell is not None:
        return _existing_file(args.historical_dwell, "historical_dwell.csv")

    if not getattr(args, "allow_same_run_calibration", False):
        raise ValueError(
            "DARK replay requires --historical-dwell from PRIOR completed run(s). "
            "Same-run calibration is disabled to preserve causality. "
            "For a non-evaluative demo only, pass --allow-same-run-calibration."
        )

    generated_dir = _generated_replay_dir(run_dir, events_csv)
    output = generated_dir / "historical_dwell.csv"
    print(
        "DEMO MODE: auto-generating same-run dwell calibration "
        f"from station_events.csv -> {output}"
    )
    helpers["derive_historical_dwell_csv"](
        str(events_csv),
        str(units_csv),
        output_csv=str(output),
        dark_zone_station_ids=dark_station_ids,
    )
    return output


def _prepare_replay_corridor_residence(
    *,
    args: argparse.Namespace,
    events_csv: Path,
    run_dir: Optional[Path],
    corridors: Mapping[str, Any],
    helpers: Mapping[str, Any],
) -> Optional[Path]:
    """Resolve or auto-build corridor residence calibration before PF startup.

    Explicit ``--corridor-residence`` always wins. Production/validation replay
    never learns corridor residence from the evaluated run; prior historical dwell
    remains the causal fallback when no prior corridor-residence file is supplied.
    Same-run residence generation is available only behind the explicit
    ``--allow-same-run-calibration`` demo flag. Live mode never auto-generates
    future-dependent calibration.
    """
    if not corridors:
        return None
    if args.corridor_residence is not None:
        return _existing_file(
            args.corridor_residence, "corridor residence calibration CSV"
        )
    if run_dir is None:
        print(
            "No --corridor-residence supplied and replay has no --run-dir; "
            "corridor PF will use its processing-dwell fallback."
        )
        return None
    if not getattr(args, "allow_same_run_calibration", False):
        # A prior historical_dwell file is sufficient for the PF's causal
        # processing-dwell fallback. Do not learn corridor residence from the
        # run currently being evaluated.
        return None

    rows: list[dict[str, Any]] = []
    for corridor in corridors.values():
        rows.extend(
            helpers["build_corridor_residence_one_run"](
                run_dir,
                list(corridor.sequence),
                upstream_station=corridor.upstream_light_station,
            )
        )

    if not rows:
        print(
            "WARNING: Could not auto-build corridor residence calibration; "
            "corridor PF will use its processing-dwell fallback."
        )
        return None

    output = _generated_replay_dir(run_dir, events_csv) / "corridor_residence_calibration.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    print(
        "No --corridor-residence supplied; auto-generated replay corridor "
        f"residence calibration ({len(rows)} rows) -> {output}"
    )
    print(
        "NOTE: same-run corridor residence calibration is for functionality/demo "
        "replay only. Accuracy validation must use prior completed run(s)."
    )
    return output


def _discover_optional_run_file(
    explicit: Optional[str | Path],
    run_dir: Optional[Path],
    filename: str,
) -> Optional[Path]:
    if explicit is not None:
        return _existing_file(explicit, filename)
    if run_dir is None:
        return None
    candidate = run_dir / filename
    return candidate.resolve() if candidate.is_file() else None


def _dark_event_to_runtime_evidence(event: Any) -> dict[str, Any]:
    raw_type = getattr(getattr(event, "event_type", None), "value", "")
    event_type = {
        "rfid_checkpoint": "RFID_CHECKPOINT",
        "power_draw": "POWER_DRAW",
        "andon_scan": "ANDON_SCAN",
    }.get(str(raw_type).lower())
    if event_type is None:
        raise ValueError(f"Unsupported replay evidence event type: {raw_type!r}")

    vehicle_id = getattr(event, "vehicle_id", None)
    missing_vehicle = (
        vehicle_id is None
        or (isinstance(vehicle_id, float) and pd.isna(vehicle_id))
        or not str(vehicle_id).strip()
    )
    # POWER_DRAW is intentionally allowed to be anonymous: the simulator's
    # station-level power checkpoint observes activity without identifying a
    # unit. RFID/Andon remain identity evidence.
    if missing_vehicle and event_type != "POWER_DRAW":
        raise ValueError(f"Replay {event_type} evidence is missing unit_id")

    progress = getattr(event, "checkpoint_progress", None)
    if progress is None or pd.isna(progress):
        raise ValueError("Replay evidence event is missing checkpoint_progress")

    return {
        "timestamp_ms": int(round(float(event.ts) * 1000.0)),
        "station_id": str(event.station_id),
        "unit_id": None if missing_vehicle else str(vehicle_id),
        "event_type": event_type,
        "checkpoint_progress": float(progress),
    }


def _prepare_replay_evidence(
    *,
    args: argparse.Namespace,
    units_csv: Path,
    events_csv: Path,
    run_dir: Optional[Path],
    dark_station_ids: set[str],
    helpers: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Auto-discover/generate Layers 3-5 evidence for CSV replay."""
    if not dark_station_ids or args.no_auto_evidence:
        return []

    manual_checks = _discover_optional_run_file(
        args.manual_checks, run_dir, "manual_checks.csv"
    )
    station_checkpoints = _discover_optional_run_file(
        args.station_checkpoints, run_dir, "station_checkpoints.csv"
    )

    # Simulator schema v2.1 emits the real observable checkpoint stream. Use it
    # directly. Synthetic generation is only a legacy fallback for older runs
    # that have checkpoint definitions but no checkpoint_events.csv.
    checkpoint_events = _discover_optional_run_file(
        args.checkpoint_events, run_dir, "checkpoint_events.csv"
    )
    if checkpoint_events is None and station_checkpoints is not None:
        generated_dir = _generated_replay_dir(run_dir, events_csv)
        checkpoint_events = generated_dir / "checkpoint_events.csv"
        print(
            "No checkpoint_events.csv found; generating legacy checkpoint evidence "
            f"-> {checkpoint_events}"
        )
        helpers["generate_checkpoint_events"](
            station_events_csv=str(events_csv),
            units_csv=str(units_csv),
            station_checkpoints_csv=str(station_checkpoints),
            output_csv=str(checkpoint_events),
            dark_zone_station_ids=dark_station_ids,
        )

    evidence: list[Any] = []
    if manual_checks is not None:
        evidence.extend(
            helpers["load_manual_checks_as_andon_events"](
                str(manual_checks),
                str(units_csv),
                dark_station_ids,
                station_events_csv=str(events_csv),
            )
        )

    if checkpoint_events is not None:
        if station_checkpoints is None:
            raise ValueError(
                "checkpoint_events.csv requires station_checkpoints.csv for "
                "checkpoint_progress mapping"
            )
        evidence.extend(
            helpers["load_checkpoint_events"](
                str(checkpoint_events),
                str(station_checkpoints),
                str(units_csv),
                dark_station_ids,
                station_events_csv=str(events_csv),
            )
        )

    runtime_events = [_dark_event_to_runtime_evidence(e) for e in evidence]
    runtime_events.sort(key=lambda e: int(e["timestamp_ms"]))
    if runtime_events:
        print(
            f"Replay evidence prepared: {len(runtime_events)} event(s) "
            "from manual/checkpoint streams."
        )
    return runtime_events


def _merged_replay_timeline(
    station_events: pd.DataFrame,
    evidence_events: list[dict[str, Any]],
    corridor_upstream_stations: Optional[set[str]] = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Merge station + Dark evidence streams with causal same-time ordering."""
    timeline: list[tuple[int, int, int, str, dict[str, Any]]] = []
    seq = 0
    corridor_upstream_stations = corridor_upstream_stations or set()

    for row in station_events.itertuples(index=False):
        event = row._asdict()
        ts = int(pd.to_numeric(event["timestamp_ms"], errors="raise"))
        typ = str(event.get("event_type", "")).strip().upper()
        sid = str(event.get("station_id", "")).strip()
        # Corridor upstream completion is an ENTRY boundary and must precede
        # same-time dark-start/checkpoint rows. Ordinary processing completion
        # remains an EXIT/service boundary.
        if typ == "PROCESSING_COMPLETED" and sid in corridor_upstream_stations:
            priority = -1
        elif typ == "PROCESSING_STARTED":
            priority = 0
        elif typ == "PROCESSING_COMPLETED":
            priority = 2
        else:
            priority = 1
        timeline.append((ts, priority, seq, "station", event))
        seq += 1

    for event in evidence_events:
        ts = int(event["timestamp_ms"])
        timeline.append((ts, 1, seq, "evidence", event))
        seq += 1

    timeline.sort(key=lambda x: (x[0], x[1], x[2]))
    return [(kind, event) for _, _, _, kind, event in timeline]


def replay_command(args: argparse.Namespace) -> int:
    """Replay CSV events through the exact live pipeline and write dashboard JSONL."""
    if args.pace and args.mult <= 0:
        raise ValueError("--mult must be positive when --pace is enabled")
    if args.inference_batch_size <= 0:
        raise ValueError("--inference-batch-size must be > 0")
    units_csv, events_csv, run_dir = _resolve_replay_inputs(args)
    dark_station_ids = _configured_dark_station_ids(args.configured_stations)
    corridors = _configured_corridors(args.configured_stations)
    helpers = _load_dark_zone_replay_helpers(args.dark_zone_dir) if dark_station_ids else {}
    historical_dwell = _prepare_replay_calibration(
        args=args,
        units_csv=units_csv,
        events_csv=events_csv,
        run_dir=run_dir,
        dark_station_ids=dark_station_ids,
        helpers=helpers,
    )
    corridor_residence = _prepare_replay_corridor_residence(
        args=args,
        events_csv=events_csv,
        run_dir=run_dir,
        corridors=corridors,
        helpers=helpers,
    )
    evidence_events = _prepare_replay_evidence(
        args=args,
        units_csv=units_csv,
        events_csv=events_csv,
        run_dir=run_dir,
        dark_station_ids=dark_station_ids,
        helpers=helpers,
    )

    pipeline = build_pipeline(
        configured_stations_csv=args.configured_stations,
        units_csv=units_csv,
        historical_dwell_csv=historical_dwell,
        corridor_residence_csv=corridor_residence,
        dark_zone_dir=args.dark_zone_dir,
        model_bundle_path=args.model_bundle,
        run_id=args.run_id,
        prediction_interval_s=args.prediction_interval_s,
        corridor_particles=args.corridor_particles,
    )

    if args.print_summary:
        print(json.dumps(pipeline.summary(), indent=2, ensure_ascii=False, default=str))

    output_path = Path(args.output_jsonl).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Empty the file first; a replay should be deterministic and should not append
    # to results from a previous run.
    total_predictions = 0
    processed_events = 0
    processed_evidence = 0
    last_timestamp_ms: Optional[int] = None
    delivered_timestamp_ms: Optional[int] = None
    pending_packets: list[Any] = []

    with output_path.open("w", encoding="utf-8") as output_handle:
        def flush_pending() -> int:
            if not pending_packets:
                return 0
            batch = pipeline.score_packets(pending_packets)
            pending_packets.clear()
            return _emit_predictions(
                batch,
                output_handle=output_handle,
                print_handle=sys.stdout if args.print_predictions else None,
                include_diagnostics=args.include_diagnostics,
            )

        events = pd.read_csv(events_csv)
        if args.limit is not None:
            events = events.iloc[: args.limit].copy()
            if not events.empty:
                replay_end_ms = int(pd.to_numeric(events["timestamp_ms"], errors="raise").max())
                evidence_events = [
                    e for e in evidence_events if int(e["timestamp_ms"]) <= replay_end_ms
                ]

        corridor_upstreams = {
            c.upstream_light_station
            for c in corridors.values()
            if c.upstream_light_station is not None
        }
        timeline = _merged_replay_timeline(
            events, evidence_events, corridor_upstream_stations=corridor_upstreams
        )
        for kind, event in timeline:
            last_timestamp_ms = int(pd.to_numeric(event["timestamp_ms"], errors="raise"))
            if args.pace and delivered_timestamp_ms is not None:
                # MULT controls delivery timing as well as the simulated clock.
                # Event order itself remains the source's causal order.
                delay_seconds = max(0, last_timestamp_ms - delivered_timestamp_ms) / (1000.0 * args.mult)
                if delay_seconds:
                    time.sleep(delay_seconds)
            delivered_timestamp_ms = last_timestamp_ms
            if kind == "evidence":
                packets = pipeline.route_evidence_event(event)
                processed_evidence += 1
            else:
                packets = pipeline.route_event(event)
                processed_events += 1
            pending_packets.extend(packets)

            # Accelerated/unpaced replay can batch model + TreeSHAP work because
            # predictions do not feed back into the causal runtime controller.
            # Paced replay keeps immediate emission semantics.
            effective_batch_size = 1 if args.pace else args.inference_batch_size
            if len(pending_packets) >= effective_batch_size:
                total_predictions += flush_pending()

        total_predictions += flush_pending()
        if args.flush_dark_to_ms is not None:
            flush_to = int(args.flush_dark_to_ms)
            predictions = pipeline.score_packets(pipeline.route_advance_time(flush_to))
            total_predictions += _emit_predictions(
                predictions,
                output_handle=output_handle,
                print_handle=sys.stdout if args.print_predictions else None,
                include_diagnostics=args.include_diagnostics,
            )
        elif args.flush_dark_by_ms is not None and last_timestamp_ms is not None:
            flush_to = last_timestamp_ms + int(args.flush_dark_by_ms)
            predictions = pipeline.score_packets(pipeline.route_advance_time(flush_to))
            total_predictions += _emit_predictions(
                predictions,
                output_handle=output_handle,
                print_handle=sys.stdout if args.print_predictions else None,
                include_diagnostics=args.include_diagnostics,
            )

    print(f"Station events processed: {processed_events}")
    print(f"Evidence events processed: {processed_evidence}")
    print(f"Predictions written: {total_predictions}")
    print(f"Output:              {output_path}")
    return 0


def _json_line_stream(handle: TextIO) -> Iterator[tuple[int, dict[str, Any]]]:
    for line_number, line in enumerate(handle, 1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON on input line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Input line {line_number} must be a JSON object")
        yield line_number, payload


def live_command(args: argparse.Namespace) -> int:
    """Consume JSONL station events from stdin/file and emit dashboard-ready JSONL.

    Normal line:
        {"timestamp_ms": ..., "station_id": "S01", "event_type": ...}

    Optional Dark heartbeat control line for periods with no station event:
        {"_control": "advance_time", "timestamp_ms": 123456}

    Optional Dark evidence control line:
        {"_control": "evidence", "event": {...}}
    """
    pipeline = build_pipeline(
        configured_stations_csv=args.configured_stations,
        units_csv=args.units,
        historical_dwell_csv=args.historical_dwell,
        corridor_residence_csv=args.corridor_residence,
        dark_zone_dir=args.dark_zone_dir,
        model_bundle_path=args.model_bundle,
        run_id=args.run_id,
        prediction_interval_s=args.prediction_interval_s,
        corridor_particles=args.corridor_particles,
    )

    if args.print_summary:
        print(
            json.dumps(pipeline.summary(), ensure_ascii=False, default=str),
            file=sys.stderr,
        )

    input_handle: TextIO
    close_input = False
    if args.input_jsonl is None or str(args.input_jsonl) == "-":
        input_handle = sys.stdin
    else:
        input_handle = _existing_file(args.input_jsonl, "input JSONL").open(
            "r", encoding="utf-8"
        )
        close_input = True

    output_handle: Optional[TextIO] = None
    if args.output_jsonl is not None:
        output_path = Path(args.output_jsonl).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_handle = output_path.open("a", encoding="utf-8")

    processed_inputs = 0
    total_predictions = 0
    try:
        for line_number, payload in _json_line_stream(input_handle):
            control = payload.get("_control")
            if control is None:
                predictions = pipeline.process_event(payload)
            elif control == "advance_time":
                if "timestamp_ms" not in payload:
                    raise ValueError(
                        f"advance_time control on line {line_number} requires timestamp_ms"
                    )
                predictions = pipeline.advance_time(int(payload["timestamp_ms"]))
            elif control == "evidence":
                evidence = payload.get("event")
                if not isinstance(evidence, Mapping):
                    raise ValueError(
                        f"evidence control on line {line_number} requires an event object"
                    )
                predictions = pipeline.process_evidence_event(evidence)
            else:
                raise ValueError(
                    f"Unknown _control={control!r} on input line {line_number}"
                )

            total_predictions += _emit_predictions(
                predictions,
                output_handle=output_handle,
                print_handle=None if args.quiet else sys.stdout,
                include_diagnostics=args.include_diagnostics,
            )
            processed_inputs += 1
    finally:
        if close_input:
            input_handle.close()
        if output_handle is not None:
            output_handle.close()

    print(
        f"Live input records processed: {processed_inputs}; predictions: {total_predictions}",
        file=sys.stderr,
    )
    return 0


def _add_pipeline_arguments(parser: argparse.ArgumentParser, *, units_required: bool) -> None:
    parser.add_argument(
        "--configured-stations",
        type=Path,
        default=DEFAULT_CONFIGURED_STATIONS,
        help=f"Configured station CSV (default: {DEFAULT_CONFIGURED_STATIONS})",
    )
    parser.add_argument(
        "--units",
        type=Path,
        required=units_required,
        help="units.csv. Replay can infer this from --run-dir.",
    )
    parser.add_argument(
        "--dark-zone-dir",
        type=Path,
        default=DEFAULT_DARK_ZONE_DIR,
        help=f"Existing Dark Zone folder (default: {DEFAULT_DARK_ZONE_DIR})",
    )
    parser.add_argument(
        "--model-bundle",
        type=Path,
        default=DEFAULT_MODEL_BUNDLE,
        help=f"Production 28-feature XGBoost joblib bundle (default: {DEFAULT_MODEL_BUNDLE})",
    )
    parser.add_argument("--historical-dwell", type=Path)
    parser.add_argument("--corridor-residence", type=Path)
    parser.add_argument("--run-id", default="LIVE")
    parser.add_argument("--prediction-interval-s", type=float, default=60.0)
    parser.add_argument("--corridor-particles", type=int, default=3000)
    parser.add_argument("--print-summary", action="store_true")
    parser.add_argument(
        "--include-diagnostics",
        action="store_true",
        help="Include Dark dashboard state and unknown model categories in output.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Digital Twin bottleneck backend: configure, replay, or run live."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser(
        "configure", help="Mark stations LIGHT/NORMAL or DARK/NONE."
    )
    configure.add_argument("--stations", type=Path, required=True)
    configure.add_argument(
        "--output", type=Path, default=DEFAULT_CONFIGURED_STATIONS
    )
    configure.add_argument(
        "--dark-stations",
        help=(
            "Optional comma-separated station IDs for non-interactive use, e.g. "
            "S07,S08. If omitted, you will be prompted."
        ),
    )
    configure.set_defaults(func=configure_command)

    replay = sub.add_parser(
        "replay", help="Replay station_events.csv through the complete runtime pipeline."
    )
    _add_pipeline_arguments(replay, units_required=False)
    replay.add_argument(
        "--run-dir",
        type=Path,
        help=(
            "Run directory containing units.csv and station_events.csv. "
            "manual_checks.csv and station_checkpoints.csv are auto-discovered."
        ),
    )
    replay.add_argument("--events", type=Path)
    replay.add_argument(
        "--manual-checks",
        type=Path,
        help="Optional override for manual_checks.csv; auto-discovered from --run-dir.",
    )
    replay.add_argument(
        "--checkpoint-events",
        type=Path,
        help=(
            "Optional explicit checkpoint_events.csv. With --run-dir, the simulator's "
            "checkpoint_events.csv is auto-discovered; generation is legacy fallback only."
        ),
    )
    replay.add_argument(
        "--station-checkpoints",
        type=Path,
        help="Optional override for station_checkpoints.csv; auto-discovered from --run-dir.",
    )
    replay.add_argument(
        "--allow-same-run-calibration",
        action="store_true",
        help=(
            "DEMO ONLY: allow the replayed completed run to calibrate its own DARK "
            "estimator. Never use this for validation or production evaluation."
        ),
    )
    replay.add_argument(
        "--no-auto-evidence",
        action="store_true",
        help="Replay only station_events.csv; do not auto-load/generate Layers 3-5 evidence.",
    )
    replay.add_argument(
        "--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL
    )
    replay.add_argument(
        "--limit", type=int, help="Optional number of input events for a smoke/demo replay."
    )
    replay.add_argument(
        "--inference-batch-size",
        type=int,
        default=256,
        help=(
            "Batch size for XGBoost + TreeSHAP during unpaced replay (default: 256). "
            "Use 1 for strictly per-prediction inference."
        ),
    )
    replay.add_argument("--flush-dark-to-ms", type=int)
    replay.add_argument(
        "--flush-dark-by-ms",
        type=int,
        help="After the last replayed event, advance Dark PFs by this many milliseconds.",
    )
    replay.add_argument(
        "--print-predictions",
        action="store_true",
        help="Also print each formatted prediction to stdout.",
    )
    replay.add_argument(
        "--mult",
        type=float,
        default=1.0,
        help="Simulation-time to event-delivery multiplier when --pace is enabled.",
    )
    replay.add_argument(
        "--pace",
        action="store_true",
        help="Deliver replay events against wall-clock time at --mult while preserving causal order.",
    )
    replay.set_defaults(func=replay_command)

    live = sub.add_parser(
        "live", help="Consume station events as JSONL from stdin or a JSONL file."
    )
    _add_pipeline_arguments(live, units_required=True)
    live.add_argument(
        "--input-jsonl",
        type=Path,
        help="Input JSONL path. Omit to read stdin.",
    )
    live.add_argument(
        "--output-jsonl",
        type=Path,
        help="Optional persistent JSONL log. Live output is also printed unless --quiet.",
    )
    live.add_argument(
        "--quiet", action="store_true", help="Do not print predictions to stdout."
    )
    live.set_defaults(func=live_command)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
