"""Live run sessions: a running pipeline plus the prediction history it has produced.

Streamlit re-executes the whole script on every interaction, so a plain local variable
holding a run's prediction history would be discarded several times a second. State
therefore lives in a module-level registry, which is created once per Python process and
survives every rerun, and is keyed by ``run_id`` so switching pages or stations never
loses what has accumulated.

The registry is a *cache*, not the record. The authoritative source is always the
``bottleneck_predictions.jsonl`` the existing runtime writes: a feed rebuilt from
scratch -- after a dashboard restart, or for a run this process never launched -- reads
the same file from byte zero and arrives at the same history. Nothing is reconstructed
from memory alone, and no prediction is ever synthesised.

Nothing here simulates or predicts. The subprocess it supervises is the canonical
``cli.py`` command built by :class:`~dashboard.orchestration.existing_runtime_adapter.ExistingRuntimeAdapter`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from dashboard import process_tree
from dashboard.live.bottleneck_state import LiveBottleneckState
from dashboard.live.defect_state import LiveDefectState
from dashboard.live.stream import JsonlTailer

logger = logging.getLogger(__name__)

#: Filenames of the two prediction streams inside a run's prediction output directory.
#: Mirrors ``system_runtime.output_paths``; the adapter remains authoritative when
#: available. The streams are never merged -- each gets its own feed and its own state.
BOTTLENECK_STREAM = "bottleneck_predictions.jsonl"
DEFECT_STREAM = "defect_predictions.jsonl"

#: How often the supervising thread pulls newly emitted records off disk. Short enough
#: that the UI sees fresh points on any rerun, long enough not to spin on a large file.
DEFAULT_POLL_INTERVAL_S = 1.0

#: Runtime stdout lines retained for display. A full run prints far more than a panel
#: can show, and only the recent tail is useful.
OUTPUT_TAIL = 400


class LiveRunStatus(str, Enum):
    """Lifecycle of a dashboard-launched run."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def finished(self) -> bool:
        return self in (LiveRunStatus.COMPLETED, LiveRunStatus.FAILED, LiveRunStatus.CANCELLED)


class LivePredictionFeed:
    """Incremental bottleneck history for one run's prediction output directory.

    Polling is idempotent and cheap: each call reads only the bytes appended since the
    last one. Calling it from the UI thread and from a supervising thread at the same
    time is safe.
    """

    def __init__(self, run_id: str, stream_path: str | Path, *, state: Any = None):
        self.run_id = run_id
        self.stream_path = Path(stream_path)
        #: Defaults to the bottleneck accumulator; pass ``state=LiveDefectState()`` for
        #: the defect stream. Both expose the same ``clear()``/``ingest(records)`` shape,
        #: so this class stays agnostic to which one it is tailing.
        self.state = LiveBottleneckState(run_id=None) if state is None else state
        self._tailer = JsonlTailer(self.stream_path)
        self._lock = threading.RLock()
        self.last_poll_at: float | None = None
        self.polls = 0
        self.malformed_lines = 0

    # -- ingestion --------------------------------------------------------------------

    def poll(self) -> int:
        """Ingest every record emitted since the previous poll. Returns how many."""
        with self._lock:
            result = self._tailer.read_new()
            if result.restarted:
                # The runtime deleted or rewrote its output, so anything held from the
                # previous file is no longer part of this stream.
                self.state.clear()
                self.malformed_lines = 0
            self.malformed_lines += result.malformed
            accepted = self.state.ingest(result.records)
            self.polls += 1
            self.last_poll_at = time.time()
            return accepted

    def reload(self) -> int:
        """Discard progress and re-read the whole stream from the beginning."""
        with self._lock:
            self.state.clear()
            self.malformed_lines = 0
            result = self._tailer.read_all()
            self.malformed_lines += result.malformed
            self.polls += 1
            self.last_poll_at = time.time()
            return self.state.ingest(result.records)

    # -- reading ----------------------------------------------------------------------

    @property
    def stream_exists(self) -> bool:
        return self._tailer.exists()

    @property
    def bytes_consumed(self) -> int:
        return self._tailer.offset

    def snapshot(self) -> Any:
        """The accumulated state. Read-only from the caller's point of view."""
        return self.state


@dataclass
class LiveRunProgress:
    """What the UI needs to describe a run without touching the process object."""

    run_id: str
    status: LiveRunStatus
    started_at: float | None
    finished_at: float | None
    exit_code: int | None
    error: str | None
    record_count: int
    warning_count: int
    station_count: int
    latest_timestamp_ms: int | None
    ingested: bool

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at


