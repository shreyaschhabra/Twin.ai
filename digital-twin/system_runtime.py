"""Operational coordinator for synchronized bottleneck + defect inference.

This module deliberately keeps the two prediction streams separate.  It owns only
process lifecycle, shared run identity, health/status metadata, and cross-stream
sanity checks.  The simulator remains an independent process in live mode.
"""
from __future__ import annotations

import csv
import json
import math
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_RUN_DIR = PROJECT_ROOT / "bottlenecks_prediction" / "data" / "input" / "current_run"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "runtime_output"
DEFAULT_BOTTLENECK_ARTIFACT_ROOT = PROJECT_ROOT / "bottlenecks_prediction" / "factory_models"
DEFAULT_DEFECT_ARTIFACT_ROOT = PROJECT_ROOT / "Defect_Model" / "factory_models"
DEFAULT_HISTORY_ROOT = PROJECT_ROOT / "bottlenecks_prediction" / "data" / "calibration" / "history"


@dataclass(frozen=True)
class DualRunPaths:
    root: Path
    bottleneck_output: Path
    defect_output: Path
    bottleneck_log: Path
    defect_log: Path
    health: Path
    manifest: Path


def output_paths(output_dir: str | Path) -> DualRunPaths:
    root = Path(output_dir).expanduser().resolve()
    return DualRunPaths(
        root=root,
        bottleneck_output=root / "bottleneck_predictions.jsonl",
        defect_output=root / "defect_predictions.jsonl",
        bottleneck_log=root / "bottleneck_runtime.log",
        defect_log=root / "defect_runtime.log",
        health=root / "system_health.json",
        manifest=root / "system_run_manifest.json",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _selected_models(
    bottleneck_artifact_root: Path,
    defect_artifact_root: Path,
    bottleneck_model_id: str | None,
    defect_model_id: str | None,
) -> dict[str, str]:
    from bottlenecks_prediction.factory_models import selected_model_id as selected_bottleneck
    from Defect_Model.factory_models import selected_model_id as selected_defect

    return {
        "bottleneck": str(bottleneck_model_id or selected_bottleneck(bottleneck_artifact_root)),
        "defect": str(defect_model_id or selected_defect(defect_artifact_root)),
    }


def _completed_run_preflight(run_dir: Path) -> dict:
    required = {
        "stations.csv",
        "units.csv",
        "station_events.csv",
        "runtime_events.csv",
        "dz.csv",
        "station_checkpoints.csv",
        "run_metadata.json",
    }
    missing = sorted(name for name in required if not (run_dir / name).is_file())
    if missing:
        raise FileNotFoundError(
            f"Completed dual replay requires simulator-v2.1 run files in {run_dir}; missing: "
            + ", ".join(missing)
        )
    return _read_bus_summary(run_dir / "runtime_events.csv")


def _read_bus_summary(path: Path) -> dict:
    required = {"sequence", "timestamp_ms", "record_type", "station_id"}
    count = 0
    first_ts: int | None = None
    last_ts: int | None = None
    last_seq = 0
    record_types: dict[str, int] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"runtime_events.csv missing columns: {sorted(missing)}")
        for row in reader:
            seq = int(row["sequence"])
            if seq != last_seq + 1:
                raise ValueError(
                    f"runtime_events.csv sequence gap/reorder at row {count + 1}: expected {last_seq + 1}, got {seq}"
                )
            ts = int(row["timestamp_ms"])
            if last_ts is not None and ts < last_ts:
                raise ValueError(
                    f"runtime_events.csv timestamp moved backward at sequence {seq}: {ts} < {last_ts}"
                )
            first_ts = ts if first_ts is None else first_ts
            last_ts = ts
            last_seq = seq
            count += 1
            kind = str(row.get("record_type", "")).upper()
            record_types[kind] = record_types.get(kind, 0) + 1
    if count == 0:
        raise ValueError("runtime_events.csv contains no public events")
    return {
        "records": count,
        "first_timestamp_ms": first_ts,
        "last_timestamp_ms": last_ts,
        "record_types": record_types,
    }


