"""Live consumption of the bottleneck prediction stream.

These tests write JSONL the way the existing runtime does -- appending complete records
to a growing file -- and check that the dashboard sees them as they land, that its
temporal analytics match the records emitted so far, and that nothing is lost when the
user switches stations, the run ends, or the dashboard is restarted.

No test here runs the simulator or a model. The stream is the contract.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from dashboard.live.bottleneck_state import (
    TREND_FALLING,
    TREND_RISING,
    TREND_STABLE,
    TREND_UNKNOWN,
    LiveBottleneckState,
    parse_point,
)
from dashboard.live.session import (
    LivePredictionFeed,
    LiveRunRegistry,
    LiveRunSession,
    LiveRunStatus,
    bottleneck_stream_path,
)
from dashboard.live.stream import JsonlTailer

RUN_ID = "production_day_0001"


def record(
    *,
    station: str = "S02",
    timestamp_ms: int = 1000,
    probability: float = 0.5,
    warning: bool | None = None,
    threshold: float = 0.4,
    run_id: str = RUN_ID,
    **extra,
) -> dict:
    """One ``bottleneck-prediction-v1`` record.

    ``warning`` defaults to what the runtime would emit for this probability, but tests
    may set it independently -- the dashboard must use the flag, not re-derive it.
    """
    payload = {
        "schema_version": "bottleneck-prediction-v1",
        "run_id": run_id,
        "timestamp_ms": timestamp_ms,
        "station_id": station,
        "vehicle_id": "U000001",
        "zone": "LIGHT",
        "route": "LIGHT",
        "prediction_trigger": "UNIT_ARRIVED",
        "bottleneck_probability": probability,
        "bottleneck_risk_percent": probability * 100,
        "warning": (probability >= threshold) if warning is None else warning,
        "decision_threshold": threshold,
        "decision_threshold_percent": threshold * 100,
        "state_confidence": 1.0,
    }
    payload.update(extra)
    return payload


def append(path: Path, *records: dict) -> None:
    """Append complete records, the way ``append_jsonl`` does: open, write, close."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in records:
            handle.write(json.dumps(item) + "\n")