class LiveRunSession:
    """One dashboard-launched run: the subprocess plus its live prediction feed.

    The subprocess is supervised on a background thread that does two things and no
    more: it drains the pipeline's stdout so the pipe cannot fill and stall the run, and
    it polls the prediction stream so history keeps accumulating even while nobody is
    looking at the page. Neither the Streamlit script nor the supervising thread ever
    blocks waiting for the pipeline to finish.
    """

    def __init__(
        self,
        run_id: str,
        stream_path: str | Path,
        *,
        defect_stream_path: str | Path | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ):
        self.run_id = run_id
        self.feed = LivePredictionFeed(run_id, stream_path)
        # Both prediction streams live as siblings under the same output directory
        # (see ``system_runtime.output_paths``); default to that sibling when the
        # caller does not name it explicitly.
        resolved_defect_path = (
            Path(defect_stream_path)
            if defect_stream_path is not None
            else Path(stream_path).parent / DEFECT_STREAM
        )
        self.defect_feed = LivePredictionFeed(
            run_id, resolved_defect_path, state=LiveDefectState()
        )
        self.poll_interval_s = poll_interval_s
        self.status = LiveRunStatus.IDLE
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        #: Set once the completed run has been recorded in dashboard history, so the
        #: UI ingests it exactly once without re-deriving the timeline.
        self.ingested = False
        self.plan: Any = None
        self.output_lines: deque[str] = deque(maxlen=OUTPUT_TAIL)
        self._process: Any = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    # -- lifecycle --------------------------------------------------------------------

    def start(self, launch: Callable[[], Any], *, plan: Any = None) -> None:
        """Start the run. Returns as soon as the process exists, never at its end.

        ``launch`` is expected to be the adapter's ``launch_planned_run``; the session
        does not build commands or know what the pipeline does.
        """
        with self._lock:
            if self.status == LiveRunStatus.RUNNING:
                raise RuntimeError(f"Run {self.run_id} is already running")
            self.plan = plan
            self.status = LiveRunStatus.RUNNING
            self.started_at = time.time()
            self.finished_at = None
            self.exit_code = None
            self.error = None
            self.ingested = False
            self.output_lines.clear()

        try:
            self._process = launch()
        except Exception as error:  # the command could not even be started
            with self._lock:
                self.status = LiveRunStatus.FAILED
                self.error = str(error)
                self.finished_at = time.time()
            raise

        self._thread = threading.Thread(
            target=self._supervise, name=f"live-run-{self.run_id}", daemon=True
        )
        self._thread.start()

    def _supervise(self) -> None:
        process = self._process
        last_poll = 0.0
        try:
            stdout = getattr(process, "stdout", None)
            if stdout is not None:
                for line in stdout:
                    with self._lock:
                        self.output_lines.append(line.rstrip())
                    now = time.time()
                    if now - last_poll >= self.poll_interval_s:
                        last_poll = now
                        self._safe_poll()
            code = process.wait()
        except Exception as error:  # pragma: no cover - defensive around the process
            logger.warning("live run %s supervision failed: %s", self.run_id, error)
            with self._lock:
                self.error = str(error)
                self.status = LiveRunStatus.FAILED
                self.finished_at = time.time()
            return

        # One final drain, so the last batch the consumer wrote is never lost.
        self._safe_poll()
        with self._lock:
            self.exit_code = code
            self.finished_at = time.time()
            if self.status == LiveRunStatus.CANCELLED:
                pass
            elif code == 0:
                self.status = LiveRunStatus.COMPLETED
            else:
                self.status = LiveRunStatus.FAILED
                self.error = self.error or f"Factory runtime exited with code {code}."

    def _safe_poll(self) -> int:
        """Poll both prediction streams. Returns the bottleneck stream's new-record count."""
        bottleneck_count = 0
        try:
            bottleneck_count = self.feed.poll()
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("polling %s failed: %s", self.feed.stream_path, error)
        try:
            self.defect_feed.poll()
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("polling %s failed: %s", self.defect_feed.stream_path, error)
        return bottleneck_count

    def cancel(self) -> None:
        """Ask the pipeline to stop. The dashboard keeps whatever it already produced.

        The launched process is ``cli.py system run random``, which spawns the two
        prediction consumers as its own children. Terminating just the top process
        leaves those running (Windows never reaps them, and they would keep writing
        to the prediction streams for minutes), so the whole process tree is taken
        down together -- see :mod:`dashboard.process_tree`.
        """
        with self._lock:
            if self.status != LiveRunStatus.RUNNING:
                return
            self.status = LiveRunStatus.CANCELLED
        process = self._process
        if process is not None:
            try:
                process_tree.terminate_tree(process)
            except Exception as error:  # pragma: no cover - defensive
                logger.warning("could not terminate run %s: %s", self.run_id, error)

    # -- reading ----------------------------------------------------------------------

    def refresh(self) -> int:
        """Pull any records written since the last look. Safe to call every rerun."""
        return self._safe_poll()

    @property
    def is_running(self) -> bool:
        return self.status == LiveRunStatus.RUNNING

    @property
    def state(self) -> LiveBottleneckState:
        return self.feed.state

    @property
    def defect_state(self) -> LiveDefectState:
        return self.defect_feed.state

    def recent_output(self, limit: int = 20) -> list[str]:
        with self._lock:
            return list(self.output_lines)[-limit:]

    def progress(self) -> LiveRunProgress:
        state = self.feed.state
        with self._lock:
            return LiveRunProgress(
                run_id=self.run_id,
                status=self.status,
                started_at=self.started_at,
                finished_at=self.finished_at,
                exit_code=self.exit_code,
                error=self.error,
                record_count=state.record_count,
                warning_count=state.warning_count,
                station_count=len(state.stations),
                latest_timestamp_ms=state.last_timestamp_ms,
                ingested=self.ingested,
            )

    def mark_ingested(self) -> None:
        with self._lock:
            self.ingested = True


