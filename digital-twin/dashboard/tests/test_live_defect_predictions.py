"""Live consumption of the defect prediction stream, and its page in the dashboard.

The per-unit sibling of ``test_live_predictions.py``: same guarantees, same style of
test, applied to ``defect_predictions.jsonl`` and the unit-scoped timeline it drives on
the Defects page. No test here runs the simulator or a model -- the stream is the
contract, and the two prediction streams are exercised independently since they are
never merged.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from dashboard.live.defect_state import (
    TREND_FALLING,
    TREND_RISING,
    TREND_STABLE,
    TREND_UNKNOWN,
    LiveDefectState,
    parse_defect_point,
)
from dashboard.live.session import (
    LivePredictionFeed,
    LiveRunRegistry,
    LiveRunSession,
    LiveRunStatus,
    bottleneck_stream_path,
    defect_stream_path,
)
from dashboard.live.stream import JsonlTailer

RUN_ID = "production_day_0001"


def defect_record(
    *,
    unit: str = "U000001",
    station: str = "S02",
    timestamp_ms: int = 1000,
    probability: float = 0.5,
    warning: bool | None = None,
    threshold: float = 0.4,
    run_id: str = RUN_ID,
    **extra,
) -> dict:
    """One ``defect-prediction-v2`` record.

    ``warning`` defaults to what the runtime would emit for this probability, but tests
    may set it independently -- the dashboard must use the flag, not re-derive it.
    """
    payload = {
        "schema_version": "defect-prediction-v2",
        "run_id": run_id,
        "timestamp_ms": timestamp_ms,
        "unit_id": unit,
        "station_id": station,
        "station_index": 1,
        "final_inspection_station": False,
        "route": "LIGHT",
        "prediction_trigger": "STATION_EXIT",
        "data_source": "sensor",
        "state_confidence": 1.0,
        "defect_probability": probability,
        "defect_risk_percent": probability * 100,
        "raw_defect_probability": probability,
        "alert_policy": "single_row",
        "alert_policy_score": probability,
        "decision_threshold": threshold,
        "threshold_crossed": probability >= threshold,
        "warning": (probability >= threshold) if warning is None else warning,
    }
    payload.update(extra)
    return payload


def append(path: Path, *records: dict) -> None:
    """Append complete records, the way ``append_jsonl`` does: open, write, close."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in records:
            handle.write(json.dumps(item) + "\n")


class TestParsing:
    def test_mandatory_fields_are_timestamp_and_probability(self):
        assert parse_defect_point({"timestamp_ms": 1, "defect_probability": 0.5}) is not None
        assert parse_defect_point({"defect_probability": 0.5}) is None
        assert parse_defect_point({"timestamp_ms": 1}) is None

    def test_warning_is_read_verbatim_never_recomputed(self):
        """A record can legally have high probability but warning=False (final inspection)."""
        record = defect_record(probability=0.9, threshold=0.1, warning=False)
        point = parse_defect_point(record)
        assert point.probability == pytest.approx(0.9)
        assert point.warning is False

    def test_final_inspection_suppression_is_not_re_derived(self):
        record = defect_record(
            probability=0.95, threshold=0.1, warning=False, final_inspection_station=True,
            threshold_crossed=True,
        )
        point = parse_defect_point(record)
        assert point.warning is False
        assert point.final_inspection_station is True


class TestIncrementalConsumption:
    def test_feed_accumulates_across_polls(self, tmp_path: Path):
        stream = tmp_path / "defect_predictions.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        assert feed.poll() == 0

        append(stream, defect_record(timestamp_ms=100))
        assert feed.poll() == 1
        append(stream, defect_record(timestamp_ms=200), defect_record(timestamp_ms=300))
        assert feed.poll() == 2
        assert feed.state.record_count == 3
        assert feed.state.last_timestamp_ms == 300

    def test_reads_only_what_is_new(self, tmp_path: Path):
        stream = tmp_path / "defect_predictions.jsonl"
        append(stream, defect_record(timestamp_ms=100), defect_record(timestamp_ms=200))
        tailer = JsonlTailer(stream)
        first = tailer.read_new()
        assert [r["timestamp_ms"] for r in first.records] == [100, 200]
        assert tailer.read_new().records == []


