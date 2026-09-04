from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from system_runtime import output_paths, system_status, validate_synchronized_outputs


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)


def _fixture_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    _write_csv(run / "stations.csv", ["station_id"], [{"station_id": "S02"}])
    _write_csv(run / "units.csv", ["unit_id", "vehicle_model"], [{"unit_id": "U1", "vehicle_model": "A"}])
    _write_csv(
        run / "runtime_events.csv",
        ["sequence", "timestamp_ms", "record_type", "station_id"],
        [
            {"sequence": 1, "timestamp_ms": 1000, "record_type": "STATION", "station_id": "S02"},
            {"sequence": 2, "timestamp_ms": 2000, "record_type": "SENSOR", "station_id": "S02"},
        ],
    )
    return run


def test_separate_outputs_validate_on_shared_clock(tmp_path: Path) -> None:
    run = _fixture_run(tmp_path)
    b = tmp_path / "b.jsonl"
    d = tmp_path / "d.jsonl"
    b.write_text(json.dumps({
        "run_id": "R", "timestamp_ms": 1500, "station_id": "S02", "vehicle_id": "U1",
        "bottleneck_probability": 0.4, "decision_threshold": 0.3, "warning": True,
        "route": "LIGHT",
        "explanation": {"top_drivers": [{"feature": "x"}], "probability_additivity_error": 1e-9},
    }) + "\n", encoding="utf-8")
    d.write_text(json.dumps({
        "run_id": "R", "timestamp_ms": 2000, "station_id": "S02", "unit_id": "U1",
        "defect_probability": 0.2, "defect_risk_percent": 20.0,
    }) + "\n", encoding="utf-8")
    result = validate_synchronized_outputs(
        run_dir=run, run_id="R", bottleneck_output=b, defect_output=d
    )
    assert result["synchronization"]["same_run_id"] is True
    assert result["synchronization"]["one_to_one_prediction_join_required"] is False
    assert result["bottleneck"]["predictions"] == 1
    assert result["defect"]["predictions"] == 1


def test_sync_validation_rejects_run_id_mismatch(tmp_path: Path) -> None:
    run = _fixture_run(tmp_path)
    b = tmp_path / "b.jsonl"; d = tmp_path / "d.jsonl"
    b.write_text(json.dumps({
        "run_id": "WRONG", "timestamp_ms": 1500, "station_id": "S02", "vehicle_id": "U1",
        "bottleneck_probability": 0.4, "decision_threshold": 0.3, "warning": True,
        "route": "LIGHT",
        "explanation": {"top_drivers": [{"feature": "x"}], "probability_additivity_error": 1e-9},
    }) + "\n", encoding="utf-8")
    d.write_text(json.dumps({
        "run_id": "R", "timestamp_ms": 1500, "station_id": "S02", "unit_id": "U1",
        "defect_probability": 0.2, "defect_risk_percent": 20.0,
    }) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="run_id"):
        validate_synchronized_outputs(run_dir=run, run_id="R", bottleneck_output=b, defect_output=d)


def test_output_contract_keeps_prediction_files_separate(tmp_path: Path) -> None:
    paths = output_paths(tmp_path / "out")
    assert paths.bottleneck_output != paths.defect_output
    assert paths.bottleneck_output.name == "bottleneck_predictions.jsonl"
    assert paths.defect_output.name == "defect_predictions.jsonl"


def test_system_status_does_not_require_unified_output(tmp_path: Path) -> None:
    # Use real artifact roots for selected-model resolution, but an empty run dir.
    project = Path(__file__).resolve().parents[1]
    status = system_status(
        run_dir=tmp_path / "future_run",
        output_dir=tmp_path / "out",
        bottleneck_artifact_root=project / "bottlenecks_prediction" / "factory_models",
        defect_artifact_root=project / "Defect_Model" / "factory_models",
    )
    assert status["output_separation"] is True
    assert status["simulator_launched_by_system_live"] is False
    assert status["synchronization_keys"] == ["run_id", "timestamp_ms", "station_id", "unit_id/vehicle_id"]


def test_live_coordinator_rejects_completed_run_before_launch(tmp_path: Path) -> None:
    from system_runtime import run_dual_live
    run = tmp_path / "completed"
    run.mkdir()
    (run / "run_metadata.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already completed"):
        run_dual_live(run_dir=run, output_dir=tmp_path / "out")


def test_pair_failure_marks_health_failed_and_stops_peer(tmp_path: Path) -> None:
    import sys
    from system_runtime import _run_pair, output_paths
    paths = output_paths(tmp_path / "out")
    paths.root.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Bottleneck consumer failed"):
        _run_pair(
            bottleneck_cmd=[sys.executable, "-c", "import sys; sys.exit(3)"],
            defect_cmd=[sys.executable, "-c", "import time; time.sleep(10)"],
            paths=paths,
            health_base={"schema_version": "test", "mode": "live", "run_id": "R"},
        )
    health = json.loads(paths.health.read_text(encoding="utf-8"))
    assert health["overall_status"] == "FAILED"
    assert health["bottleneck"]["status"] == "FAILED_OR_STOPPED"


def test_dual_model_selection_preflights_both_before_mutation(tmp_path: Path) -> None:
    from system_runtime import select_dual_model
    from bottlenecks_prediction.factory_models import selected_model_id as b_selected
    from Defect_Model.factory_models import selected_model_id as d_selected
    b_root = tmp_path / "bmodels"; d_root = tmp_path / "dmodels"
    result = select_dual_model("base", bottleneck_artifact_root=b_root, defect_artifact_root=d_root)
    assert result["model_id"] == "base"
    assert b_selected(b_root) == "base"
    assert d_selected(d_root) == "base"
    with pytest.raises(FileNotFoundError):
        select_dual_model("missing-factory", bottleneck_artifact_root=b_root, defect_artifact_root=d_root)
    assert b_selected(b_root) == "base"
    assert d_selected(d_root) == "base"