class LiveRunRegistry:
    """Process-wide home for live sessions and rehydrated feeds.

    Streamlit's script reruns cannot be relied on to preserve anything, and
    ``st.session_state`` is per browser session, so a run started in one tab would be
    invisible in another. A module-level registry keyed by ``run_id`` gives one home per
    Python process.
    """

    def __init__(self):
        self._sessions: dict[str, LiveRunSession] = {}
        self._feeds: dict[str, LivePredictionFeed] = {}
        self._defect_feeds: dict[str, LivePredictionFeed] = {}
        self._lock = threading.RLock()

    # -- sessions ---------------------------------------------------------------------

    def create_session(
        self,
        run_id: str,
        stream_path: str | Path,
        *,
        defect_stream_path: str | Path | None = None,
        poll_interval_s: float | None = None,
    ) -> LiveRunSession:
        """Register a session for ``run_id``, replacing any finished one."""
        with self._lock:
            existing = self._sessions.get(run_id)
            if existing is not None and existing.is_running:
                raise RuntimeError(f"Run {run_id} is already running")
            session = LiveRunSession(
                run_id,
                stream_path,
                defect_stream_path=defect_stream_path,
                poll_interval_s=(
                    DEFAULT_POLL_INTERVAL_S if poll_interval_s is None else poll_interval_s
                ),
            )
            self._sessions[run_id] = session
            # A session's own feeds supersede any read-only feeds for the same run.
            self._feeds.pop(run_id, None)
            self._defect_feeds.pop(run_id, None)
            return session

    def session(self, run_id: str) -> LiveRunSession | None:
        with self._lock:
            return self._sessions.get(run_id)

    def sessions(self) -> list[LiveRunSession]:
        with self._lock:
            return list(self._sessions.values())

    def active_session(self) -> LiveRunSession | None:
        """The one run currently executing, if any."""
        with self._lock:
            for session in self._sessions.values():
                if session.is_running:
                    return session
            return None

    def latest_session(self) -> LiveRunSession | None:
        """The most recently started session, running or not."""
        with self._lock:
            candidates = [s for s in self._sessions.values() if s.started_at is not None]
            if not candidates:
                return None
            return max(candidates, key=lambda s: s.started_at or 0.0)

    def discard(self, run_id: str) -> None:
        with self._lock:
            self._sessions.pop(run_id, None)
            self._feeds.pop(run_id, None)
            self._defect_feeds.pop(run_id, None)

    def clear(self) -> None:
        """Drop every session and feed. Intended for tests."""
        with self._lock:
            self._sessions.clear()
            self._feeds.clear()
            self._defect_feeds.clear()

    # -- feeds ------------------------------------------------------------------------

    def feed(self, run_id: str, stream_path: str | Path) -> LivePredictionFeed:
        """The bottleneck feed for ``run_id``, rebuilt from the stream file when unknown.

        This is what makes a completed run need no second processing step and a restarted
        dashboard lose nothing: the history is re-derived from the same file the runtime
        wrote, by the same code path the live run used.
        """
        with self._lock:
            session = self._sessions.get(run_id)
            if session is not None:
                return session.feed
            feed = self._feeds.get(run_id)
            if feed is not None and feed.stream_path == Path(stream_path):
                feed.poll()
                return feed
            feed = LivePredictionFeed(run_id, stream_path)
            self._feeds[run_id] = feed
            feed.poll()
            return feed

    def defect_feed(self, run_id: str, stream_path: str | Path) -> LivePredictionFeed:
        """The defect feed for ``run_id``, rebuilt from the stream file when unknown.

        The read-only-rehydration sibling of :meth:`feed`, for a run this process did
        not launch (ingested earlier, or from a previous dashboard start).
        """
        with self._lock:
            session = self._sessions.get(run_id)
            if session is not None:
                return session.defect_feed
            feed = self._defect_feeds.get(run_id)
            if feed is not None and feed.stream_path == Path(stream_path):
                feed.poll()
                return feed
            feed = LivePredictionFeed(run_id, stream_path, state=LiveDefectState())
            self._defect_feeds[run_id] = feed
            feed.poll()
            return feed


#: The one registry per dashboard process. Imported, never re-instantiated by views.
_REGISTRY = LiveRunRegistry()


def get_registry() -> LiveRunRegistry:
    """The process-wide live-run registry."""
    return _REGISTRY


def bottleneck_stream_path(predictions_dir: str | Path) -> Path:
    """The bottleneck stream inside a run's prediction output directory."""
    return Path(predictions_dir) / BOTTLENECK_STREAM


def defect_stream_path(predictions_dir: str | Path) -> Path:
    """The defect stream inside a run's prediction output directory."""
    return Path(predictions_dir) / DEFECT_STREAM