class TestUnitTimeSeries:
    def test_series_accumulate_per_unit_in_simulator_time(self, tmp_path: Path):
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(
            stream,
            defect_record(unit="U000001", station="S02", timestamp_ms=1000, probability=0.1),
            defect_record(unit="U000002", station="S02", timestamp_ms=1500, probability=0.2),
            defect_record(unit="U000001", station="S05", timestamp_ms=3000, probability=0.6),
        )
        feed.poll()
        assert feed.state.unit_ids() == ["U000001", "U000002"]
        series = feed.state.series("U000001")
        assert [p.timestamp_ms for p in series.points] == [1000, 3000]
        assert [p.station_id for p in series.points] == ["S02", "S05"]

    def test_trend_needs_at_least_four_points(self, tmp_path: Path):
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(stream, defect_record(timestamp_ms=1, probability=0.1))
        feed.poll()
        assert feed.state.analytics("U000001").trend == TREND_UNKNOWN

    def test_trend_direction_follows_the_recent_window(self, tmp_path: Path):
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(
            stream,
            *(
                defect_record(timestamp_ms=i * 1000, probability=0.1)
                for i in range(4)
            ),
            *(
                defect_record(timestamp_ms=(i + 4) * 1000, probability=0.9)
                for i in range(4)
            ),
        )
        feed.poll()
        analytics = feed.state.analytics("U000001")
        assert analytics.trend == TREND_RISING


class TestThresholdAndWarningIntervals:
    def test_threshold_crossings_and_warning_periods(self, tmp_path: Path):
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(
            stream,
            defect_record(timestamp_ms=1000, probability=0.1, warning=False, threshold=0.4),
            defect_record(timestamp_ms=2000, probability=0.8, warning=True, threshold=0.4),
            defect_record(timestamp_ms=3000, probability=0.85, warning=True, threshold=0.4),
            defect_record(timestamp_ms=4000, probability=0.1, warning=False, threshold=0.4),
            defect_record(timestamp_ms=5000, probability=0.9, warning=True, threshold=0.4),
        )
        feed.poll()
        analytics = feed.state.analytics("U000001")
        assert analytics.threshold_crossings == 2
        assert len(analytics.warning_periods) == 2
        assert analytics.warning_periods[0].duration_ms == 1000
        assert analytics.time_above_threshold_ms == 1000

    def test_final_inspection_suppression_does_not_count_as_a_crossing(self, tmp_path: Path):
        """A high-probability, warning=False final-inspection record stays out of the tally."""
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(
            stream,
            defect_record(
                timestamp_ms=1000, probability=0.95, threshold=0.1, warning=False,
                final_inspection_station=True, threshold_crossed=True,
            ),
        )
        feed.poll()
        analytics = feed.state.analytics("U000001")
        assert analytics.threshold_crossings == 0
        assert analytics.warning_periods == ()


class TestLatestRisk:
    def test_current_risk_is_the_most_recent_record(self, tmp_path: Path):
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(
            stream,
            defect_record(timestamp_ms=1000, probability=0.2),
            defect_record(timestamp_ms=2000, probability=0.6),
        )
        feed.poll()
        analytics = feed.state.analytics("U000001")
        assert analytics.current_risk == pytest.approx(0.6)
        assert analytics.peak_risk == pytest.approx(0.6)

    def test_active_warning_units_reflects_only_the_latest_point(self, tmp_path: Path):
        stream = tmp_path / "d.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        append(
            stream,
            defect_record(unit="U000001", timestamp_ms=1000, warning=True),
            defect_record(unit="U000001", timestamp_ms=2000, warning=False),
            defect_record(unit="U000002", timestamp_ms=1000, warning=True),
        )
        feed.poll()
        assert feed.state.active_warning_units() == ["U000002"]


