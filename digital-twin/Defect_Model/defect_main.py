"""Single entry point for the finalized V5 defect runtime + SHAP pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator, TextIO, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:  # package-safe when invoked through root cli.py
    from .output.defect_prediction_output import append_jsonl, format_prediction
    from .runtime.defect_pipeline import DigitalTwinDefectPipeline
except ImportError:  # direct: python Defect_Model/defect_main.py
    from output.defect_prediction_output import append_jsonl, format_prediction
    from runtime.defect_pipeline import DigitalTwinDefectPipeline

DEFAULT_MODEL = PROJECT_ROOT / "saved_models" / "defect_v5_models.joblib"
DEFAULT_CONFIG = PROJECT_ROOT / "saved_models" / "defect_v5_config.json"
DEFAULT_CALIBRATOR = PROJECT_ROOT / "saved_models" / "defect_v5_calibrator.joblib"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "output" / "defect_predictions.jsonl"


def build_pipeline(
    *,
    stations_csv: str | Path,
    units_csv: str | Path,
    model_artifact_path: str | Path = DEFAULT_MODEL,
    config_path: str | Path = DEFAULT_CONFIG,
    calibrator_path: str | Path = DEFAULT_CALIBRATOR,
    run_id: str = "LIVE",
    explain_mode: str = "warnings",
    shap_top_k: int = 3,
    dark_adapter=None,
) -> DigitalTwinDefectPipeline:
    return DigitalTwinDefectPipeline(
        stations_csv=stations_csv,
        units_csv=units_csv,
        model_artifact_path=model_artifact_path,
        config_path=config_path,
        calibrator_path=calibrator_path,
        run_id=run_id,
        explain_mode=explain_mode,
        shap_top_k=shap_top_k,
        dark_adapter=dark_adapter,
    )


def _station_priority(event_type: Any) -> int:
    event_type = str(event_type).strip().upper()
    if event_type == "PROCESSING_STARTED":
        return 10
    if event_type == "PROCESSING_COMPLETED":
        return 50
    return 40


def iter_replay_records(run_dir: str | Path) -> Iterator[dict[str, Any]]:
    run_dir = Path(run_dir)

    events_path = run_dir / "station_events.csv"
    sensors_path = run_dir / "sensor_readings.csv"
    manual_path = run_dir / "manual_checks.csv"

    for p in (events_path, sensors_path, manual_path):
        if not p.is_file():
            raise FileNotFoundError(f"Required replay file not found: {p}")

    events = pd.read_csv(events_path)
    events["event_sequence"] = range(len(events))
    events["_stream"] = "station_event"
    events["_source_order"] = range(len(events))
    events["_priority"] = events["event_type"].map(_station_priority)

    sensors = pd.read_csv(sensors_path)
    sensors["_stream"] = "sensor_reading"
    sensors["_source_order"] = range(len(sensors))
    sensors["_priority"] = 20

    manual = pd.read_csv(manual_path)
    manual["_stream"] = "manual_check"
    manual["_source_order"] = range(len(manual))
    manual["_priority"] = 30

    common = pd.concat([events, sensors, manual], ignore_index=True, sort=False)
    common["timestamp_ms"] = pd.to_numeric(common["timestamp_ms"], errors="raise")
    common = common.sort_values(
        ["timestamp_ms", "_priority", "_source_order"],
        kind="stable",
    )

    for row in common.to_dict(orient="records"):
        stream = str(row.pop("_stream"))
        row.pop("_priority", None)
        row.pop("_source_order", None)

        clean = {
            key: value
            for key, value in row.items()
            if not (isinstance(value, float) and pd.isna(value))
        }
        clean["stream"] = stream
        yield clean


def replay_command(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    stations = run_dir / "stations.csv"
    units = run_dir / "units.csv"
    if not stations.is_file() or not units.is_file():
        raise FileNotFoundError("run-dir must contain stations.csv and units.csv")

    run_id = args.run_id or run_dir.name
    pipeline = build_pipeline(
        stations_csv=stations,
        units_csv=units,
        model_artifact_path=args.model,
        config_path=args.config,
        calibrator_path=args.calibrator,
        run_id=run_id,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
    )

    output_path = Path(args.output_jsonl).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("", encoding="utf-8")

    count = 0
    explained = 0
    for record in iter_replay_records(run_dir):
        predictions = pipeline.process_record(record)
        if predictions:
            count += append_jsonl(output_path, predictions)
            explained += sum(p.explanation_available for p in predictions)

    if args.print_summary:
        print(json.dumps(pipeline.summary(), indent=2, default=str))

    print(f"Defect predictions written: {count}")
    print(f"Predictions with SHAP explanations: {explained}")
    print(output_path)
    return 0


def _iter_jsonl(handle: TextIO) -> Iterator[dict[str, Any]]:
    for line_number, line in enumerate(handle, start=1):
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Line {line_number} must be a JSON object")
        yield payload


def live_command(args: argparse.Namespace) -> int:
    pipeline = build_pipeline(
        stations_csv=args.stations,
        units_csv=args.units,
        model_artifact_path=args.model,
        config_path=args.config,
        calibrator_path=args.calibrator,
        run_id=args.run_id,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
    )

    should_close = False
    if args.input_jsonl is None:
        input_handle = sys.stdin
    else:
        input_handle = Path(args.input_jsonl).open("r", encoding="utf-8")
        should_close = True

    output_path = (
        Path(args.output_jsonl).expanduser().resolve()
        if args.output_jsonl is not None
        else None
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        for record in _iter_jsonl(input_handle):
            predictions = pipeline.process_record(record)
            for prediction in predictions:
                payload = format_prediction(prediction)
                print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
                if output_path is not None:
                    append_jsonl(output_path, [prediction])
    finally:
        if should_close:
            input_handle.close()

    return 0


def _add_explanation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--explain-mode",
        choices=["off", "warnings", "all"],
        default="warnings",
        help=(
            "off=no SHAP; warnings=SHAP only for actionable warnings; "
            "all=SHAP for every prediction"
        ),
    )
    parser.add_argument(
        "--shap-top-k",
        type=int,
        default=3,
        help="Number of positive and protective SHAP drivers to return",
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V5 defect runtime + SHAP pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay")
    replay.add_argument("--run-dir", required=True)
    replay.add_argument("--run-id")
    replay.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT))
    replay.add_argument("--model", default=str(DEFAULT_MODEL))
    replay.add_argument("--config", default=str(DEFAULT_CONFIG))
    replay.add_argument("--calibrator", default=str(DEFAULT_CALIBRATOR))
    replay.add_argument("--print-summary", action="store_true")
    _add_explanation_args(replay)
    replay.set_defaults(func=replay_command)

    live = sub.add_parser("live")
    live.add_argument("--stations", required=True)
    live.add_argument("--units", required=True)
    live.add_argument("--run-id", default="LIVE")
    live.add_argument("--input-jsonl")
    live.add_argument("--output-jsonl")
    live.add_argument("--model", default=str(DEFAULT_MODEL))
    live.add_argument("--config", default=str(DEFAULT_CONFIG))
    live.add_argument("--calibrator", default=str(DEFAULT_CALIBRATOR))
    _add_explanation_args(live)
    live.set_defaults(func=live_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