def _read_units_and_stations(run_dir: Path) -> tuple[set[str], set[str]]:
    station_ids: set[str] = set()
    unit_ids: set[str] = set()
    with (run_dir / "stations.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            station_ids.add(str(row["station_id"]).strip())
    with (run_dir / "units.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            unit_ids.add(str(row["unit_id"]).strip())
    return station_ids, unit_ids


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise RuntimeError(f"Expected prediction output was not created: {path}")
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON in {path.name} line {line_no}: {exc}") from exc
    if not out:
        raise RuntimeError(f"Prediction output contains zero rows: {path}")
    return out


def validate_synchronized_outputs(
    *,
    run_dir: str | Path,
    run_id: str,
    bottleneck_output: str | Path,
    defect_output: str | Path,
    require_defect_explanations: bool = False,
) -> dict:
    """Validate both independent dashboard streams against one simulator run."""
    run = Path(run_dir).expanduser().resolve()
    bus = _read_bus_summary(run / "runtime_events.csv")
    stations, units = _read_units_and_stations(run)
    bottleneck = _load_jsonl(Path(bottleneck_output).expanduser().resolve())
    defects = _load_jsonl(Path(defect_output).expanduser().resolve())
    first_ts = int(bus["first_timestamp_ms"])
    last_ts = int(bus["last_timestamp_ms"])

    def common(row: dict, subsystem: str, idx: int) -> None:
        if str(row.get("run_id")) != str(run_id):
            raise RuntimeError(
                f"{subsystem} output row {idx} has run_id={row.get('run_id')!r}; expected {run_id!r}"
            )
        station = str(row.get("station_id", ""))
        if station not in stations:
            raise RuntimeError(f"{subsystem} output row {idx} references unknown station {station!r}")
        try:
            ts = int(row["timestamp_ms"])
        except Exception as exc:
            raise RuntimeError(f"{subsystem} output row {idx} has invalid timestamp_ms") from exc
        # PF interval predictions may be between public events, but must stay inside
        # the simulator's public run time window.
        if ts < first_ts or ts > last_ts:
            raise RuntimeError(
                f"{subsystem} output row {idx} timestamp {ts} is outside simulator window [{first_ts}, {last_ts}]"
            )

    bottleneck_routes: dict[str, int] = {}
    bottleneck_warnings = 0
    max_bottleneck_shap_error = 0.0
    for idx, row in enumerate(bottleneck, 1):
        common(row, "bottleneck", idx)
        vehicle = row.get("vehicle_id")
        if vehicle not in (None, "") and str(vehicle) not in units:
            raise RuntimeError(f"bottleneck output row {idx} references unknown unit {vehicle!r}")
        p = float(row["bottleneck_probability"])
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise RuntimeError(f"bottleneck output row {idx} has invalid probability")
        if bool(row["warning"]) != (p >= float(row["decision_threshold"])):
            raise RuntimeError(f"bottleneck output row {idx} warning/threshold mismatch")
        bottleneck_warnings += int(bool(row["warning"]))
        route = str(row.get("route"))
        bottleneck_routes[route] = bottleneck_routes.get(route, 0) + 1
        explanation = row.get("explanation") or {}
        drivers = explanation.get("top_drivers")
        err = explanation.get("probability_additivity_error")
        if not isinstance(drivers, list) or not drivers or err is None:
            raise RuntimeError(f"bottleneck output row {idx} is missing TreeSHAP explanation")
        err = float(err)
        if not math.isfinite(err) or err > 1e-5:
            raise RuntimeError(f"bottleneck output row {idx} has invalid TreeSHAP additivity")
        max_bottleneck_shap_error = max(max_bottleneck_shap_error, err)

    defect_routes: dict[str, int] = {}
    defect_warnings = 0
    defect_explained = 0
    max_defect_shap_error = 0.0
    for idx, row in enumerate(defects, 1):
        common(row, "defect", idx)
        unit = str(row.get("unit_id", ""))
        if unit not in units:
            raise RuntimeError(f"defect output row {idx} references unknown unit {unit!r}")
        p = float(row["defect_probability"])
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise RuntimeError(f"defect output row {idx} has invalid probability")
        if abs(float(row["defect_risk_percent"]) - 100.0 * p) > 1e-8:
            raise RuntimeError(f"defect output row {idx} probability/risk mismatch")
        defect_warnings += int(bool(row.get("warning")))
        route = str(row.get("route"))
        defect_routes[route] = defect_routes.get(route, 0) + 1
        if bool(row.get("explanation_available")):
            defect_explained += 1
            err = row.get("shap_probability_reconstruction_error")
            if err is not None:
                err = float(err)
                if not math.isfinite(err) or err > 1e-5:
                    raise RuntimeError(f"defect output row {idx} has invalid SHAP reconstruction")
                max_defect_shap_error = max(max_defect_shap_error, err)
        elif require_defect_explanations:
            raise RuntimeError(f"defect output row {idx} is missing required CatBoost SHAP explanation")

    # Synchronization is clock/run based, not a one-to-one prediction join.  The
    # two models legitimately emit at different triggers and frequencies.
    return {
        "run_id": str(run_id),
        "simulator": bus,
        "bottleneck": {
            "predictions": len(bottleneck),
            "first_timestamp_ms": min(int(r["timestamp_ms"]) for r in bottleneck),
            "last_timestamp_ms": max(int(r["timestamp_ms"]) for r in bottleneck),
            "routes": bottleneck_routes,
            "warnings": bottleneck_warnings,
            "shap_explanations": len(bottleneck),
            "max_shap_additivity_error": max_bottleneck_shap_error,
        },
        "defect": {
            "predictions": len(defects),
            "first_timestamp_ms": min(int(r["timestamp_ms"]) for r in defects),
            "last_timestamp_ms": max(int(r["timestamp_ms"]) for r in defects),
            "routes": defect_routes,
            "warnings": defect_warnings,
            "shap_explanations": defect_explained,
            "max_shap_reconstruction_error": max_defect_shap_error,
        },
        "synchronization": {
            "same_run_id": True,
            "same_simulator_clock": True,
            "one_to_one_prediction_join_required": False,
            "dashboard_join_keys": ["run_id", "timestamp_ms", "station_id", "unit_id/vehicle_id"],
        },
    }



def validate_single_subsystem_output(
    *,
    run_dir: str | Path,
    run_id: str,
    subsystem: str,
    output: str | Path,
    defect_explain_mode: str = "all",
) -> dict:
    """Validate one surviving prediction stream during degraded operation.

    This is intentionally separate from ``validate_synchronized_outputs``: in a
    degraded live run one ML subsystem may have failed, while the healthy sibling
    is allowed to finish and remains useful to the dashboard.
    """
    name = str(subsystem).strip().lower()
    if name not in {"bottleneck", "defect"}:
        raise ValueError("subsystem must be 'bottleneck' or 'defect'")
    run = Path(run_dir).expanduser().resolve()
    path = Path(output).expanduser().resolve()
    bus = _read_bus_summary(run / "runtime_events.csv")
    stations, units = _read_units_and_stations(run)
    rows = _load_jsonl(path)
    first_ts, last_ts = int(bus["first_timestamp_ms"]), int(bus["last_timestamp_ms"])
    for idx, row in enumerate(rows, 1):
        if str(row.get("run_id")) != str(run_id):
            raise RuntimeError(
                f"{name} output row {idx} has run_id={row.get('run_id')!r}; expected {run_id!r}"
            )
        station = str(row.get("station_id", ""))
        if station not in stations:
            raise RuntimeError(f"{name} output row {idx} references unknown station {station!r}")
        ts = int(row["timestamp_ms"])
        if ts < first_ts or ts > last_ts:
            raise RuntimeError(
                f"{name} output row {idx} timestamp {ts} is outside simulator window [{first_ts}, {last_ts}]"
            )
        uid = row.get("vehicle_id") if name == "bottleneck" else row.get("unit_id")
        if uid not in (None, "") and str(uid) not in units:
            raise RuntimeError(f"{name} output row {idx} references unknown unit {uid!r}")

    if name == "bottleneck":
        from bottlenecks_prediction.run_current import _validate_output as validate_output
        quality = validate_output(path)
    else:
        from Defect_Model.run_current_defects import _validate_output as validate_output
        quality = validate_output(path, explain_mode=str(defect_explain_mode))
    return {
        "subsystem": name,
        "run_id": str(run_id),
        "simulator": bus,
        "first_timestamp_ms": min(int(r["timestamp_ms"]) for r in rows),
        "last_timestamp_ms": max(int(r["timestamp_ms"]) for r in rows),
        **quality,
    }

def _prepare_output_dir(paths: DualRunPaths, *, force: bool) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    managed = [
        paths.bottleneck_output,
        paths.defect_output,
        paths.bottleneck_log,
        paths.defect_log,
        paths.health,
        paths.manifest,
    ]
    existing = [p for p in managed if p.exists()]
    if existing and not force:
        raise FileExistsError(
            "Dual-runtime output already exists: " + ", ".join(p.name for p in existing) + ". Repeat with --force."
        )
    if force:
        for path in managed:
            path.unlink(missing_ok=True)


class _TerminationGuard:
    """Turn an external stop signal into the loop's normal cleanup path.

    ``_run_pair`` already tears down both consumers on any ``BaseException`` (a
    ``KeyboardInterrupt`` from Ctrl-C included). What it does *not* survive is a
    plain ``SIGTERM`` -- ``Popen.terminate()`` on POSIX, or ``kill <pid>`` -- whose
    default action kills this process outright, orphaning ``bp``/``dp``. While this
    guard is active, ``SIGTERM`` (and ``SIGBREAK`` on Windows) instead raises
    ``KeyboardInterrupt`` so the existing ``except BaseException`` block runs and
    both children are terminated.

    The dashboard's own cancel path does not rely on this -- it puts the whole run
    in a Windows Job Object and kills the tree directly -- but a coordinated run
    started any other way still cleans up after itself.
    """

    _SIGNALS = (signal.SIGTERM,) + ((signal.SIGBREAK,) if hasattr(signal, "SIGBREAK") else ())

    def __enter__(self):
        self._previous = {}
        for sig in self._SIGNALS:
            try:
                self._previous[sig] = signal.signal(sig, self._on_signal)
            except (ValueError, OSError):  # not the main thread, or unsupported here
                pass
        return self

    def __exit__(self, *exc_info):
        for sig, handler in self._previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        return False

    @staticmethod
    def _on_signal(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _launch(cmd: list[str], log_path: Path) -> tuple[subprocess.Popen, object]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    kwargs = {
        "cwd": str(PROJECT_ROOT),
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return proc, handle


def _run_pair(
    *,
    bottleneck_cmd: list[str],
    defect_cmd: list[str],
    paths: DualRunPaths,
    health_base: dict,
    failure_policy: str = "fail-fast",
) -> dict:
    """Run both ML consumers with strict or fault-isolated lifecycle policy.

    ``fail-fast`` is intended for CI/validation: either consumer failure stops its
    peer and fails the coordinated run. ``isolate`` is intended for live factory
    operation: a failed consumer is marked unavailable while the healthy sibling
    continues against the same simulator stream. The simulator is always external
    to this coordinator and is never terminated by either policy.
    """
    policy = str(failure_policy).strip().lower()
    if policy not in {"fail-fast", "isolate"}:
        raise ValueError("failure_policy must be 'fail-fast' or 'isolate'")

    bp, b_log = _launch(bottleneck_cmd, paths.bottleneck_log)
    dp, d_log = _launch(defect_cmd, paths.defect_log)
    state = {
        **health_base,
        "failure_policy": policy,
        "overall_status": "RUNNING",
        "bottleneck": {"status": "RUNNING", "pid": bp.pid, "log": str(paths.bottleneck_log)},
        "defect": {"status": "RUNNING", "pid": dp.pid, "log": str(paths.defect_log)},
        "updated_at_unix": time.time(),
    }
    _write_json(paths.health, state)
    seen_brc = seen_drc = None
    # A SIGTERM to this coordinator now flows into the ``except BaseException``
    # cleanup below instead of killing it and orphaning bp/dp.
    _termination_guard = _TerminationGuard()
    _termination_guard.__enter__()
    try:
        while True:
            brc, drc = bp.poll(), dp.poll()
            if policy == "fail-fast":
                if brc is not None and brc != 0:
                    _terminate(dp)
                    raise RuntimeError(
                        f"Bottleneck consumer failed with exit code {brc}; defect consumer was stopped. See {paths.bottleneck_log}"
                    )
                if drc is not None and drc != 0:
                    _terminate(bp)
                    raise RuntimeError(
                        f"Defect consumer failed with exit code {drc}; bottleneck consumer was stopped. See {paths.defect_log}"
                    )
            else:
                changed = False
                if brc is not None and seen_brc is None:
                    seen_brc = brc; changed = True
                    state["bottleneck"]["status"] = "PASS" if brc == 0 else "FAILED_ISOLATED"
                if drc is not None and seen_drc is None:
                    seen_drc = drc; changed = True
                    state["defect"]["status"] = "PASS" if drc == 0 else "FAILED_ISOLATED"
                if changed and ((brc not in (None, 0)) or (drc not in (None, 0))):
                    state["overall_status"] = "DEGRADED_RUNNING"
                    state["updated_at_unix"] = time.time()
                    _write_json(paths.health, state)

            if brc is not None and drc is not None:
                break
            time.sleep(0.05)
    except BaseException:
        _terminate(bp)
        _terminate(dp)
        state["overall_status"] = "FAILED"
        state["bottleneck"]["status"] = "PASS" if bp.poll() == 0 else "FAILED_OR_STOPPED"
        state["defect"]["status"] = "PASS" if dp.poll() == 0 else "FAILED_OR_STOPPED"
        state["updated_at_unix"] = time.time()
        _write_json(paths.health, state)
        raise
    finally:
        _termination_guard.__exit__(None, None, None)
        b_log.close()
        d_log.close()

    brc, drc = int(bp.returncode), int(dp.returncode)
    b_ok, d_ok = brc == 0, drc == 0
    if b_ok and d_ok:
        overall = "CONSUMERS_PASS"
    elif b_ok or d_ok:
        overall = "DEGRADED"
    else:
        overall = "FAILED"
    state["overall_status"] = overall
    state["bottleneck"]["status"] = "PASS" if b_ok else "FAILED_ISOLATED"
    state["bottleneck"]["returncode"] = brc
    state["defect"]["status"] = "PASS" if d_ok else "FAILED_ISOLATED"
    state["defect"]["returncode"] = drc
    state["updated_at_unix"] = time.time()
    _write_json(paths.health, state)
    return {
        "failure_policy": policy,
        "overall_status": overall,
        "bottleneck_returncode": brc,
        "defect_returncode": drc,
        "bottleneck_pass": b_ok,
        "defect_pass": d_ok,
    }


def run_dual_prescribed(
    *,
    run_dir: str | Path,
    output_dir: str | Path,
    run_id: str | None = None,
    bottleneck_model_id: str | None = None,
    defect_model_id: str | None = None,
    bottleneck_artifact_root: str | Path = DEFAULT_BOTTLENECK_ARTIFACT_ROOT,
    defect_artifact_root: str | Path = DEFAULT_DEFECT_ARTIFACT_ROOT,
    history_root: str | Path = DEFAULT_HISTORY_ROOT,
    particles: int = 3000,
    explain_mode: str = "all",
    shap_top_k: int = 3,
    force: bool = False,
    mode: str = "prescribed",
    multiplier: float | None = None,
) -> dict:
    """Run both prediction consumers over a completed run's public bus.

    ``multiplier``, when given, paces both consumers' replay so simulated time
    advances at roughly ``multiplier`` times wall-clock speed (``None`` keeps the
    default as-fast-as-possible replay). It is forwarded verbatim to each consumer's
    own ``--pace``/``--mult`` flags -- the same delivery-timing mechanism the
    bottleneck-only replay path already used -- so both streams stay paced together
    against the one shared event timeline.
    """
    if mode not in {"prescribed", "random"}:
        raise ValueError(f"Unsupported completed dual-run mode: {mode}")
    if multiplier is not None and multiplier <= 0:
        raise ValueError("multiplier must be positive")
    run = Path(run_dir).expanduser().resolve()
    bus = _completed_run_preflight(run)
    rid = str(run_id or run.name)
    paths = output_paths(output_dir)
    _prepare_output_dir(paths, force=force)
    b_art = Path(bottleneck_artifact_root).expanduser().resolve()
    d_art = Path(defect_artifact_root).expanduser().resolve()
    hist = Path(history_root).expanduser().resolve()
    models = _selected_models(b_art, d_art, bottleneck_model_id, defect_model_id)

    bottleneck_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "bottlenecks_prediction" / "run_current.py"),
        "--mode", "replay",
        "--run-dir", str(run),
        "--particles", str(int(particles)),
        "--output", str(paths.bottleneck_output),
        "--run-id", rid,
        "--artifact-root", str(b_art),
    ]
    if bottleneck_model_id:
        bottleneck_cmd += ["--model-id", str(bottleneck_model_id)]
    defect_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "Defect_Model" / "run_current_defects.py"),
        "--mode", "replay",
        "--run-dir", str(run),
        "--particles", str(int(particles)),
        "--output", str(paths.defect_output),
        "--run-id", rid,
        "--artifact-root", str(d_art),
        "--history-root", str(hist),
        "--explain-mode", str(explain_mode),
        "--shap-top-k", str(int(shap_top_k)),
    ]
    if defect_model_id:
        defect_cmd += ["--model-id", str(defect_model_id)]
    if multiplier is not None:
        # Both consumers pace independently against the same event timeline, so they
        # advance through simulated time together without either driving the other.
        bottleneck_cmd += ["--pace", "--mult", str(float(multiplier))]
        defect_cmd += ["--pace", "--mult", str(float(multiplier))]

    health_base = {
        "schema_version": "digital-twin-system-health-v1",
        "mode": mode,
        "run_id": rid,
        "run_dir": str(run),
        "models": models,
        "simulator": {"status": "COMPLETED_INPUT", **bus},
    }
    pair = _run_pair(
        bottleneck_cmd=bottleneck_cmd,
        defect_cmd=defect_cmd,
        paths=paths,
        health_base=health_base,
        failure_policy="fail-fast",
    )
    sync = validate_synchronized_outputs(
        run_dir=run,
        run_id=rid,
        bottleneck_output=paths.bottleneck_output,
        defect_output=paths.defect_output,
        require_defect_explanations=(str(explain_mode) == "all"),
    )
    manifest = {
        "schema_version": "digital-twin-dual-run-v1",
        "mode": mode,
        "run_id": rid,
        "run_dir": str(run),
        "models": models,
        "outputs": {
            "bottleneck": str(paths.bottleneck_output),
            "defect": str(paths.defect_output),
        },
        "logs": {
            "bottleneck": str(paths.bottleneck_log),
            "defect": str(paths.defect_log),
        },
        "validation": sync,
        "lifecycle": pair,
    }
    _write_json(paths.manifest, manifest)
    health = json.loads(paths.health.read_text(encoding="utf-8"))
    health["overall_status"] = "PASS"
    health["validation"] = sync
    health["updated_at_unix"] = time.time()
    _write_json(paths.health, health)
    return manifest