class TestCompletedRunPersistence:
    def test_a_completed_files_full_history_reads_the_same_way_as_a_live_one(
        self, tmp_path: Path
    ):
        """No second processing step: read-all and incremental-read agree."""
        stream = tmp_path / "d.jsonl"
        append(
            stream,
            defect_record(unit="U000001", timestamp_ms=1000, probability=0.2),
            defect_record(unit="U000002", timestamp_ms=1500, probability=0.7, warning=True),
        )
        completed = LivePredictionFeed(RUN_ID, stream, state=LiveDefectState())
        completed.poll()
        assert completed.state.record_count == 2
        assert completed.state.unit_ids() == ["U000001", "U000002"]


class TestLiveRunSessionTailsBothStreams:
    """One session, one background thread, both prediction streams kept current."""

    def test_default_defect_path_is_the_sibling_of_the_bottleneck_stream(self, tmp_path: Path):
        predictions_dir = tmp_path / "runtime_output" / RUN_ID
        session = LiveRunSession(RUN_ID, bottleneck_stream_path(predictions_dir))
        assert session.defect_feed.stream_path == defect_stream_path(predictions_dir)

    def test_refresh_polls_both_streams(self, tmp_path: Path):
        predictions_dir = tmp_path / "runtime_output" / RUN_ID
        b_stream = bottleneck_stream_path(predictions_dir)
        d_stream = defect_stream_path(predictions_dir)
        session = LiveRunSession(RUN_ID, b_stream)

        from dashboard.tests.test_live_predictions import record as bottleneck_record

        append(b_stream, bottleneck_record(timestamp_ms=100))
        append(d_stream, defect_record(timestamp_ms=100))
        session.refresh()

        assert session.state.record_count == 1
        assert session.defect_state.record_count == 1

    def test_registry_defect_feed_rehydrates_a_run_this_process_did_not_launch(
        self, tmp_path: Path
    ):
        predictions_dir = tmp_path / "runtime_output" / RUN_ID
        d_stream = defect_stream_path(predictions_dir)
        append(d_stream, defect_record(timestamp_ms=100), defect_record(timestamp_ms=200))

        registry = LiveRunRegistry()
        feed = registry.defect_feed(RUN_ID, d_stream)
        assert feed.state.record_count == 2
        # A second call for the same run/path returns the same rehydrated feed.
        assert registry.defect_feed(RUN_ID, d_stream) is feed