class TestIncrementalConsumption:
    def test_reads_only_what_is_new(self, tmp_path: Path):
        stream = tmp_path / "bottleneck_predictions.jsonl"
        append(stream, record(timestamp_ms=100), record(timestamp_ms=200))
        tailer = JsonlTailer(stream)

        first = tailer.read_new()
        assert [r["timestamp_ms"] for r in first.records] == [100, 200]

        assert tailer.read_new().records == []

        append(stream, record(timestamp_ms=300))
        assert [r["timestamp_ms"] for r in tailer.read_new().records] == [300]

    def test_missing_stream_is_not_an_error(self, tmp_path: Path):
        tailer = JsonlTailer(tmp_path / "never_written.jsonl")
        assert tailer.read_new().records == []
        assert not tailer.exists()

    def test_a_half_written_line_is_held_until_it_completes(self, tmp_path: Path):
        """A batch caught mid-flush must not be reported as malformed or dropped."""
        stream = tmp_path / "b.jsonl"
        line = json.dumps(record(timestamp_ms=100))
        stream.write_text(line[:20], encoding="utf-8")
        tailer = JsonlTailer(stream)

        partial = tailer.read_new()
        assert partial.records == []
        assert partial.malformed == 0

        with stream.open("a", encoding="utf-8") as handle:
            handle.write(line[20:] + "\n")
        assert [r["timestamp_ms"] for r in tailer.read_new().records] == [100]

    def test_malformed_lines_are_counted_not_fatal(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        stream.write_text("{not json}\n" + json.dumps(record()) + "\n", encoding="utf-8")
        result = JsonlTailer(stream).read_new()
        assert result.malformed == 1
        assert len(result.records) == 1

    def test_a_rewritten_stream_restarts_the_tailer(self, tmp_path: Path):
        """The replay consumer deletes its output before it starts appending."""
        stream = tmp_path / "b.jsonl"
        append(stream, record(timestamp_ms=1), record(timestamp_ms=2), record(timestamp_ms=3))
        tailer = JsonlTailer(stream)
        assert len(tailer.read_new().records) == 3

        stream.unlink()
        append(stream, record(timestamp_ms=9))
        result = tailer.read_new()
        assert result.restarted
        assert [r["timestamp_ms"] for r in result.records] == [9]

    def test_feed_accumulates_across_polls(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream)
        assert feed.poll() == 0

        append(stream, record(timestamp_ms=100))
        assert feed.poll() == 1
        append(stream, record(timestamp_ms=200), record(timestamp_ms=300))
        assert feed.poll() == 2
        assert feed.state.record_count == 3
        assert feed.state.last_timestamp_ms == 300


class TestStationTimeSeries:
    def test_series_accumulate_per_station_in_simulator_time(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream)
        append(
            stream,
            record(station="S02", timestamp_ms=100, probability=0.1),
            record(station="S03", timestamp_ms=150, probability=0.9),
            record(station="S02", timestamp_ms=400, probability=0.2),
        )
        feed.poll()

        assert feed.state.station_ids() == ["S02", "S03"]
        s02 = feed.state.series("S02")
        assert [p.timestamp_ms for p in s02.points] == [100, 400]
        assert [p.probability for p in s02.points] == [0.1, 0.2]
        assert len(feed.state.series("S03")) == 1

    def test_a_record_without_a_timestamp_is_skipped_not_invented(self, tmp_path: Path):
        state = LiveBottleneckState()
        broken = record()
        del broken["timestamp_ms"]
        assert state.ingest([broken]) == 0
        assert state.skipped_records == 1
        assert state.stations == {}

    def test_records_from_another_run_are_never_merged(self, tmp_path: Path):
        state = LiveBottleneckState()
        state.ingest([record(run_id="run_a", timestamp_ms=1)])
        state.ingest([record(run_id="run_b", timestamp_ms=2)])
        assert state.run_id == "run_a"
        assert state.record_count == 1
        assert state.foreign_run_records == 1

    def test_the_stream_supplies_the_threshold(self, tmp_path: Path):
        state = LiveBottleneckState()
        state.ingest([record(threshold=0.1555924266576767)])
        assert state.analytics("S02").threshold == pytest.approx(0.1555924266576767)

    def test_warning_is_read_not_recomputed(self):
        """A record whose flag disagrees with probability >= threshold keeps its flag."""
        point = parse_point(record(probability=0.9, threshold=0.4, warning=False))
        assert point.probability == 0.9
        assert point.warning is False

        state = LiveBottleneckState()
        state.ingest([record(probability=0.1, threshold=0.4, warning=True)])
        assert state.analytics("S02").warning_count == 1


class TestThresholdAndWarningIntervals:
    def _state(self, *flags: bool, step: int = 1000) -> LiveBottleneckState:
        state = LiveBottleneckState()
        state.ingest(
            [
                record(timestamp_ms=(index + 1) * step, probability=0.9 if flag else 0.1,
                       warning=flag)
                for index, flag in enumerate(flags)
            ]
        )
        return state

    def test_crossings_count_transitions_into_the_warning_state(self):
        analytics = self._state(False, True, True, False, True).analytics("S02")
        assert analytics.threshold_crossings == 2
        assert analytics.warning_count == 3

    def test_a_run_that_starts_flagged_counts_one_crossing(self):
        assert self._state(True, True).analytics("S02").threshold_crossings == 1

    def test_time_above_threshold_spans_consecutive_flagged_records(self):
        # Flagged at 2000, 3000, 4000 -> two 1000 ms gaps inside the period.
        analytics = self._state(False, True, True, True, False).analytics("S02")
        assert analytics.time_above_threshold_ms == 2000

    def test_an_isolated_flagged_record_contributes_no_duration(self):
        analytics = self._state(False, True, False).analytics("S02")
        assert analytics.threshold_crossings == 1
        assert analytics.time_above_threshold_ms == 0

    def test_warning_periods_carry_their_simulator_bounds(self):
        analytics = self._state(False, True, True, False, True, True).analytics("S02")
        periods = analytics.warning_periods
        assert len(periods) == 2
        assert (periods[0].start_ms, periods[0].end_ms) == (2000, 3000)
        assert periods[0].duration_ms == 1000
        assert periods[0].point_count == 2
        assert not periods[0].open_ended
        # The run's newest record is still flagged, so the last period is still open.
        assert periods[1].open_ended

    def test_analytics_advance_incrementally_as_records_arrive(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream)

        append(stream, record(timestamp_ms=1000, probability=0.1, warning=False))
        feed.poll()
        assert feed.state.analytics("S02").threshold_crossings == 0

        append(stream, record(timestamp_ms=2000, probability=0.8, warning=True))
        feed.poll()
        first = feed.state.analytics("S02")
        assert first.threshold_crossings == 1
        assert first.time_above_threshold_ms == 0

        append(stream, record(timestamp_ms=5000, probability=0.85, warning=True))
        feed.poll()
        second = feed.state.analytics("S02")
        assert second.threshold_crossings == 1
        assert second.time_above_threshold_ms == 3000
        assert second.peak_risk == pytest.approx(0.85)


class TestLatestRisk:
    def test_current_risk_follows_the_newest_record(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream)
        append(stream, record(timestamp_ms=100, probability=0.2))
        feed.poll()
        assert feed.state.analytics("S02").current_risk == pytest.approx(0.2)

        append(stream, record(timestamp_ms=200, probability=0.7))
        feed.poll()
        analytics = feed.state.analytics("S02")
        assert analytics.current_risk == pytest.approx(0.7)
        assert analytics.peak_risk == pytest.approx(0.7)
        assert analytics.average_risk == pytest.approx(0.45)

        append(stream, record(timestamp_ms=300, probability=0.3))
        feed.poll()
        analytics = feed.state.analytics("S02")
        assert analytics.current_risk == pytest.approx(0.3)
        assert analytics.peak_risk == pytest.approx(0.7), "peak is the run maximum, not the latest"

    def test_active_alerts_come_from_the_latest_record_per_station(self, tmp_path: Path):
        state = LiveBottleneckState()
        state.ingest(
            [
                record(station="S02", timestamp_ms=1, warning=True),
                record(station="S02", timestamp_ms=2, warning=False),
                record(station="S03", timestamp_ms=1, warning=True),
            ]
        )
        assert state.active_warning_stations() == ["S03"]

    def test_trend_is_descriptive_and_needs_enough_points(self):
        state = LiveBottleneckState()
        state.ingest([record(timestamp_ms=1, probability=0.5)])
        assert state.analytics("S02").trend == TREND_UNKNOWN

        rising = LiveBottleneckState()
        rising.ingest(
            [record(timestamp_ms=i, probability=0.1 * i) for i in range(1, 9)]
        )
        assert rising.analytics("S02").trend == TREND_RISING

        falling = LiveBottleneckState()
        falling.ingest(
            [record(timestamp_ms=i, probability=0.9 - 0.1 * i) for i in range(1, 9)]
        )
        assert falling.analytics("S02").trend == TREND_FALLING

        flat = LiveBottleneckState()
        flat.ingest([record(timestamp_ms=i, probability=0.5) for i in range(1, 9)])
        assert flat.analytics("S02").trend == TREND_STABLE


class TestSwitchingStationsDuringARun:
    def test_every_station_accumulates_regardless_of_which_one_is_displayed(
        self, tmp_path: Path
    ):
        """Selecting a station is a read. History for the others keeps building."""
        stream = tmp_path / "b.jsonl"
        feed = LivePredictionFeed(RUN_ID, stream)

        append(stream, record(station="S02", timestamp_ms=100, probability=0.2))
        feed.poll()
        # The user is looking at S02 only.
        assert feed.state.analytics("S02").point_count == 1
        assert feed.state.analytics("S05").point_count == 0

        append(
            stream,
            record(station="S05", timestamp_ms=200, probability=0.8, warning=True),
            record(station="S05", timestamp_ms=300, probability=0.9, warning=True),
            record(station="S02", timestamp_ms=400, probability=0.3),
        )
        feed.poll()

        # Switching to S05 mid-run shows everything it produced while unobserved.
        s05 = feed.state.analytics("S05")
        assert s05.point_count == 2
        assert s05.threshold_crossings == 1
        assert s05.time_above_threshold_ms == 100
        assert feed.state.analytics("S02").point_count == 2

    def test_analytics_for_an_unseen_station_are_empty_not_invented(self, tmp_path: Path):
        feed = LivePredictionFeed(RUN_ID, tmp_path / "b.jsonl")
        analytics = feed.state.analytics("S99")
        assert analytics.point_count == 0
        assert analytics.current_risk is None
        assert analytics.warning_periods == ()


class TestCompletedRunPersistence:
    def test_history_survives_the_run_finishing(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        session = LiveRunSession(RUN_ID, stream, poll_interval_s=0.01)
        process = FakeProcess(["starting"], exit_code=0)

        def launch():
            append(stream, record(timestamp_ms=100), record(timestamp_ms=200))
            return process

        session.start(launch)
        _wait_until(lambda: session.status.finished)

        assert session.status == LiveRunStatus.COMPLETED
        assert session.state.record_count == 2
        # No second processing step: the timeline is readable immediately.
        assert session.state.analytics("S02").point_count == 2

    def test_the_final_batch_is_never_lost(self, tmp_path: Path):
        """Records written just before exit must still be drained."""
        stream = tmp_path / "b.jsonl"
        session = LiveRunSession(RUN_ID, stream, poll_interval_s=60.0)
        released = threading.Event()

        def on_exit():
            append(stream, record(timestamp_ms=999))
            released.set()

        session.start(lambda: FakeProcess([], exit_code=0, on_wait=on_exit))
        _wait_until(lambda: session.status.finished)
        assert released.is_set()
        assert session.state.record_count == 1

    def test_a_failed_run_keeps_what_it_produced(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        append(stream, record(timestamp_ms=10))
        session = LiveRunSession(RUN_ID, stream, poll_interval_s=0.01)
        session.start(lambda: FakeProcess(["boom"], exit_code=1))
        _wait_until(lambda: session.status.finished)

        assert session.status == LiveRunStatus.FAILED
        assert "code 1" in (session.error or "")
        assert session.state.record_count == 1

    def test_a_completed_run_reads_back_identically_from_its_file(self, tmp_path: Path):
        """LIVE and COMPLETED mode are the same code path over the same file."""
        stream = tmp_path / "b.jsonl"
        live = LivePredictionFeed(RUN_ID, stream)
        for index in range(1, 6):
            append(stream, record(timestamp_ms=index * 100, probability=index / 10))
            live.poll()

        completed = LivePredictionFeed(RUN_ID, stream)
        completed.poll()

        assert completed.state.record_count == live.state.record_count
        assert completed.state.analytics("S02") == live.state.analytics("S02")


class TestRestartingTheDashboard:
    def test_a_fresh_registry_rebuilds_history_from_the_stream(self, tmp_path: Path):
        """A dashboard restart drops memory, not history: the file is the record."""
        predictions_dir = tmp_path / "runtime_output" / RUN_ID
        stream = bottleneck_stream_path(predictions_dir)
        append(
            stream,
            record(timestamp_ms=100, probability=0.2),
            record(timestamp_ms=200, probability=0.8, warning=True),
        )

        before = LiveRunRegistry().feed(RUN_ID, stream)
        assert before.state.record_count == 2

        after_restart = LiveRunRegistry().feed(RUN_ID, stream)
        assert after_restart.state.record_count == 2
        assert after_restart.state.analytics("S02") == before.state.analytics("S02")

    def test_repeated_reads_do_not_duplicate_records(self, tmp_path: Path):
        """A Streamlit rerun polls again; the same records must not be counted twice."""
        stream = tmp_path / "b.jsonl"
        registry = LiveRunRegistry()
        append(stream, record(timestamp_ms=100), record(timestamp_ms=200))

        feed = registry.feed(RUN_ID, stream)
        for _ in range(5):  # five reruns of the script
            registry.feed(RUN_ID, stream)
        assert feed.state.record_count == 2

    def test_a_registered_session_keeps_its_feed_across_lookups(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        registry = LiveRunRegistry()
        session = registry.create_session(RUN_ID, stream)
        append(stream, record(timestamp_ms=100))
        session.refresh()

        assert registry.feed(RUN_ID, stream) is session.feed
        assert registry.session(RUN_ID) is session

    def test_registry_refuses_to_start_a_second_copy_of_a_running_run(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        registry = LiveRunRegistry()
        session = registry.create_session(RUN_ID, stream)
        session.start(lambda: FakeProcess([], exit_code=0, block=True))
        try:
            with pytest.raises(RuntimeError):
                registry.create_session(RUN_ID, stream)
        finally:
            session.cancel()
            _wait_until(lambda: session.status.finished)


class TestNonBlockingExecution:
    def test_start_returns_while_the_pipeline_is_still_running(self, tmp_path: Path):
        """The UI thread must not sit inside the run."""
        stream = tmp_path / "b.jsonl"
        session = LiveRunSession(RUN_ID, stream, poll_interval_s=0.01)
        process = FakeProcess([], exit_code=0, block=True)

        started = time.time()
        session.start(lambda: process)
        assert time.time() - started < 2.0
        assert session.is_running

        # Predictions emitted mid-run are visible before the run ends.
        append(stream, record(timestamp_ms=100))
        assert session.refresh() == 1
        assert session.is_running

        process.release()
        _wait_until(lambda: session.status.finished)
        assert session.status == LiveRunStatus.COMPLETED

    def test_cancelling_stops_the_run_and_keeps_the_history(self, tmp_path: Path):
        stream = tmp_path / "b.jsonl"
        append(stream, record(timestamp_ms=100))
        session = LiveRunSession(RUN_ID, stream, poll_interval_s=0.01)
        process = FakeProcess([], exit_code=0, block=True)
        session.start(lambda: process)
        session.refresh()

        session.cancel()
        _wait_until(lambda: session.status.finished)
        assert session.status == LiveRunStatus.CANCELLED
        assert process.terminated
        assert session.state.record_count == 1


class TestBottlenecksPageRendersTheTimeline:
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
        stream = bottleneck_stream_path(predictions_dir)
        append(
            stream,
            record(station="S02", timestamp_ms=1000, probability=0.10, warning=False),
            record(station="S02", timestamp_ms=2000, probability=0.80, warning=True),
            record(station="S02", timestamp_ms=3000, probability=0.85, warning=True),
            record(station="S05", timestamp_ms=2500, probability=0.20, warning=False),
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
        return app.sidebar.radio[0].set_value("Bottlenecks").run()

    def test_completed_run_shows_its_timeline_without_a_second_step(
        self, tmp_path: Path, monkeypatch
    ):
        app = self._launch(tmp_path, monkeypatch)
        assert not app.exception, [str(e) for e in app.exception]
        stations = [
            box for box in app.selectbox if box.label == "Station"
        ]
        assert stations, "the timeline's station picker did not render"
        assert list(stations[0].options) == ["S02", "S05"]

    def test_the_page_reports_the_analytics_for_the_selected_station(
        self, tmp_path: Path, monkeypatch
    ):
        app = self._launch(tmp_path, monkeypatch)
        labels = {metric.label: metric.value for metric in app.metric}
        assert labels.get("Current risk") == "85.0%"
        assert labels.get("Peak risk") == "85.0%"
        assert labels.get("Threshold") == "40.0%"
        assert labels.get("Threshold crossings") == "1"

    def test_switching_station_shows_that_station_history(self, tmp_path: Path, monkeypatch):
        app = self._launch(tmp_path, monkeypatch)
        picker = next(box for box in app.selectbox if box.label == "Station")
        app = picker.set_value("S05").run()
        assert not app.exception, [str(e) for e in app.exception]
        labels = {metric.label: metric.value for metric in app.metric}
        assert labels.get("Current risk") == "20.0%"
        assert labels.get("Threshold crossings") == "0"


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