def run_dual_live(
    *,
    run_dir: str | Path = DEFAULT_RUN_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    run_id: str = "CURRENT_RUN",
    bottleneck_model_id: str | None = None,
    defect_model_id: str | None = None,
    bottleneck_artifact_root: str | Path = DEFAULT_BOTTLENECK_ARTIFACT_ROOT,
    defect_artifact_root: str | Path = DEFAULT_DEFECT_ARTIFACT_ROOT,
    history_root: str | Path = DEFAULT_HISTORY_ROOT,
    particles: int = 3000,
    explain_mode: str = "all",
    shap_top_k: int = 3,
    wait_seconds: float = 120.0,
    poll_ms: float = 50.0,
    force: bool = False,
    failure_policy: str = "isolate",
) -> dict:
    run = Path(run_dir).expanduser().resolve()
    if (run / "run_metadata.json").is_file():
        raise ValueError(
            f"Live mode received an already completed run ({run / 'run_metadata.json'} exists). Use system run prescribed instead."
        )
    paths = output_paths(output_dir)
    _prepare_output_dir(paths, force=force)
    b_art = Path(bottleneck_artifact_root).expanduser().resolve()
    d_art = Path(defect_artifact_root).expanduser().resolve()
    hist = Path(history_root).expanduser().resolve()
    models = _selected_models(b_art, d_art, bottleneck_model_id, defect_model_id)

    common = ["--run-dir", str(run), "--particles", str(int(particles)), "--run-id", str(run_id),
              "--wait-seconds", str(float(wait_seconds)), "--poll-ms", str(float(poll_ms))]
    bottleneck_cmd = [
        sys.executable, str(PROJECT_ROOT / "bottlenecks_prediction" / "run_current.py"),
        "--mode", "live", *common,
        "--output", str(paths.bottleneck_output),
        "--artifact-root", str(b_art),
    ]
    if bottleneck_model_id:
        bottleneck_cmd += ["--model-id", str(bottleneck_model_id)]
    defect_cmd = [
        sys.executable, str(PROJECT_ROOT / "Defect_Model" / "run_current_defects.py"),
        "--mode", "live", *common,
        "--output", str(paths.defect_output),
        "--artifact-root", str(d_art),
        "--history-root", str(hist),
        "--explain-mode", str(explain_mode),
        "--shap-top-k", str(int(shap_top_k)),
    ]
    if defect_model_id:
        defect_cmd += ["--model-id", str(defect_model_id)]

    health_base = {
        "schema_version": "digital-twin-system-health-v1",
        "mode": "live",
        "run_id": str(run_id),
        "run_dir": str(run),
        "models": models,
        "simulator": {"status": "EXTERNAL_PROCESS"},
    }
    pair = _run_pair(
        bottleneck_cmd=bottleneck_cmd,
        defect_cmd=defect_cmd,
        paths=paths,
        health_base=health_base,
        failure_policy=failure_policy,
    )
    if pair["overall_status"] == "FAILED":
        raise RuntimeError(
            "Both prediction consumers failed. The external simulator was not stopped; "
            f"see {paths.bottleneck_log} and {paths.defect_log}."
        )
    if not (run / "run_metadata.json").is_file():
        raise RuntimeError("Consumers exited but simulator completion marker run_metadata.json is missing")

    if pair["bottleneck_pass"] and pair["defect_pass"]:
        sync = validate_synchronized_outputs(
            run_dir=run,
            run_id=str(run_id),
            bottleneck_output=paths.bottleneck_output,
            defect_output=paths.defect_output,
            require_defect_explanations=(str(explain_mode) == "all"),
        )
    else:
        available = {}
        if pair["bottleneck_pass"]:
            available["bottleneck"] = validate_single_subsystem_output(
                run_dir=run, run_id=str(run_id), subsystem="bottleneck",
                output=paths.bottleneck_output, defect_explain_mode=str(explain_mode),
            )
        if pair["defect_pass"]:
            available["defect"] = validate_single_subsystem_output(
                run_dir=run, run_id=str(run_id), subsystem="defect",
                output=paths.defect_output, defect_explain_mode=str(explain_mode),
            )
        sync = {
            "run_id": str(run_id),
            "simulator": _read_bus_summary(run / "runtime_events.csv"),
            "available_subsystems": available,
            "synchronization": {
                "status": "DEGRADED",
                "one_to_one_prediction_join_required": False,
                "dashboard_join_keys": ["run_id", "timestamp_ms", "station_id", "unit_id/vehicle_id"],
            },
        }
    manifest = {
        "schema_version": "digital-twin-dual-run-v1",
        "mode": "live",
        "run_id": str(run_id),
        "run_dir": str(run),
        "models": models,
        "outputs": {"bottleneck": str(paths.bottleneck_output), "defect": str(paths.defect_output)},
        "logs": {"bottleneck": str(paths.bottleneck_log), "defect": str(paths.defect_log)},
        "validation": sync,
        "lifecycle": pair,
    }
    _write_json(paths.manifest, manifest)
    health = json.loads(paths.health.read_text(encoding="utf-8"))
    health["overall_status"] = "PASS" if pair["overall_status"] == "CONSUMERS_PASS" else "DEGRADED"
    health["simulator"] = {"status": "COMPLETED", **sync["simulator"]}
    health["validation"] = sync
    health["updated_at_unix"] = time.time()
    _write_json(paths.health, health)
    return manifest