class TestDefectsPageRendersTheTimeline:
    """The real page, through Streamlit, over a run's own stream file."""

    def _launch(self, tmp_path: Path, monkeypatch):
        pytest.importorskip("streamlit", reason="dashboard/requirements.txt not installed")
        from streamlit.testing.v1 import AppTest

        from dashboard.config import load_config
        from dashboard.context import build_context
        from dashboard.domain.run import Run, RunStatus
        from dashboard.live.session import get_registry

        monkeypatch.setenv("DT_DASHBOARD_FACTORY", str(tmp_path / "config" / "factory.json"))
        monkeypatch.setenv("DT_DASHBOARD_DB", str(tmp_path / "db" / "dashboard.db"))
        monkeypatch.setenv("DT_DASHBOARD_RUNS", str(tmp_path / "runs"))
        monkeypatch.setenv("DT_DASHBOARD_GENERATED", str(tmp_path / "generated"))
        monkeypatch.setenv("DT_DASHBOARD_PREDICTIONS", str(tmp_path / "runtime_output"))

        predictions_dir = tmp_path / "runtime_output" / RUN_ID
        stream = defect_stream_path(predictions_dir)
        append(
            stream,
            defect_record(unit="U000001", timestamp_ms=1000, probability=0.10, warning=False),
            defect_record(unit="U000001", timestamp_ms=2000, probability=0.80, warning=True),
            defect_record(unit="U000001", timestamp_ms=3000, probability=0.85, warning=True),
            defect_record(unit="U000002", timestamp_ms=2500, probability=0.20, warning=False),
        )

        context = build_context(load_config())
        context.repository.upsert_run(
            Run(
                run_id=RUN_ID,
                production_day=1,
                status=RunStatus.COMPLETED,
                artifact_path=str(tmp_path / "runs" / RUN_ID / "run_0001"),
                predictions_path=str(predictions_dir),
            )
        )
        get_registry().clear()

        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[2] / "dashboard" / "app.py"),
            default_timeout=60,
        )
        app.run()
        return app.sidebar.radio[0].set_value("Defects").run()

    def test_completed_run_shows_its_timeline_without_a_second_step(
        self, tmp_path: Path, monkeypatch
    ):
        app = self._launch(tmp_path, monkeypatch)
        assert not app.exception, [str(e) for e in app.exception]
        units = [box for box in app.selectbox if box.label == "Unit"]
        assert units, "the timeline's unit picker did not render"
        assert list(units[0].options) == ["U000001", "U000002"]

    def test_the_page_reports_the_analytics_for_the_selected_unit(
        self, tmp_path: Path, monkeypatch
    ):
        app = self._launch(tmp_path, monkeypatch)
        labels = {metric.label: metric.value for metric in app.metric}
        assert labels.get("Current risk") == "85.0%"
        assert labels.get("Peak risk") == "85.0%"
        assert labels.get("Threshold") == "40.0%"
        assert labels.get("Threshold crossings") == "1"

    def test_switching_unit_shows_that_units_history(self, tmp_path: Path, monkeypatch):
        app = self._launch(tmp_path, monkeypatch)
        picker = next(box for box in app.selectbox if box.label == "Unit")
        app = picker.set_value("U000002").run()
        assert not app.exception, [str(e) for e in app.exception]
        labels = {metric.label: metric.value for metric in app.metric}
        assert labels.get("Current risk") == "20.0%"
        assert labels.get("Threshold crossings") == "0"


class TestLiveUpdateDuringARun:
    """A run this process launched: predictions keep landing while it executes."""

    def test_switching_units_mid_run_reads_accumulated_history_so_far(self, tmp_path: Path):
        """``refresh()`` is what Streamlit calls on every rerun; drive it directly."""
        predictions_dir = tmp_path / "runtime_output" / RUN_ID
        b_stream = bottleneck_stream_path(predictions_dir)
        d_stream = defect_stream_path(predictions_dir)

        process = FakeProcess([], block=True)
        session = LiveRunSession(RUN_ID, b_stream, poll_interval_s=0.01)
        session.start(lambda: process)
        try:
            append(d_stream, defect_record(unit="U000001", timestamp_ms=100, probability=0.3))
            session.refresh()
            assert session.defect_state.record_count == 1
            assert session.defect_state.unit_ids() == ["U000001"]
            assert session.is_running

            append(d_stream, defect_record(unit="U000002", timestamp_ms=200, probability=0.9))
            session.refresh()
            assert session.defect_state.record_count == 2
            assert session.defect_state.unit_ids() == ["U000001", "U000002"]
            assert session.defect_state.series("U000001") is not None
        finally:
            process.release()
            _wait_until(lambda: session.status.finished)


# -- helpers -------------------------------------------------------------------------


class FakeProcess:
    """Stand-in for the pipeline subprocess.

    The real one is ``cli.py system run random``; these tests are about how the
    dashboard supervises a process, not about what that process computes.
    """

    def __init__(self, lines: list[str], *, exit_code: int = 0, block: bool = False,
                 on_wait=None):
        self.stdout = iter(f"{line}\n" for line in lines)
        self.exit_code = exit_code
        self.on_wait = on_wait
        self.terminated = False
        self._release = threading.Event()
        if not block:
            self._release.set()

    def release(self) -> None:
        self._release.set()

    def wait(self) -> int:
        self._release.wait(timeout=10)
        if self.on_wait:
            self.on_wait()
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self._release.set()


def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not reached in time")
