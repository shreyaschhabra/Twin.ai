"""Run generated scenario/defect pairs through the standalone simulator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from .scenario_generator import generate
except ImportError:  # Supports direct execution: python training/orchestrator.py
    from scenario_generator import generate


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def run_generated(
    simulator: Path,
    factory: Path,
    generated_directory: Path,
    output_directory: Path,
    fail_fast: bool,
    *,
    progress: Callable[[str], None] | None = None,
) -> Path:
    manifest = _read_json(generated_directory / "manifest.json")
    output_directory.mkdir(parents=True, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    runs = manifest.get("runs", [])
    if progress:
        progress(f"Running {len(runs)} simulator scenario(s) with {simulator}...")
    for index, run in enumerate(runs, start=1):
        run_id = run["run_id"]
        run_directory = output_directory / run_id
        if progress:
            progress(f"Simulator run {index}/{len(runs)} started: {run_id}")
        command = [
            str(simulator),
            "--factory",
            str(factory),
            "--scenario",
            str(generated_directory / run["scenario"]),
            "--defects",
            str(generated_directory / run["defects"]),
            "--output",
            str(run_directory),
        ]
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            return_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except OSError as error:
            return_code, stdout, stderr = -1, "", str(error)
        (run_directory / "simulator.stdout.log").parent.mkdir(parents=True, exist_ok=True)
        (run_directory / "simulator.stdout.log").write_text(stdout, encoding="utf-8")
        (run_directory / "simulator.stderr.log").write_text(stderr, encoding="utf-8")
        outcomes.append(
            {
                "run_id": run_id,
                "seed": run["seed"],
                "output": str(run_directory),
                "return_code": return_code,
                "status": "completed" if return_code == 0 else "failed",
            }
        )
        if progress:
            state = "completed" if return_code == 0 else f"failed (exit {return_code})"
            progress(f"Simulator run {index}/{len(runs)} {state}: {run_id}")
        if return_code != 0 and fail_fast:
            break
    run_manifest = {"schema_version": "1.0", "factory": str(factory.resolve()), "runs": outcomes}
    result_path = output_directory / "run_manifest.json"
    _write_json(result_path, run_manifest)
    if any(outcome["status"] == "failed" for outcome in outcomes):
        raise RuntimeError(f"{sum(item['status'] == 'failed' for item in outcomes)} simulator run(s) failed")
    if progress:
        progress(f"Simulator batch complete: {result_path}")
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and/or execute simulator training runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate_parser = subparsers.add_parser("generate", help="Generate scenario/defect pairs")
    generate_parser.add_argument("--factory", type=Path, required=True)
    generate_parser.add_argument("--generated", type=Path, required=True)
    generate_parser.add_argument("--count", type=int, required=True)
    generate_parser.add_argument("--seed", type=int, default=42)
    generate_parser.add_argument("--duration-ms", type=int, default=28_800_000)
    run_parser = subparsers.add_parser("run", help="Run a generated manifest")
    run_parser.add_argument("--simulator", type=Path, required=True)
    run_parser.add_argument("--factory", type=Path, required=True)
    run_parser.add_argument("--generated", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--fail-fast", action="store_true")
    all_parser = subparsers.add_parser("all", help="Generate and run scenarios")
    all_parser.add_argument("--simulator", type=Path, required=True)
    all_parser.add_argument("--factory", type=Path, required=True)
    all_parser.add_argument("--generated", type=Path, required=True)
    all_parser.add_argument("--output", type=Path, required=True)
    all_parser.add_argument("--count", type=int, required=True)
    all_parser.add_argument("--seed", type=int, default=42)
    all_parser.add_argument("--duration-ms", type=int, default=28_800_000)
    all_parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            print(generate(args.factory, args.generated, args.count, args.seed, args.duration_ms, progress=print))
        elif args.command == "run":
            print(run_generated(args.simulator, args.factory, args.generated, args.output, args.fail_fast, progress=print))
        else:
            generate(args.factory, args.generated, args.count, args.seed, args.duration_ms, progress=print)
            print(run_generated(args.simulator, args.factory, args.generated, args.output, args.fail_fast, progress=print))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        parser.exit(1, f"orchestration failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