def system_status(
    *,
    run_dir: str | Path = DEFAULT_RUN_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    bottleneck_artifact_root: str | Path = DEFAULT_BOTTLENECK_ARTIFACT_ROOT,
    defect_artifact_root: str | Path = DEFAULT_DEFECT_ARTIFACT_ROOT,
) -> dict:
    run = Path(run_dir).expanduser().resolve()
    paths = output_paths(output_dir)
    b_art = Path(bottleneck_artifact_root).expanduser().resolve()
    d_art = Path(defect_artifact_root).expanduser().resolve()
    models = _selected_models(b_art, d_art, None, None)
    required_live = ["stations.csv", "units.csv", "runtime_events.csv", "dz.csv", "station_checkpoints.csv"]
    files = {name: (run / name).is_file() for name in required_live}
    status = {
        "schema_version": "digital-twin-system-status-v1",
        "run_dir": str(run),
        "run_exists": run.is_dir(),
        "live_files": files,
        "live_input_ready": all(files.values()),
        "run_completed": (run / "run_metadata.json").is_file(),
        "selected_models": models,
        "outputs": {
            "directory": str(paths.root),
            "bottleneck": str(paths.bottleneck_output),
            "defect": str(paths.defect_output),
        },
        "output_separation": True,
        "synchronization_keys": ["run_id", "timestamp_ms", "station_id", "unit_id/vehicle_id"],
        "simulator_launched_by_system_live": False,
    }
    if paths.health.is_file():
        try:
            status["last_health"] = json.loads(paths.health.read_text(encoding="utf-8"))
        except Exception:
            status["last_health"] = {"status": "UNREADABLE"}
    return status