def test_pair_isolate_policy_keeps_healthy_peer_running(tmp_path: Path) -> None:
    import sys
    import time
    from system_runtime import _run_pair, output_paths

    paths = output_paths(tmp_path / "out_isolate")
    paths.root.mkdir(parents=True)
    marker = tmp_path / "healthy_finished.txt"
    start = time.monotonic()
    result = _run_pair(
        bottleneck_cmd=[sys.executable, "-c", "import sys; sys.exit(3)"],
        defect_cmd=[
            sys.executable,
            "-c",
            f"import time, pathlib; time.sleep(0.35); pathlib.Path({str(marker)!r}).write_text('done')",
        ],
        paths=paths,
        health_base={"schema_version": "test", "mode": "live", "run_id": "R"},
        failure_policy="isolate",
    )
    elapsed = time.monotonic() - start
    assert marker.read_text() == "done"
    assert elapsed >= 0.30  # peer was allowed to finish instead of being terminated
    assert result["overall_status"] == "DEGRADED"
    assert result["bottleneck_pass"] is False
    assert result["defect_pass"] is True
    health = json.loads(paths.health.read_text(encoding="utf-8"))
    assert health["overall_status"] == "DEGRADED"
    assert health["bottleneck"]["status"] == "FAILED_ISOLATED"
    assert health["defect"]["status"] == "PASS"


def _minimal_completed_run(run_dir: Path) -> None:
    """The smallest fixture `_completed_run_preflight` will accept."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "stations.csv").write_text("station_id\nS01\n", encoding="utf-8")
    (run_dir / "units.csv").write_text("unit_id\nU000001\n", encoding="utf-8")
    (run_dir / "station_events.csv").write_text("", encoding="utf-8")
    (run_dir / "dz.csv").write_text("", encoding="utf-8")
    (run_dir / "station_checkpoints.csv").write_text("", encoding="utf-8")
    (run_dir / "run_metadata.json").write_text("{}", encoding="utf-8")
    (run_dir / "runtime_events.csv").write_text(
        "sequence,timestamp_ms,record_type,station_id\n1,0,STATION,S01\n",
        encoding="utf-8",
    )


class _StopBeforeLaunch(Exception):
    """Raised by a fake `_run_pair` once it has captured the commands it was given."""


def test_run_dual_prescribed_paces_both_consumers_when_a_playback_speed_is_given(
    tmp_path: Path,
) -> None:
    """The bug this guards: `--mult` used to be dropped, leaving the replay unpaced."""
    import system_runtime as sr

    run_dir = tmp_path / "run_0001"
    _minimal_completed_run(run_dir)

    captured: dict[str, list[str]] = {}

    def fake_run_pair(*, bottleneck_cmd, defect_cmd, **_kwargs):
        captured["bottleneck_cmd"] = bottleneck_cmd
        captured["defect_cmd"] = defect_cmd
        raise _StopBeforeLaunch

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            sr, "_selected_models", lambda *a, **k: {"bottleneck": "base", "defect": "base"}
        )
        monkeypatch.setattr(sr, "_run_pair", fake_run_pair)
        with pytest.raises(_StopBeforeLaunch):
            sr.run_dual_prescribed(
                run_dir=run_dir,
                output_dir=tmp_path / "out",
                run_id="R",
                mode="random",
                multiplier=12.5,
            )
    finally:
        monkeypatch.undo()

    for cmd in (captured["bottleneck_cmd"], captured["defect_cmd"]):
        assert "--pace" in cmd
        assert cmd[cmd.index("--mult") + 1] == "12.5"


def test_run_dual_prescribed_stays_unpaced_when_no_playback_speed_is_given(
    tmp_path: Path,
) -> None:
    """Callers that never pass `multiplier` (e.g. `system run prescribed`) are unchanged."""
    import system_runtime as sr

    run_dir = tmp_path / "run_0001"
    _minimal_completed_run(run_dir)

    captured: dict[str, list[str]] = {}

    def fake_run_pair(*, bottleneck_cmd, defect_cmd, **_kwargs):
        captured["bottleneck_cmd"] = bottleneck_cmd
        captured["defect_cmd"] = defect_cmd
        raise _StopBeforeLaunch

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            sr, "_selected_models", lambda *a, **k: {"bottleneck": "base", "defect": "base"}
        )
        monkeypatch.setattr(sr, "_run_pair", fake_run_pair)
        with pytest.raises(_StopBeforeLaunch):
            sr.run_dual_prescribed(
                run_dir=run_dir, output_dir=tmp_path / "out", run_id="R", mode="random"
            )
    finally:
        monkeypatch.undo()

    for cmd in (captured["bottleneck_cmd"], captured["defect_cmd"]):
        assert "--pace" not in cmd
        assert "--mult" not in cmd


def test_run_dual_prescribed_rejects_a_non_positive_multiplier(tmp_path: Path) -> None:
    import system_runtime as sr

    run_dir = tmp_path / "run_0001"
    _minimal_completed_run(run_dir)
    with pytest.raises(ValueError, match="multiplier must be positive"):
        sr.run_dual_prescribed(
            run_dir=run_dir, output_dir=tmp_path / "out", run_id="R", mode="random",
            multiplier=0.0,
        )
