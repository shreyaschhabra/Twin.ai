"""Repository-level Digital Twin control plane.

Run ``py cli.py`` on Windows or ``python3 cli.py`` on macOS/Linux. Running
without arguments opens the interactive shell; one-shot commands use these
same handlers for automation.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = PROJECT_ROOT / "bottlenecks_prediction"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from factory_models import (  # noqa: E402
    BASE_MODEL_ID, DEFAULT_ARTIFACT_ROOT, configure_factory, delete_model,
    list_models, model_paths, select_model, selected_model_id, train_factory_model,
    build_dark_calibration_files,
)
from config.configure_stations import configure_from_dz, validate_runtime_topology_match  # noqa: E402
from factory_registry import (  # noqa: E402
    DEFAULT_REGISTRY, delete_factory, get_factory, list_factories,
    register_factory, set_configured_stations,
)
from simulation.training.orchestrator import run_generated  # noqa: E402
from simulation.training.scenario_generator import generate  # noqa: E402
from Defect_Model.factory_models import (  # noqa: E402
    BASE_MODEL_ID as DEFECT_BASE_MODEL_ID,
    DEFAULT_ARTIFACT_ROOT as DEFAULT_DEFECT_ARTIFACT_ROOT,
    delete_model as delete_defect_model,
    list_models as list_defect_models,
    model_paths as defect_model_paths,
    select_model as select_defect_model,
    selected_model_id as selected_defect_model_id,
    train_factory_model as train_defect_factory_model,
    validate_runtime_factory_contract as validate_defect_runtime_factory_contract,
)

DEFAULT_FACTORY = PROJECT_ROOT / "simulation" / "config" / "factory.json"
DEFAULT_RUNS = PROJECT_ROOT / "simulation" / "training" / "runs"
DEFAULT_GENERATED = PROJECT_ROOT / "simulation" / "training" / "generated"
DEFAULT_DEFECT_OUTPUT = PROJECT_ROOT / "Defect_Model" / "data" / "output" / "defect_predictions.jsonl"
SIMULATION_ROOT = PROJECT_ROOT / "simulation"
SIMULATION_BUILD = SIMULATION_ROOT / "build"
DEFAULT_SIMULATOR = None

#: Playback-speed bounds for `system run random`'s paced coordinated replay. 1x is
#: approximately real-time; the ceiling keeps a run from being paced so fast that
#: sub-millisecond inter-event delays become meaningless.
PLAYBACK_SPEED_MIN = 0.75
PLAYBACK_SPEED_MAX = 20.0


def _playback_speed(value: str) -> float:
    parsed = float(value)
    if not (PLAYBACK_SPEED_MIN <= parsed <= PLAYBACK_SPEED_MAX):
        raise argparse.ArgumentTypeError(
            f"--mult must be between {PLAYBACK_SPEED_MIN}x and {PLAYBACK_SPEED_MAX}x "
            f"(got {parsed}x)"
        )
    return parsed


def _system_runtime():
    # Imported lazily so ordinary factory/model commands do not pay runtime startup cost.
    import system_runtime
    return system_runtime


def _require_force(force: bool, action: str) -> None:
    if not force:
        raise ValueError(f"Refusing to {action}. Repeat with --force after verifying the target.")


def _run_directory(path: str | Path) -> Path:
    run = Path(path).expanduser().resolve()
    missing = [name for name in ("stations.csv", "units.csv", "station_events.csv", "run_metadata.json") if not (run / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Not a completed simulator run directory: {run}; missing {', '.join(missing)}")
    return run


def _simulator_candidates() -> list[Path]:
    if sys.platform.startswith("win"):
        return [
            SIMULATION_BUILD / "Release" / "simulation.exe",
            SIMULATION_BUILD / "Debug" / "simulation.exe",
            SIMULATION_BUILD / "simulation.exe",
        ]
    return [
        SIMULATION_BUILD / "simulation",
        SIMULATION_BUILD / "Release" / "simulation",
        SIMULATION_BUILD / "Debug" / "simulation",
    ]


def _resolve_simulator(explicit: str | Path | None, *, auto_build: bool = True) -> Path:
    """Find the C++ simulator cross-platform and build it when needed."""
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"Simulator executable not found: {path}")

    for candidate in _simulator_candidates():
        if candidate.is_file():
            return candidate.resolve()

    if auto_build:
        cmake = shutil.which("cmake")
        if cmake is None:
            raise FileNotFoundError(
                "Simulator is not built and CMake is not available on PATH. "
                "Install CMake + a C++ compiler, then run: "
                "cmake -S simulation -B simulation/build && "
                "cmake --build simulation/build --config Release"
            )
        SIMULATION_BUILD.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [cmake, "-S", str(SIMULATION_ROOT), "-B", str(SIMULATION_BUILD)],
                cwd=PROJECT_ROOT,
                check=True,
            )
            subprocess.run(
                [cmake, "--build", str(SIMULATION_BUILD), "--config", "Release"],
                cwd=PROJECT_ROOT,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Automatic simulator build failed. Check that a supported C++ compiler "
                "is installed, then rerun the CMake commands shown in README.md."
            ) from exc

        for candidate in _simulator_candidates():
            if candidate.is_file():
                return candidate.resolve()

    searched = ", ".join(str(p) for p in _simulator_candidates())
    raise FileNotFoundError(f"Simulator executable not found. Searched: {searched}")


def _model_runtime_args(
    model_id: str | None,
    artifact_root: Path,
    run_dir: str | Path,
    base_history_root: str | Path | None = None,
) -> list[str]:
    """Resolve one runtime contract for either BASE or a factory artifact.

    Factory artifacts carry immutable configured topology/calibration.  BASE
    derives topology from the simulator run's authoritative ``dz.csv``; raw
    ``sensor_coverage`` is telemetry richness and must not be used as a DARK flag.
    """
    chosen = model_id or selected_model_id(artifact_root)
    paths = model_paths(chosen, artifact_root)

    if chosen == BASE_MODEL_ID:
        run = Path(run_dir).expanduser().resolve()
        stations = run / "stations.csv"
        dz = run / "dz.csv"
        if not stations.is_file():
            raise FileNotFoundError(f"Run stations.csv not found for base model: {stations}")
        if not dz.is_file():
            raise FileNotFoundError(
                f"Run dz.csv not found for base model: {dz}. "
                "Simulator schema v2.1 uses dz.csv as the DARK topology contract."
            )
        configured, dark_ids = configure_from_dz(stations, dz)
        generated = PACKAGE_ROOT / "data" / "generated" / run.name
        generated.mkdir(parents=True, exist_ok=True)
        configured_path = generated / "configured_stations.csv"
        configured.to_csv(configured_path, index=False)
        result = [
            "--configured-stations", str(configured_path),
            "--model-bundle", str(paths["bundle"]),
        ]
        if dark_ids:
            history_root = Path(
                base_history_root or (PACKAGE_ROOT / "data" / "calibration" / "history")
            ).expanduser().resolve()
            history_runs = [
                d for d in sorted(history_root.iterdir())
                if d.is_dir()
                and all((d / name).is_file() for name in ("stations.csv", "units.csv", "station_events.csv"))
            ] if history_root.is_dir() else []
            if not history_runs:
                raise FileNotFoundError(
                    "BASE model DARK replay requires prior calibration history. "
                    f"No completed runs found under {history_root}."
                )
            cal_dir = generated / "base_prior_calibration"
            dwell, residence, _ = build_dark_calibration_files(
                history_runs, configured_path, cal_dir, dark_station_ids=set(dark_ids)
            )
            if dwell is None:
                raise RuntimeError("BASE DARK history produced no historical dwell calibration")
            result += ["--historical-dwell", str(dwell)]
            if residence is not None:
                result += ["--corridor-residence", str(residence)]
        return result

    run = Path(run_dir).expanduser().resolve()
    dz = run / "dz.csv"
    if not dz.is_file():
        raise FileNotFoundError(
            f"Run dz.csv not found for factory model {chosen!r}: {dz}"
        )
    validate_runtime_topology_match(
        paths["configured_stations"], run / "stations.csv", dz
    )
    result = [
        "--configured-stations", str(paths["configured_stations"]),
        "--model-bundle", str(paths["model_bundle"]),
    ]
    if "historical_dwell" in paths:
        result += ["--historical-dwell", str(paths["historical_dwell"])]
    if "corridor_residence" in paths:
        result += ["--corridor-residence", str(paths["corridor_residence"])]
    return result


def command_configure(args: argparse.Namespace) -> int:
    print(configure_factory(args.factory, args.stations, args.output)); return 0


def command_generate(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Generation output already contains files: {output}. Choose a new --output directory.")
    print(generate(args.factory, output, args.count, args.seed, args.duration_ms, progress=print)); return 0


def command_simulate(args: argparse.Namespace) -> int:
    generated, output = Path(args.generated).expanduser().resolve(), Path(args.output).expanduser().resolve()
    manifest = generated / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"Generated scenario manifest not found: {manifest}")
    run_ids = [str(item["run_id"]) for item in json.loads(manifest.read_text(encoding="utf-8")).get("runs", [])]
    existing = [run_id for run_id in run_ids if (output / run_id).exists()]
    if existing:
        raise FileExistsError("Simulator output already exists for: " + ", ".join(existing) + ". Choose a new --output directory.")
    simulator = _resolve_simulator(args.simulator)
    print(run_generated(simulator, args.factory, generated, output, args.fail_fast, progress=print)); return 0


def command_data_list(args: argparse.Namespace) -> int:
    root = Path(args.runs).expanduser().resolve()
    if not root.is_dir():
        print("[]"); return 0
    rows = []
    for run in sorted(path for path in root.glob("run_*") if path.is_dir()):
        metadata = run / "run_metadata.json"
        data = json.loads(metadata.read_text(encoding="utf-8")) if metadata.is_file() else {}
        rows.append({"run_id": run.name, "path": str(run), "completed": metadata.is_file(), "units_created": data.get("units_created")})
    print(json.dumps(rows, indent=2)); return 0


def command_data_delete(args: argparse.Namespace) -> int:
    _require_force(args.force, f"delete run {args.run_id!r}")
    root, target = Path(args.runs).expanduser().resolve(), (Path(args.runs).expanduser().resolve() / args.run_id).resolve()
    if target.parent != root or not target.is_dir() or not target.name.startswith("run_"):
        raise ValueError("Run deletion target must be an existing direct run_* child of --runs")
    shutil.rmtree(target); print(f"Deleted run directory: {target}"); return 0


def command_models_list(args: argparse.Namespace) -> int:
    print(json.dumps(list_models(args.artifact_root), indent=2)); return 0


def command_models_select(args: argparse.Namespace) -> int:
    print(json.dumps(select_model(args.model_id, args.artifact_root), indent=2)); return 0


def command_models_delete(args: argparse.Namespace) -> int:
    _require_force(args.force, f"delete model {args.model_id!r}")
    delete_model(args.model_id, args.artifact_root); print(f"Deleted factory model: {args.model_id}"); return 0


def command_train(args: argparse.Namespace) -> int:
    if args.replace:
        _require_force(args.force, f"replace model {args.model_id!r}")
    registered = get_factory(args.factory_id, args.registry) if args.factory_id else None
    print(train_factory_model(model_id=args.model_id, factory_json=registered["factory_json"] if registered else args.factory,
        runs_root=args.runs, configured_stations=registered.get("configured_stations") if registered else None,
        root=args.artifact_root, seed=args.seed, threshold_objective=args.threshold_objective,
        replace=args.replace, progress=print)); return 0


def command_factories_list(args: argparse.Namespace) -> int:
    print(json.dumps(list_factories(args.registry), indent=2)); return 0


def command_factories_show(args: argparse.Namespace) -> int:
    print(json.dumps(get_factory(args.factory_id, args.registry), indent=2)); return 0


def command_factory_add(args: argparse.Namespace) -> int:
    factory = Path(args.factory).expanduser().resolve()
    inferred = factory.parent.name if factory.stem.lower() == "factory" else factory.stem
    print(json.dumps(register_factory(args.factory_id or inferred, factory, args.registry, replace=args.replace), indent=2)); return 0


def command_factories_configure(args: argparse.Namespace) -> int:
    entry = get_factory(args.factory_id, args.registry)
    output = args.output or (Path(args.registry).expanduser().resolve().parent / "configurations" / entry["id"] / "configured_stations.csv")
    print(json.dumps(set_configured_stations(entry["id"], configure_factory(entry["factory_json"], args.stations, output), args.registry), indent=2)); return 0


def command_factories_delete(args: argparse.Namespace) -> int:
    _require_force(args.force, f"delete factory registration {args.factory_id!r}")
    delete_factory(args.factory_id, args.registry); print(f"Deleted factory registration: {args.factory_id}"); return 0


def command_run_prescribed(args: argparse.Namespace) -> int:
    from main import main as bottleneck_main
    run, output = _run_directory(args.run_dir), Path(args.output).expanduser().resolve()
    if output.exists():
        _require_force(args.force, f"overwrite prediction output {str(output)!r}")
    argv = ["replay", "--run-dir", str(run), "--output-jsonl", str(output), "--run-id", args.run_id or run.name]
    argv += _model_runtime_args(args.model_id, args.artifact_root, run, args.base_history)
    if not args.unpaced:
        argv += ["--pace", "--mult", str(args.mult)]
    return bottleneck_main(argv)


def command_run_random(args: argparse.Namespace) -> int:
    generated, runs = Path(args.generated).expanduser().resolve(), Path(args.runs).expanduser().resolve()
    if generated.exists() and any(generated.iterdir()):
        raise FileExistsError(f"Random-test generated-input directory already contains files: {generated}. Choose a new --generated directory.")
    if (runs / "run_0001").exists():
        raise FileExistsError(f"Random-test destination already exists: {runs / 'run_0001'}. Choose a new --runs directory.")
    print("Preparing a random simulator run...")
    generate(args.factory, generated, 1, args.seed, args.duration_ms, progress=print)
    run_generated(_resolve_simulator(args.simulator), args.factory, generated, runs, fail_fast=True, progress=print)
    return command_run_prescribed(argparse.Namespace(run_dir=runs / "run_0001", output=args.output, run_id="random_run_0001",
        model_id=args.model_id, artifact_root=args.artifact_root, base_history=args.base_history, mult=args.mult, unpaced=args.unpaced, force=args.force))


def command_defect_models_list(args: argparse.Namespace) -> int:
    print(json.dumps(list_defect_models(args.artifact_root), indent=2)); return 0


def command_defect_models_select(args: argparse.Namespace) -> int:
    print(json.dumps(select_defect_model(args.model_id, args.artifact_root), indent=2)); return 0


def command_defect_models_delete(args: argparse.Namespace) -> int:
    _require_force(args.force, f"delete defect model {args.model_id!r}")
    delete_defect_model(args.model_id, args.artifact_root)
    print(f"Deleted defect factory model: {args.model_id}"); return 0


def _defect_runtime_args(model_id: str | None, artifact_root: Path, run_dir: str | Path) -> list[str]:
    chosen = model_id or selected_defect_model_id(artifact_root)
    paths = defect_model_paths(chosen, artifact_root)
    run = Path(run_dir).expanduser().resolve()
    if chosen != DEFECT_BASE_MODEL_ID:
        validate_defect_runtime_factory_contract(paths, run)
    return [
        "--model", str(paths["model"]),
        "--config", str(paths["config"]),
        "--calibrator", str(paths["calibrator"]),
    ]


def command_defect_run_live(args: argparse.Namespace) -> int:
    from Defect_Model.run_current_defects import main as defect_live_main
    argv = [
        "--run-dir", str(Path(args.run_dir).expanduser().resolve()),
        "--output", str(Path(args.output).expanduser().resolve()),
        "--run-id", str(args.run_id),
        "--artifact-root", str(Path(args.artifact_root).expanduser().resolve()),
        "--explain-mode", str(args.explain_mode),
        "--shap-top-k", str(args.shap_top_k),
        "--wait-seconds", str(args.wait_seconds),
        "--poll-ms", str(args.poll_ms),
        "--live-batch-size", str(args.live_batch_size),
    ]
    if args.model_id:
        argv += ["--model-id", str(args.model_id)]
    return defect_live_main(argv)


def command_defect_run_prescribed(args: argparse.Namespace) -> int:
    from Defect_Model.run_current_defects import main as defect_runtime_main
    run = _run_directory(args.run_dir)
    required = ["runtime_events.csv", "dz.csv", "station_checkpoints.csv"]
    missing = [name for name in required if not (run / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "Defect replay requires streamlined simulator public-bus files: " + ", ".join(missing)
        )
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        _require_force(args.force, f"overwrite defect prediction output {str(output)!r}")
    argv = [
        "--mode", "replay", "--run-dir", str(run), "--output", str(output),
        "--run-id", args.run_id or run.name,
        "--artifact-root", str(Path(args.artifact_root).expanduser().resolve()),
        "--history-root", str(Path(args.history_root).expanduser().resolve()),
        "--particles", str(args.particles),
        "--explain-mode", args.explain_mode,
        "--shap-top-k", str(args.shap_top_k),
    ]
    if args.model_id:
        argv += ["--model-id", str(args.model_id)]
    return defect_runtime_main(argv)


def command_defect_train(args: argparse.Namespace) -> int:
    if args.replace:
        _require_force(args.force, f"replace defect model {args.model_id!r}")
    registered = get_factory(args.factory_id, args.registry) if args.factory_id else None
    factory_json = registered["factory_json"] if registered else args.factory
    if factory_json is None:
        raise ValueError("Provide --factory-id for a registered factory or --factory path")
    path = train_defect_factory_model(
        model_id=args.model_id,
        factory_json=factory_json,
        factory_id=registered["id"] if registered else args.factory_id,
        runs_root=args.runs,
        root=args.artifact_root,
        validation_fraction=args.validation_fraction,
        seed=args.seed,
        corridor_particles=args.particles,
        continuation_iterations=args.continuation_iterations,
        replace=args.replace,
        progress=print,
    )
    print(path)
    return 0


def command_defect_status(args: argparse.Namespace) -> int:
    print(json.dumps({
        "subsystem": "defects",
        "selected_model": selected_defect_model_id(args.artifact_root),
        "models": list_defect_models(args.artifact_root),
        "shared_factory_registry": str(args.registry),
        "factories": list_factories(args.registry),
        "runtime_sources": ["stations.csv", "units.csv", "runtime_events.csv"],
        "live_bus_ready": True,
        "live_record_types": ["STATION", "SENSOR", "MANUAL"],
        "ignored_parallel_records": ["EVIDENCE"],
        "ground_truth_on_live_bus": False,
        "dark_zone_sensor_assignment": "causal PF-based attribution enabled",
        "factory_training": "deployment-public-bus replay with inspection label-only and no same-run DARK calibration",
    }, indent=2)); return 0


def command_system_models_list(args: argparse.Namespace) -> int:
    runtime = _system_runtime()
    print(json.dumps(runtime.list_dual_models(
        bottleneck_artifact_root=args.bottleneck_artifact_root,
        defect_artifact_root=args.defect_artifact_root,
    ), indent=2))
    return 0


def command_system_models_use(args: argparse.Namespace) -> int:
    runtime = _system_runtime()
    print(json.dumps(runtime.select_dual_model(
        args.model_id,
        bottleneck_artifact_root=args.bottleneck_artifact_root,
        defect_artifact_root=args.defect_artifact_root,
    ), indent=2))
    return 0


def command_system_status(args: argparse.Namespace) -> int:
    runtime = _system_runtime()
    print(json.dumps(runtime.system_status(
        run_dir=args.run_dir,
        output_dir=args.output_dir,
        bottleneck_artifact_root=args.bottleneck_artifact_root,
        defect_artifact_root=args.defect_artifact_root,
    ), indent=2))
    return 0


def command_system_run_prescribed(args: argparse.Namespace) -> int:
    runtime = _system_runtime()
    result = runtime.run_dual_prescribed(
        run_dir=args.run_dir,
        output_dir=args.output_dir,
        run_id=args.run_id,
        bottleneck_model_id=args.bottleneck_model_id,
        defect_model_id=args.defect_model_id,
        bottleneck_artifact_root=args.bottleneck_artifact_root,
        defect_artifact_root=args.defect_artifact_root,
        history_root=args.history_root,
        particles=args.particles,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0


def command_system_run_live(args: argparse.Namespace) -> int:
    runtime = _system_runtime()
    result = runtime.run_dual_live(
        run_dir=args.run_dir,
        output_dir=args.output_dir,
        run_id=args.run_id,
        bottleneck_model_id=args.bottleneck_model_id,
        defect_model_id=args.defect_model_id,
        bottleneck_artifact_root=args.bottleneck_artifact_root,
        defect_artifact_root=args.defect_artifact_root,
        history_root=args.history_root,
        particles=args.particles,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
        wait_seconds=args.wait_seconds,
        poll_ms=args.poll_ms,
        force=args.force,
        failure_policy=args.failure_policy,
    )
    print(json.dumps(result, indent=2))
    return 0


def command_system_run_random(args: argparse.Namespace) -> int:
    runtime = _system_runtime()
    generated = Path(args.generated).expanduser().resolve()
    runs = Path(args.runs).expanduser().resolve()
    run = runs / "run_0001"
    if generated.exists() and any(generated.iterdir()):
        raise FileExistsError(f"Generated-input directory already contains files: {generated}")
    if run.exists():
        raise FileExistsError(f"Random dual-run destination already exists: {run}")
    print("Preparing one random simulator run for both prediction systems...")
    generate(args.factory, generated, 1, args.seed, args.duration_ms, progress=print)
    run_generated(
        _resolve_simulator(args.simulator), args.factory, generated, runs,
        fail_fast=True, progress=print
    )
    result = runtime.run_dual_prescribed(
        run_dir=run,
        output_dir=args.output_dir,
        run_id=args.run_id or "random_run_0001",
        bottleneck_model_id=args.bottleneck_model_id,
        defect_model_id=args.defect_model_id,
        bottleneck_artifact_root=args.bottleneck_artifact_root,
        defect_artifact_root=args.defect_artifact_root,
        history_root=args.history_root,
        particles=args.particles,
        explain_mode=args.explain_mode,
        shap_top_k=args.shap_top_k,
        force=args.force,
        mode="random",
        multiplier=args.mult,
    )
    print(json.dumps(result, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    print(json.dumps({"selected_model": selected_model_id(args.artifact_root), "models": list_models(args.artifact_root),
        "factories": list_factories(args.registry), "default_factory": str(DEFAULT_FACTORY), "default_runs": str(DEFAULT_RUNS),
        "simulator": str(next((p for p in _simulator_candidates() if p.is_file()), _simulator_candidates()[0])),
        "simulator_built": any(p.is_file() for p in _simulator_candidates())}, indent=2)); return 0


def _add_factory_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    factory = sub.add_parser("factory", help="Add, inspect, configure, and remove factory definitions")
    children = factory.add_subparsers(dest="factory_command", required=True)
    add = children.add_parser("add", help="Validate and register a factory.json")
    add.add_argument("factory", type=Path); add.add_argument("--id", dest="factory_id"); add.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); add.add_argument("--replace", action="store_true"); add.set_defaults(func=command_factory_add)
    listing = children.add_parser("list", help="List registered factories")
    listing.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); listing.set_defaults(func=command_factories_list)
    inspect = children.add_parser("inspect", help="Inspect a registered factory")
    inspect.add_argument("factory_id"); inspect.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); inspect.set_defaults(func=command_factories_show)
    configure = children.add_parser("configure", help="Create and retain station configuration")
    configure.add_argument("factory_id"); configure.add_argument("--stations", type=Path, required=True); configure.add_argument("--output", type=Path); configure.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); configure.set_defaults(func=command_factories_configure)
    remove = children.add_parser("remove", help="Remove a registration without deleting factory files")
    remove.add_argument("factory_id"); remove.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); remove.add_argument("--force", action="store_true"); remove.set_defaults(func=command_factories_delete)


def _add_legacy_factories_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Retain the older plural spelling used by existing scripts and docs."""
    factories = sub.add_parser("factories", help="Compatibility alias for factory management")
    children = factories.add_subparsers(dest="factories_command", required=True)
    listing = children.add_parser("list"); listing.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); listing.set_defaults(func=command_factories_list)
    show = children.add_parser("show"); show.add_argument("factory_id"); show.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); show.set_defaults(func=command_factories_show)
    register = children.add_parser("register")
    register.add_argument("factory_id"); register.add_argument("factory", type=Path); register.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); register.add_argument("--replace", action="store_true")
    register.set_defaults(func=lambda args: (print(json.dumps(register_factory(args.factory_id, args.factory, args.registry, replace=args.replace), indent=2)) or 0))
    configure = children.add_parser("configure")
    configure.add_argument("factory_id"); configure.add_argument("--stations", type=Path, required=True); configure.add_argument("--output", type=Path); configure.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); configure.set_defaults(func=command_factories_configure)
    delete = children.add_parser("delete")
    delete.add_argument("factory_id"); delete.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); delete.add_argument("--force", action="store_true"); delete.set_defaults(func=command_factories_delete)