def list_dual_models(
    *,
    bottleneck_artifact_root: str | Path = DEFAULT_BOTTLENECK_ARTIFACT_ROOT,
    defect_artifact_root: str | Path = DEFAULT_DEFECT_ARTIFACT_ROOT,
) -> dict:
    from bottlenecks_prediction.factory_models import list_models as list_bottleneck
    from Defect_Model.factory_models import list_models as list_defect
    return {
        "bottleneck": list_bottleneck(Path(bottleneck_artifact_root).expanduser().resolve()),
        "defect": list_defect(Path(defect_artifact_root).expanduser().resolve()),
    }


def select_dual_model(
    model_id: str,
    *,
    bottleneck_artifact_root: str | Path = DEFAULT_BOTTLENECK_ARTIFACT_ROOT,
    defect_artifact_root: str | Path = DEFAULT_DEFECT_ARTIFACT_ROOT,
) -> dict:
    """Atomically select the same model id for both subsystems.

    Both artifacts are validated before either selection pointer is changed.  This
    prevents a half-switched digital twin when only one subsystem has a factory
    artifact with the requested id.
    """
    from bottlenecks_prediction.factory_models import model_paths as b_paths, select_model as b_select
    from Defect_Model.factory_models import model_paths as d_paths, select_model as d_select

    b_root = Path(bottleneck_artifact_root).expanduser().resolve()
    d_root = Path(defect_artifact_root).expanduser().resolve()
    # Preflight both first. model_paths raises if the requested artifact is absent.
    b_paths(model_id, b_root)
    d_paths(model_id, d_root)
    b = b_select(model_id, b_root)
    d = d_select(model_id, d_root)
    return {"model_id": str(model_id), "bottleneck": b, "defect": d, "atomic_preflight": True}
