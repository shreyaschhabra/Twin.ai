"""The single seam between the dashboard and the existing Digital Twin system.

Nothing else in :mod:`dashboard` may import the simulator, the scenario generator, the
orchestrator, ``system_runtime``, or ``cli``. Keeping those imports here means the
existing implementation can move without the dashboard noticing, and it makes the
dependency direction obvious: the dashboard depends on the system, never the reverse.

What this adapter does **not** do:

* It does not simulate. The C++ simulator remains the only simulator.
* It does not generate scenarios. ``simulation.training.scenario_generator.generate``
  remains the only scenario generator.
* It does not implement run pacing/multipliers. Those live in the existing runtime
  entry points (``--mult`` / ``--unpaced`` on ``cli.py run``).
* It does not modify ``cli.py``.

Execution boundary
------------------
Preparing a run (scenario generation + simulation) is reusable in-process today and is
exposed through :meth:`ExistingRuntimeAdapter.prepare_random_run`. Driving the
*coordinated prediction* stage is deliberately left as a documented boundary: the
existing entry point is ``cli.py system run random``, which composes generation,
simulation and ``system_runtime.run_dual_prescribed`` with argument validation that
lives inside ``cli.py``. Rather than duplicate that composition,
:meth:`plan_random_run` returns the exact command the operator (or a later dashboard
iteration) should invoke, and :meth:`execute_planned_run` raises
:class:`AdapterBoundary` describing it.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The runtime labels stations as ``S{id + 1}``: factory station id 0 is ``S01``.
#: Verified against a completed run's ``stations.csv`` and ``dz.csv``.
def station_runtime_label(station_id: int) -> str:
    """Runtime station label for a ``factory.json`` station id."""
    return f"S{int(station_id) + 1:02d}"


#: Environment the existing consumers need on Windows. Several upstream modules
#: (``bottlenecks_prediction/dark_zone/*.py``) print non-ASCII glyphs; when their stdout
#: is redirected to a log file Python falls back to the cp1252 locale encoding and the
#: consumer dies with a UnicodeEncodeError. UTF-8 mode prevents that.
RUN_ENVIRONMENT: dict[str, str] = {"PYTHONUTF8": "1"}

#: Playback-speed bounds for the coordinated pathway's ``--mult``. Mirrors
#: ``cli.py``'s ``PLAYBACK_SPEED_MIN``/``PLAYBACK_SPEED_MAX`` -- duplicated rather than
#: imported so the adapter's preflight can reject an out-of-range value before a
#: subprocess is even built, without adding a second import path into ``cli.py``.
PLAYBACK_SPEED_MIN = 0.75
PLAYBACK_SPEED_MAX = 20.0

#: Files ``cli.py:_run_directory`` requires before it will accept a run directory.
COMPLETED_RUN_FILES: tuple[str, ...] = (
    "stations.csv",
    "units.csv",
    "station_events.csv",
    "run_metadata.json",
)

#: Additional files ``system_runtime._completed_run_preflight`` requires for a
#: coordinated (bottleneck + defect) replay.
COORDINATED_RUN_FILES: tuple[str, ...] = COMPLETED_RUN_FILES + (
    "runtime_events.csv",
    "dz.csv",
    "station_checkpoints.csv",
)

#: Coordinated runtime outputs, mirroring ``system_runtime.output_paths``.
BOTTLENECK_STREAM = "bottleneck_predictions.jsonl"
DEFECT_STREAM = "defect_predictions.jsonl"
SYSTEM_HEALTH = "system_health.json"
SYSTEM_RUN_MANIFEST = "system_run_manifest.json"


class AdapterBoundary(NotImplementedError):
    """Raised where invoking existing functionality would require changing it.

    Carries the CLI command that performs the operation today.
    """

    def __init__(self, message: str, command: list[str] | None = None):
        super().__init__(message)
        self.command = command or []

    @property
    def command_line(self) -> str:
        return " ".join(self.command)


@dataclass(frozen=True)
class CompletedRun:
    """A completed simulator run directory found on disk."""

    run_id: str
    path: Path
    is_coordinated_ready: bool
    missing: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


#: Coordinated bottleneck + defect run (``cli.py system run random``). Replay is not
#: paced, so no multiplier argument exists on this pathway.
PATHWAY_COORDINATED = "coordinated"

#: Bottleneck-only run (``cli.py run random``), which exposes ``--mult`` / ``--unpaced``.
PATHWAY_BOTTLENECK = "bottleneck"


@dataclass(frozen=True)
class ModelCoverage:
    """Whether a trained bottleneck model can score every station in a factory.

    A model's ``station_id`` categorical encoder only learns levels present in its
    training data. Stations inside a DARK corridor emit no direct observations, so a
    model trained without reconstructed DARK rows never learns those levels -- yet the
    runtime does emit ``DARK_CORRIDOR`` predictions for them. The result is a run that
    completes and then fails validation with "unknown model-category outputs". Checking
    up front is the difference between a command that works and one that wastes a run.
    """

    model_id: str
    usable: bool
    missing_labels: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class RandomRunPlan:
    """Everything needed to execute one random run through the existing pipeline.

    Nothing here has been executed. It is a description, suitable for showing an
    operator and for later hand-off to the existing entry point.
    """

    pathway: str
    factory_path: Path
    generated_dir: Path
    runs_dir: Path
    output_dir: Path
    run_id: str
    seed: int
    duration_ms: int
    command: list[str]
    #: Playback speed the command actually executes at, on both pathways: the
    #: simulated-time-to-wall-clock ratio passed as ``--mult``. None only when no plan
    #: has been built yet (the dataclass default; :meth:`plan_random_run` always sets it).
    multiplier: float | None = None
    #: DARK-corridor particle filter budget used by the coordinated runtime.
    particles: int = 3000
    #: Environment variables the command needs; rendered into the displayed command line.
    environment: dict[str, str] = field(default_factory=dict)
    #: Preflight problems that would make the command fail. Empty means it should run.
    blockers: tuple[str, ...] = ()
    #: Things the operator should know that do not prevent the run.
    notes: tuple[str, ...] = ()

    @property
    def runnable(self) -> bool:
        return not self.blockers

    @property
    def expected_run_dir(self) -> Path:
        """``cli.py`` writes the single generated run as ``run_0001``."""
        return self.runs_dir / "run_0001"

    def command_line(self, shell: str = "powershell") -> str:
        """Render a copy-pasteable command for ``shell``.

        ``shell`` is ``"powershell"``, ``"cmd"`` or ``"bash"``. Paths are quoted and the
        required environment variables are prefixed in that shell's syntax, so the
        rendered string can be pasted as-is.
        """
        if shell == "powershell":
            prefix = "".join(f'$env:{k}="{v}"; ' for k, v in sorted(self.environment.items()))
            body = " ".join(_quote_powershell(part) for part in self.command)
        elif shell == "cmd":
            prefix = "".join(f"set {k}={v} && " for k, v in sorted(self.environment.items()))
            body = " ".join(_quote_cmd(part) for part in self.command)
        elif shell == "bash":
            prefix = "".join(f"{k}={v} " for k, v in sorted(self.environment.items()))
            body = " ".join(shlex.quote(part) for part in self.command)
        else:
            raise ValueError(f"Unknown shell: {shell!r}")
        return prefix + body

    def subprocess_environment(self) -> dict[str, str]:
        """The environment to pass to ``subprocess`` for programmatic execution."""
        return {**os.environ, **self.environment}


def _quote_powershell(part: str) -> str:
    if part and not any(ch in part for ch in ' \t"\'`$&|<>()'):
        return part
    escaped = part.replace("'", "''")
    return f"'{escaped}'"


def _quote_cmd(part: str) -> str:
    return f'"{part}"' if (" " in part or "\t" in part) else part


class ExistingRuntimeAdapter:
    """Read-only discovery plus a narrow, documented execution seam."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    # -- import seam -------------------------------------------------------------------
    #
    # Imports are lazy and failure-tolerant: the dashboard must start even when the ML
    # stack is not installed, so a missing optional dependency degrades a feature rather
    # than crashing the app.

    def _ensure_sys_path(self) -> None:
        for candidate in (self.project_root, self.project_root / "simulation"):
            text = str(candidate)
            if candidate.is_dir() and text not in sys.path:
                sys.path.insert(0, text)

    def scenario_generator(self) -> Callable[..., Path] | None:
        """The existing ``simulation.training.scenario_generator.generate``."""
        self._ensure_sys_path()
        try:
            from simulation.training.scenario_generator import generate
        except ImportError as error:  # pragma: no cover - environment dependent
            logger.warning("existing scenario generator unavailable: %s", error)
            return None
        return generate

    def run_orchestrator(self) -> Callable[..., Path] | None:
        """The existing ``simulation.training.orchestrator.run_generated``."""
        self._ensure_sys_path()
        try:
            from simulation.training.orchestrator import run_generated
        except ImportError as error:  # pragma: no cover - environment dependent
            logger.warning("existing run orchestrator unavailable: %s", error)
            return None
        return run_generated

    def system_runtime(self):
        """The existing coordinated runtime module, or None when unimportable."""
        self._ensure_sys_path()
        try:
            import system_runtime
        except ImportError as error:  # pragma: no cover - environment dependent
            logger.warning("system_runtime unavailable: %s", error)
            return None
        return system_runtime

    def bottleneck_model_api(self):
        """The existing ``bottlenecks_prediction.factory_models`` module."""
        self._ensure_sys_path()
        package = self.project_root / "bottlenecks_prediction"
        if package.is_dir() and str(package) not in sys.path:
            sys.path.insert(0, str(package))
        try:
            import factory_models
        except ImportError as error:  # pragma: no cover - environment dependent
            logger.warning("bottleneck factory_models unavailable: %s", error)
            return None
        return factory_models

    # -- model preflight -----------------------------------------------------------------

    def bottleneck_model_ids(self) -> list[str]:
        api = self.bottleneck_model_api()
        if api is None:
            return []
        try:
            return [str(entry["id"]) for entry in api.list_models(api.DEFAULT_ARTIFACT_ROOT)]
        except Exception as error:  # pragma: no cover - depends on local artifacts
            logger.warning("could not list bottleneck models: %s", error)
            return []

    def selected_bottleneck_model_id(self) -> str | None:
        api = self.bottleneck_model_api()
        if api is None:
            return None
        try:
            return str(api.selected_model_id(api.DEFAULT_ARTIFACT_ROOT))
        except Exception as error:  # pragma: no cover - depends on local artifacts
            logger.warning("could not read selected bottleneck model: %s", error)
            return None

    def _model_artifact_paths(self, model_id: str) -> dict[str, Path] | None:
        api = self.bottleneck_model_api()
        if api is None:
            return None
        try:
            return api.model_paths(model_id, api.DEFAULT_ARTIFACT_ROOT)
        except Exception as error:
            logger.warning("could not resolve bottleneck model %s: %s", model_id, error)
            return None

    def _model_station_levels(self, model_id: str) -> set[str] | None:
        """Station labels a model's categorical encoder knows, or None if unreadable."""
        paths = self._model_artifact_paths(model_id)
        if paths is None:
            return None
        # The base artifact names the bundle "bundle"; factory-trained ones use
        # "model_bundle".
        bundle_path = paths.get("bundle") or paths.get("model_bundle")
        if bundle_path is None:
            return None
        try:
            import joblib

            bundle = joblib.load(bundle_path)
            levels = bundle.get("category_levels", {}).get("station_id")
        except Exception as error:
            logger.warning("could not inspect bottleneck model %s: %s", model_id, error)
            return None
        return {str(level) for level in levels} if levels else None

    def _model_dark_stations(self, model_id: str) -> set[str] | None:
        """DARK station labels recorded in a factory-trained model's contract.

        The runtime derives configured coverage as DARK -> NONE, LIGHT -> NORMAL, so the
        NONE rows of ``configured_stations.csv`` are exactly the corridor the model was
        trained against. Returns None when the model carries no such contract (base).
        """
        paths = self._model_artifact_paths(model_id)
        if paths is None:
            return None
        contract = paths.get("configured_stations")
        if contract is None or not Path(contract).is_file():
            return None
        import csv

        try:
            with Path(contract).open(encoding="utf-8", newline="") as stream:
                return {
                    str(row["station_id"])
                    for row in csv.DictReader(stream)
                    if row.get("sensor_coverage") == "NONE"
                }
        except (OSError, KeyError) as error:
            logger.warning("could not read model contract for %s: %s", model_id, error)
            return None

    @staticmethod
    def _factory_dark_labels(factory: dict[str, Any]) -> set[str]:
        labels: set[str] = set()
        for zone in factory.get("darkZones") or []:
            if not isinstance(zone, dict):
                continue
            start, end = zone.get("startStationId"), zone.get("endStationId")
            if isinstance(start, int) and isinstance(end, int):
                labels.update(station_runtime_label(i) for i in range(start, end + 1))
        return labels

    def check_bottleneck_model(self, factory: dict[str, Any], model_id: str) -> ModelCoverage:
        """Verify a model can actually score this factory.

        Two independent failure modes are checked, both of which otherwise surface only
        after a full run has been executed:

        * a DARK-corridor extent that differs from the model's recorded contract, which
          fails as ``S15:sensor_coverage expected='NONE' current='NORMAL'``;
        * missing ``station_id`` categorical levels, which fails as
          ``Found N unknown model-category outputs``.

        The source station never receives a bottleneck prediction, so it is excluded.
        """
        stations = factory.get("stations") or []
        required = {
            station_runtime_label(station["id"])
            for station in stations
            if isinstance(station, dict) and station.get("source") is not True
        }

        contract_dark = self._model_dark_stations(model_id)
        if contract_dark is not None:
            factory_dark = self._factory_dark_labels(factory)
            if contract_dark != factory_dark:
                return ModelCoverage(
                    model_id=model_id,
                    usable=False,
                    reason=(
                        f"Model {model_id!r} was trained against DARK corridor "
                        f"{', '.join(sorted(contract_dark)) or '(none)'}, but this factory's "
                        f"corridor is {', '.join(sorted(factory_dark)) or '(none)'}. The run "
                        "would fail its factory-contract check."
                    ),
                )

        levels = self._model_station_levels(model_id)
        if levels is None:
            return ModelCoverage(
                model_id=model_id,
                usable=False,
                reason=f"Model {model_id!r} could not be inspected.",
            )
        missing = sorted(required - levels)
        if missing:
            return ModelCoverage(
                model_id=model_id,
                usable=False,
                missing_labels=tuple(missing),
                reason=(
                    f"Model {model_id!r} was trained without station(s) "
                    f"{', '.join(missing)}; the run would complete and then fail "
                    "validation with 'unknown model-category outputs'."
                ),
            )
        return ModelCoverage(model_id=model_id, usable=True)

    def choose_bottleneck_model(self, factory: dict[str, Any]) -> tuple[str | None, list[str]]:
        """Pick a model that can actually score this factory, preferring the selected one.

        Returns ``(model_id, notes)``. ``model_id`` is None when nothing available works.
        """
        notes: list[str] = []
        selected = self.selected_bottleneck_model_id()
        candidates = [model_id for model_id in (selected, "base") if model_id]
        candidates += [
            model_id for model_id in self.bottleneck_model_ids() if model_id not in candidates
        ]

        for model_id in candidates:
            coverage = self.check_bottleneck_model(factory, model_id)
            if coverage.usable:
                if selected and model_id != selected:
                    notes.append(
                        f"The selected model {selected!r} cannot score this factory, so "
                        f"{model_id!r} is used for this run via --bottleneck-model-id. "
                        "Your saved model selection is unchanged."
                    )
                return model_id, notes
            if coverage.reason:
                notes.append(coverage.reason)
        return None, notes

    def train_model_command(self, factory_path: str | Path, model_id: str = "factory-b") -> list[str]:
        """The existing command that publishes a model matching a given factory.

        Offered as the remedy when no available model can score the configured factory.
        Training needs completed runs generated from that same factory.
        """
        return [
            sys.executable,
            str(self.project_root / "cli.py"),
            "train", model_id,
            "--factory", str(Path(factory_path)),
            "--runs", str(self.project_root / "simulation" / "training" / "runs"),
        ]

    def defect_dependencies_ready(self) -> tuple[bool, str | None]:
        """Whether the defect consumer's third-party dependencies are importable."""
        try:
            import catboost  # noqa: F401
        except ImportError:
            return False, (
                "The defect consumer needs 'catboost', which is not installed. "
                "Install it with: py -m pip install -r Defect_Model/requirements.txt"
            )
        return True, None

    # -- factory discovery -------------------------------------------------------------

    def default_factory_path(self) -> Path:
        """Mirrors ``cli.py:DEFAULT_FACTORY``."""
        return self.project_root / "simulation" / "config" / "factory.json"

    def discover_factory(self, configured: str | Path | None = None) -> Path | None:
        """Return the configured factory if it exists, else the repository default."""
        for candidate in (configured, self.default_factory_path()):
            if candidate is None:
                continue
            path = Path(candidate)
            if path.is_file():
                return path.resolve()
        return None

    # -- simulator discovery -----------------------------------------------------------

    def simulator_candidates(self) -> list[Path]:
        """Build-output locations the existing tooling uses, in preference order."""
        build = self.project_root / "simulation" / "build"
        if sys.platform.startswith("win"):
            return [
                build / "Release" / "simulation.exe",
                build / "Debug" / "simulation.exe",
                build / "simulation.exe",
            ]
        return [
            build / "simulation",
            build / "Release" / "simulation",
            build / "Debug" / "simulation",
        ]

    def resolve_simulator(self) -> Path | None:
        """Locate an already-built simulator. Never builds -- that is the CLI's job.

        ``cli.py:_resolve_simulator`` will invoke CMake when the binary is missing; the
        dashboard deliberately does not, because a page render must never kick off a
        build.
        """
        for candidate in self.simulator_candidates():
            if candidate.is_file():
                return candidate.resolve()
        return None

    def simulator_available(self) -> bool:
        return self.resolve_simulator() is not None

    # -- completed run inspection ------------------------------------------------------

    def missing_run_files(self, run_dir: str | Path, *, coordinated: bool = False) -> tuple[str, ...]:
        """Names of the required artifacts absent from ``run_dir``."""
        path = Path(run_dir)
        required = COORDINATED_RUN_FILES if coordinated else COMPLETED_RUN_FILES
        return tuple(name for name in required if not (path / name).is_file())

    def is_completed_run(self, run_dir: str | Path) -> bool:
        """True when ``run_dir`` satisfies the base completed-run contract."""
        return not self.missing_run_files(run_dir)

    def is_coordinated_ready(self, run_dir: str | Path) -> bool:
        """True when ``run_dir`` can feed a coordinated bottleneck + defect replay."""
        return not self.missing_run_files(run_dir, coordinated=True)

    def inspect_run(self, run_dir: str | Path) -> CompletedRun | None:
        """Describe one run directory, or None when it is not a completed run."""
        path = Path(run_dir)
        if not path.is_dir():
            return None
        missing = self.missing_run_files(path)
        if missing:
            return None
        return CompletedRun(
            run_id=path.name,
            path=path.resolve(),
            is_coordinated_ready=self.is_coordinated_ready(path),
            missing=self.missing_run_files(path, coordinated=True),
            metadata=self.read_run_metadata(path) or {},
        )

    def list_completed_runs(self, runs_root: str | Path | None) -> list[CompletedRun]:
        """Find completed run directories beneath ``runs_root`` (one level deep).

        The existing pipeline writes batches as ``<runs_root>/<batch>/run_0001`` for
        ``cli.py run random`` and ``<runs_root>/run_NNNN`` for training batches, so both
        shapes are scanned.
        """
        if runs_root is None:
            return []
        root = Path(runs_root)
        if not root.is_dir():
            return []

        found: list[CompletedRun] = []
        seen: set[Path] = set()
        try:
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                run = self.inspect_run(child)
                if run is not None:
                    if run.path not in seen:
                        seen.add(run.path)
                        found.append(run)
                    continue
                for grandchild in sorted(child.iterdir()):
                    if not grandchild.is_dir():
                        continue
                    nested = self.inspect_run(grandchild)
                    if nested is not None and nested.path not in seen:
                        seen.add(nested.path)
                        found.append(nested)
        except OSError as error:
            logger.warning("could not scan runs root %s: %s", root, error)
        return found

    # -- artifact readers ---------------------------------------------------------------

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("could not read %s: %s", path, error)
            return None
        return payload if isinstance(payload, dict) else None

    def read_run_metadata(self, run_dir: str | Path) -> dict[str, Any] | None:
        return self._read_json(Path(run_dir) / "run_metadata.json")

    def prediction_output_paths(self, output_dir: str | Path) -> dict[str, Path]:
        """Coordinated runtime output locations.

        Delegates to ``system_runtime.output_paths`` when importable so the dashboard
        cannot drift from the runtime's own layout, and falls back to the documented
        filenames otherwise.
        """
        root = Path(output_dir)
        runtime = self.system_runtime()
        if runtime is not None:
            try:
                paths = runtime.output_paths(root)
                return {
                    "root": paths.root,
                    "bottleneck": paths.bottleneck_output,
                    "defect": paths.defect_output,
                    "health": paths.health,
                    "manifest": paths.manifest,
                }
            except Exception as error:  # pragma: no cover - defensive
                logger.warning("system_runtime.output_paths failed: %s", error)
        return {
            "root": root,
            "bottleneck": root / BOTTLENECK_STREAM,
            "defect": root / DEFECT_STREAM,
            "health": root / SYSTEM_HEALTH,
            "manifest": root / SYSTEM_RUN_MANIFEST,
        }

    def read_system_health(self, output_dir: str | Path) -> dict[str, Any] | None:
        """``system_health.json`` -- the authoritative coordinated runtime health source."""
        return self._read_json(self.prediction_output_paths(output_dir)["health"])

    def read_system_manifest(self, output_dir: str | Path) -> dict[str, Any] | None:
        """``system_run_manifest.json`` -- the authoritative completed-run summary."""
        return self._read_json(self.prediction_output_paths(output_dir)["manifest"])

    # -- run preparation / execution ----------------------------------------------------

    def plan_random_run(
        self,
        *,
        factory_path: str | Path,
        generated_dir: str | Path,
        runs_dir: str | Path,
        output_dir: str | Path,
        run_id: str,
        seed: int = 42,
        duration_ms: int = 28_800_000,
        multiplier: float = 1.0,
        particles: int = 3000,
        pathway: str = PATHWAY_COORDINATED,
        factory: dict[str, Any] | None = None,
    ) -> RandomRunPlan:
        """Describe one random run without executing anything.

        The command is an existing ``cli.py`` entry point, so the plan a dashboard shows
        and the work the system does cannot diverge. ``multiplier`` (the operator's
        "Playback Speed") is the actual pacing both pathways execute at -- on
        :data:`PATHWAY_COORDINATED` it becomes ``system run random --mult``, which paces
        both prediction consumers against the run's shared event timeline; on
        :data:`PATHWAY_BOTTLENECK` it becomes the bottleneck-only replay's own
        ``--mult``. On the coordinated pathway it must fall within
        :data:`PLAYBACK_SPEED_MIN`-:data:`PLAYBACK_SPEED_MAX`; an out-of-range value is
        reported as a blocker rather than silently clamped.

        When ``factory`` is supplied the plan is **preflighted**: the destination
        directories must be free, a bottleneck model that can score every station is
        selected explicitly, and the defect consumer's dependencies are checked. The
        goal is that a rendered command either runs, or is accompanied by the reason it
        cannot -- never a command that fails on paste.
        """
        if pathway not in (PATHWAY_COORDINATED, PATHWAY_BOTTLENECK):
            raise ValueError(f"Unknown run pathway: {pathway!r}")

        generated_dir = Path(generated_dir)
        runs_dir = Path(runs_dir)
        output_dir = Path(output_dir)
        blockers: list[str] = []
        notes: list[str] = []

        # cli.py refuses to write into an occupied generated/runs directory.
        if generated_dir.exists() and any(generated_dir.iterdir()):
            blockers.append(
                f"Generated-input directory already contains files: {generated_dir}. "
                "Use a new run id."
            )
        if (runs_dir / "run_0001").exists():
            blockers.append(
                f"Run destination already exists: {runs_dir / 'run_0001'}. Use a new run id."
            )
        if not self.simulator_available():
            blockers.append(
                "The C++ simulator is not built. Build it with: "
                "cmake -S simulation -B simulation/build && "
                "cmake --build simulation/build --config Release"
            )

        model_id: str | None = None
        if factory is not None:
            model_id, model_notes = self.choose_bottleneck_model(factory)
            if model_id is None:
                blockers.append(
                    "No available bottleneck model can score this factory, so no run "
                    "command would succeed. Train one against this factory first "
                    "(it needs completed runs generated from the same factory): "
                    + " ".join(self.train_model_command(factory_path))
                )
                blockers.extend(model_notes)
            else:
                notes.extend(model_notes)

        if pathway == PATHWAY_COORDINATED:
            ready, message = self.defect_dependencies_ready()
            if not ready and message:
                blockers.append(message)
            if not (PLAYBACK_SPEED_MIN <= float(multiplier) <= PLAYBACK_SPEED_MAX):
                blockers.append(
                    f"Playback speed must be between {PLAYBACK_SPEED_MIN}x and "
                    f"{PLAYBACK_SPEED_MAX}x (got {float(multiplier):g}x)."
                )

        cli = str(self.project_root / "cli.py")
        shared = [
            "--factory", str(Path(factory_path)),
            "--generated", str(generated_dir),
            "--runs", str(runs_dir),
            "--seed", str(int(seed)),
            "--duration-ms", str(int(duration_ms)),
        ]
        if pathway == PATHWAY_COORDINATED:
            command = [
                sys.executable, cli, "system", "run", "random",
                *shared,
                "--output-dir", str(output_dir),
                "--run-id", run_id,
                "--particles", str(int(particles)),
                "--mult", str(float(multiplier)),
            ]
            if model_id:
                command += ["--bottleneck-model-id", model_id]
            effective_multiplier: float | None = float(multiplier)
        else:
            command = [
                sys.executable, cli, "run", "random",
                *shared,
                "--output", str(output_dir / BOTTLENECK_STREAM),
                "--mult", str(float(multiplier)),
            ]
            if model_id:
                command += ["--model-id", model_id]
            effective_multiplier = float(multiplier)

        return RandomRunPlan(
            pathway=pathway,
            factory_path=Path(factory_path),
            generated_dir=generated_dir,
            runs_dir=runs_dir,
            output_dir=output_dir,
            run_id=run_id,
            seed=int(seed),
            duration_ms=int(duration_ms),
            multiplier=effective_multiplier,
            particles=int(particles),
            command=command,
            environment=dict(RUN_ENVIRONMENT),
            blockers=tuple(blockers),
            notes=tuple(notes),
        )

    def prepare_random_run(self, plan: RandomRunPlan, *, progress=None) -> Path:
        """Run the existing scenario generator + simulator orchestrator for ``plan``.

        This is real reuse, not a reimplementation: it calls
        ``simulation.training.scenario_generator.generate`` and
        ``simulation.training.orchestrator.run_generated`` exactly as ``cli.py`` does.
        It stops short of prediction; see :meth:`execute_planned_run`.

        Returns the completed run directory.
        """
        generate = self.scenario_generator()
        run_generated = self.run_orchestrator()
        if generate is None or run_generated is None:
            raise AdapterBoundary(
                "The existing scenario generator/orchestrator could not be imported.",
                plan.command,
            )
        simulator = self.resolve_simulator()
        if simulator is None:
            raise AdapterBoundary(
                "The C++ simulator is not built. Build it with "
                "'cmake -S simulation -B simulation/build && "
                "cmake --build simulation/build --config Release', or run the command "
                "below, which builds it automatically.",
                plan.command,
            )
        if plan.generated_dir.exists() and any(plan.generated_dir.iterdir()):
            raise FileExistsError(
                f"Generated-input directory already contains files: {plan.generated_dir}"
            )
        if plan.expected_run_dir.exists():
            raise FileExistsError(f"Run destination already exists: {plan.expected_run_dir}")

        generate(plan.factory_path, plan.generated_dir, 1, plan.seed, plan.duration_ms,
                 progress=progress)
        run_generated(simulator, plan.factory_path, plan.generated_dir, plan.runs_dir,
                      fail_fast=True, progress=progress)
        return plan.expected_run_dir

    def launch_planned_run(self, plan: RandomRunPlan) -> subprocess.Popen:
        """Start the existing CLI pipeline and return immediately.

        The caller owns the process: it must drain ``stdout`` and ``wait()``. This is
        the seam a non-blocking UI needs -- the dashboard can watch the prediction
        streams the run is writing instead of sitting inside ``communicate()`` until the
        whole pipeline finishes. It still launches the canonical command and nothing
        else; no stage of the pipeline is reimplemented here.
        """
        if not plan.runnable:
            raise RuntimeError("Run preflight failed: " + "; ".join(plan.blockers))
        # ``cli.py system run random`` spawns its own children (the two prediction
        # consumers). Launch it as a killable group so cancelling the run takes the
        # whole tree down rather than orphaning the consumers -- see
        # :mod:`dashboard.process_tree`.
        from dashboard import process_tree

        process = subprocess.Popen(
            plan.command, cwd=self.project_root, env=plan.subprocess_environment(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
            **process_tree.spawn_kwargs(),
        )
        process_tree.track(process)
        return process

    def execute_planned_run(self, plan: RandomRunPlan, *, on_output=None) -> None:
        """Execute the existing CLI pipeline to completion, surfacing its output.

        Blocking. Use :meth:`launch_planned_run` when the caller must stay responsive.
        """
        process = self.launch_planned_run(plan)
        assert process.stdout is not None
        for line in process.stdout:
            if on_output:
                on_output(line.rstrip())
        code = process.wait()
        if code:
            raise RuntimeError(f"Factory runtime exited with code {code}.")

    # -- status -------------------------------------------------------------------------

    def system_status(self, **kwargs) -> dict[str, Any] | None:
        """Delegate to ``system_runtime.system_status`` when it is importable."""
        runtime = self.system_runtime()
        if runtime is None:
            return None
        try:
            return runtime.system_status(**kwargs)
        except Exception as error:  # pragma: no cover - depends on ML stack
            logger.warning("system_runtime.system_status failed: %s", error)
            return None