def _add_generation_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--factory", type=Path, default=DEFAULT_FACTORY); command.add_argument("--output", type=Path, default=DEFAULT_GENERATED)
    command.add_argument("--count", type=int, required=True); command.add_argument("--seed", type=int, default=42); command.add_argument("--duration-ms", type=int, default=28_800_000)


def _add_simulation_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--simulator", type=Path, default=None, help="Optional simulator executable override; otherwise auto-discover/build it."); command.add_argument("--factory", type=Path, default=DEFAULT_FACTORY)
    command.add_argument("--generated", type=Path, default=DEFAULT_GENERATED); command.add_argument("--output", type=Path, default=DEFAULT_RUNS); command.add_argument("--fail-fast", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Digital Twin project control shell")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_factory_commands(sub)
    _add_legacy_factories_commands(sub)
    configure = sub.add_parser("configure", help="Create a factory-specific station configuration")
    configure.add_argument("--factory", type=Path, default=DEFAULT_FACTORY); configure.add_argument("--stations", type=Path, required=True); configure.add_argument("--output", type=Path, required=True); configure.set_defaults(func=command_configure)
    generate_parser = sub.add_parser("generate", help="Generate factory-specific random scenarios"); _add_generation_options(generate_parser); generate_parser.set_defaults(func=command_generate)
    simulate = sub.add_parser("simulate", help="Run generated scenarios through the C++ simulator"); _add_simulation_options(simulate); simulate.set_defaults(func=command_simulate)
    data = sub.add_parser("data", help="Generate, run, inspect, or remove simulator runs")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    data_list = data_sub.add_parser("list"); data_list.add_argument("--runs", type=Path, default=DEFAULT_RUNS); data_list.set_defaults(func=command_data_list)
    data_delete = data_sub.add_parser("delete"); data_delete.add_argument("run_id"); data_delete.add_argument("--runs", type=Path, default=DEFAULT_RUNS); data_delete.add_argument("--force", action="store_true"); data_delete.set_defaults(func=command_data_delete)
    data_generate = data_sub.add_parser("generate"); _add_generation_options(data_generate); data_generate.set_defaults(func=command_generate)
    data_simulate = data_sub.add_parser("simulate"); _add_simulation_options(data_simulate); data_simulate.set_defaults(func=command_simulate)
    models = sub.add_parser("models", help="Inspect, select, or delete model artifacts")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    for name, func in (("list", command_models_list), ("select", command_models_select), ("use", command_models_select), ("delete", command_models_delete)):
        command = models_sub.add_parser(name); command.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
        if name != "list": command.add_argument("model_id")
        if name == "delete": command.add_argument("--force", action="store_true")
        command.set_defaults(func=func)
    train = sub.add_parser("train", help="Train and publish one immutable factory model artifact")
    train.add_argument("model_id"); train.add_argument("--factory", type=Path, default=DEFAULT_FACTORY); train.add_argument("--factory-id"); train.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); train.add_argument("--runs", type=Path, default=DEFAULT_RUNS); train.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT); train.add_argument("--seed", type=int, default=42); train.add_argument("--threshold-objective", choices=("f1", "f2"), default="f2"); train.add_argument("--replace", action="store_true"); train.add_argument("--force", action="store_true"); train.set_defaults(func=command_train)
    run = sub.add_parser("run", help="Run a trained factory model against prescribed or random data")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    prescribed = run_sub.add_parser("prescribed", help="Causally replay an existing completed run")
    prescribed.add_argument("--run-dir", type=Path, required=True); prescribed.add_argument("--output", type=Path, required=True); prescribed.add_argument("--run-id"); prescribed.add_argument("--model-id"); prescribed.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT); prescribed.add_argument("--base-history", type=Path, default=PACKAGE_ROOT / "data" / "calibration" / "history", help="Prior completed runs used only when BASE model needs DARK calibration."); prescribed.add_argument("--mult", type=float, default=60.0); prescribed.add_argument("--unpaced", action="store_true"); prescribed.add_argument("--force", action="store_true"); prescribed.set_defaults(func=command_run_prescribed)
    random_run = run_sub.add_parser("random", help="Generate, simulate, then causally replay a new run")
    random_run.add_argument("--factory", type=Path, default=DEFAULT_FACTORY); random_run.add_argument("--simulator", type=Path, default=None, help="Optional simulator executable override; otherwise auto-discover/build it."); random_run.add_argument("--generated", type=Path, default=DEFAULT_GENERATED / "random_test"); random_run.add_argument("--runs", type=Path, default=DEFAULT_RUNS / "random_test"); random_run.add_argument("--output", type=Path, required=True); random_run.add_argument("--model-id"); random_run.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT); random_run.add_argument("--base-history", type=Path, default=PACKAGE_ROOT / "data" / "calibration" / "history"); random_run.add_argument("--seed", type=int, default=42); random_run.add_argument("--duration-ms", type=int, default=28_800_000); random_run.add_argument("--mult", type=float, default=60.0); random_run.add_argument("--unpaced", action="store_true"); random_run.add_argument("--force", action="store_true"); random_run.set_defaults(func=command_run_random)
    system = sub.add_parser("system", help="Coordinate bottleneck + defect prediction against one simulator clock")
    system_sub = system.add_subparsers(dest="system_command", required=True)
    system_models = system_sub.add_parser("models", help="Inspect or atomically select matching bottleneck + defect artifacts")
    system_models_sub = system_models.add_subparsers(dest="system_models_command", required=True)
    system_models_list = system_models_sub.add_parser("list")
    system_models_list.add_argument("--bottleneck-artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    system_models_list.add_argument("--defect-artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    system_models_list.set_defaults(func=command_system_models_list)
    system_models_use = system_models_sub.add_parser("use")
    system_models_use.add_argument("model_id")
    system_models_use.add_argument("--bottleneck-artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    system_models_use.add_argument("--defect-artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    system_models_use.set_defaults(func=command_system_models_use)

    system_status = system_sub.add_parser("status", help="Show dual-runtime readiness, selected models, and last health")
    system_status.add_argument("--run-dir", type=Path, default=PACKAGE_ROOT / "data" / "input" / "current_run")
    system_status.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "runtime_output")
    system_status.add_argument("--bottleneck-artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    system_status.add_argument("--defect-artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    system_status.set_defaults(func=command_system_status)

    system_run = system_sub.add_parser("run", help="Run both prediction consumers with separate synchronized outputs")
    system_run_sub = system_run.add_subparsers(dest="system_run_command", required=True)

    def _add_dual_common(command):
        command.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "runtime_output")
        command.add_argument("--run-id")
        command.add_argument("--bottleneck-model-id")
        command.add_argument("--defect-model-id")
        command.add_argument("--bottleneck-artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
        command.add_argument("--defect-artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
        command.add_argument("--history-root", type=Path, default=PACKAGE_ROOT / "data" / "calibration" / "history")
        command.add_argument("--particles", type=int, default=3000)
        command.add_argument("--explain-mode", choices=("off", "warnings", "all"), default="all")
        command.add_argument("--shap-top-k", type=int, default=3)
        command.add_argument("--force", action="store_true")

    system_prescribed = system_run_sub.add_parser("prescribed", help="Run both predictors in parallel on one completed simulator run")
    system_prescribed.add_argument("--run-dir", type=Path, required=True)
    _add_dual_common(system_prescribed)
    system_prescribed.set_defaults(func=command_system_run_prescribed)

    system_live = system_run_sub.add_parser("live", help="Start both consumers; simulator remains an independent process")
    system_live.add_argument("--run-dir", type=Path, default=PACKAGE_ROOT / "data" / "input" / "current_run")
    _add_dual_common(system_live)
    system_live.set_defaults(run_id="CURRENT_RUN")
    system_live.add_argument("--wait-seconds", type=float, default=120.0)
    system_live.add_argument("--poll-ms", type=float, default=50.0)
    system_live.add_argument(
        "--failure-policy",
        choices=("isolate", "fail-fast"),
        default="isolate",
        help=(
            "isolate=keep the healthy ML consumer running if its peer fails (default for live); "
            "fail-fast=stop both consumers on the first failure"
        ),
    )
    system_live.set_defaults(func=command_system_run_live)

    system_random = system_run_sub.add_parser("random", help="Generate one run, simulate it, then validate both predictors")
    system_random.add_argument("--factory", type=Path, default=DEFAULT_FACTORY)
    system_random.add_argument("--simulator", type=Path, default=None)
    system_random.add_argument("--generated", type=Path, default=DEFAULT_GENERATED / "dual_random_test")
    system_random.add_argument("--runs", type=Path, default=DEFAULT_RUNS / "dual_random_test")
    system_random.add_argument("--seed", type=int, default=42)
    system_random.add_argument("--duration-ms", type=int, default=28_800_000)
    system_random.add_argument(
        "--mult", type=_playback_speed, default=1.0,
        help=f"Playback speed: simulated time advances this many times faster than "
             f"wall-clock time ({PLAYBACK_SPEED_MIN}x-{PLAYBACK_SPEED_MAX}x, default 1.0 "
             "= real-time). Paces both consumers against the shared event timeline.",
    )
    _add_dual_common(system_random)
    system_random.set_defaults(func=command_system_run_random)

    defects = sub.add_parser("defects", help="Defect prediction control plane (parallel to bottlenecks)")
    defects_sub = defects.add_subparsers(dest="defects_command", required=True)
    defect_models = defects_sub.add_parser("models", help="Inspect/select immutable defect model artifacts")
    defect_models_sub = defect_models.add_subparsers(dest="defect_models_command", required=True)
    for name, func in (("list", command_defect_models_list), ("select", command_defect_models_select), ("use", command_defect_models_select), ("delete", command_defect_models_delete)):
        command = defect_models_sub.add_parser(name)
        command.add_argument("--artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
        if name != "list": command.add_argument("model_id")
        if name == "delete": command.add_argument("--force", action="store_true")
        command.set_defaults(func=func)
    defect_train = defects_sub.add_parser("train", help="Train/publish an immutable factory-specific defect model")
    defect_train.add_argument("model_id")
    defect_train.add_argument("--factory", type=Path)
    defect_train.add_argument("--factory-id")
    defect_train.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    defect_train.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    defect_train.add_argument("--artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    defect_train.add_argument("--validation-fraction", type=float, default=0.25)
    defect_train.add_argument("--seed", type=int, default=42)
    defect_train.add_argument("--particles", type=int, default=3000)
    defect_train.add_argument("--continuation-iterations", type=int, default=100)
    defect_train.add_argument("--replace", action="store_true")
    defect_train.add_argument("--force", action="store_true")
    defect_train.set_defaults(func=command_defect_train)
    defect_run = defects_sub.add_parser("run", help="Run defect prediction against simulator data")
    defect_run_sub = defect_run.add_subparsers(dest="defect_run_command", required=True)
    defect_prescribed = defect_run_sub.add_parser("prescribed", help="Replay one completed simulator run through defect prediction")
    defect_prescribed.add_argument("--run-dir", type=Path, required=True)
    defect_prescribed.add_argument("--output", type=Path, default=DEFAULT_DEFECT_OUTPUT)
    defect_prescribed.add_argument("--run-id")
    defect_prescribed.add_argument("--model-id")
    defect_prescribed.add_argument("--artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    defect_prescribed.add_argument("--history-root", type=Path, default=PACKAGE_ROOT / "data" / "calibration" / "history")
    defect_prescribed.add_argument("--particles", type=int, default=3000)
    defect_prescribed.add_argument("--explain-mode", choices=("off", "warnings", "all"), default="warnings")
    defect_prescribed.add_argument("--shap-top-k", type=int, default=3)
    defect_prescribed.add_argument("--force", action="store_true")
    defect_prescribed.set_defaults(func=command_defect_run_prescribed)
    defect_live = defect_run_sub.add_parser("live", help="Tail the shared simulator public bus in parallel with bottlenecks")
    defect_live.add_argument("--run-dir", type=Path, default=PACKAGE_ROOT / "data" / "input" / "current_run")
    defect_live.add_argument("--output", type=Path, default=DEFAULT_DEFECT_OUTPUT)
    defect_live.add_argument("--run-id", default="CURRENT_RUN")
    defect_live.add_argument("--model-id")
    defect_live.add_argument("--artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    defect_live.add_argument("--explain-mode", choices=("off", "warnings", "all"), default="warnings")
    defect_live.add_argument("--shap-top-k", type=int, default=3)
    defect_live.add_argument("--wait-seconds", type=float, default=120.0)
    defect_live.add_argument("--poll-ms", type=float, default=50.0)
    defect_live.add_argument("--live-batch-size", type=int, default=256)
    defect_live.set_defaults(func=command_defect_run_live)
    defect_status = defects_sub.add_parser("status", help="Show selected defect model, factories, and data-flow readiness")
    defect_status.add_argument("--artifact-root", type=Path, default=DEFAULT_DEFECT_ARTIFACT_ROOT)
    defect_status.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    defect_status.set_defaults(func=command_defect_status)
    status = sub.add_parser("status", help="Show selected model and default paths")
    status.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT); status.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY); status.set_defaults(func=command_status)
    shell = sub.add_parser("shell", help="Start the interactive cross-platform Python shell"); shell.set_defaults(func=lambda _: interactive_shell(parser))
    return parser


def interactive_shell(parser: argparse.ArgumentParser) -> int:
    print("Digital Twin Shell. Type 'help' for commands, or 'exit' to leave.")
    while True:
        try:
            line = input("dt> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); return 0
        if not line:
            continue
        if line.lower() in {"quit", "exit"}:
            return 0
        if line.lower() in {"help", "?"}:
            parser.print_help(); continue
        try:
            args = parser.parse_args(shlex.split(line))
            if args.command == "shell": print("Already in the interactive shell.")
            else: args.func(args)
        except SystemExit:
            continue
        except Exception as error:
            print(f"ERROR: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is not None and not argv: return interactive_shell(parser)
    if argv is None and len(sys.argv) == 1: return interactive_shell(parser)
    args = parser.parse_args(argv)
    try: return int(args.func(args))
    except Exception as error: parser.exit(2, f"ERROR: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
