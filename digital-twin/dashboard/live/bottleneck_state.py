"""Accumulated bottleneck prediction history, updated one record at a time.

This is the dashboard's live view of the *existing* runtime's output. It stores what the
bottleneck consumer emitted and derives only descriptive statistics over those emitted
points. It never scores, smooths, interpolates or invents a sample: every point in a
series corresponds to exactly one line the runtime wrote, and the series advances on the
record's own ``timestamp_ms`` (the simulator clock), never on wall-clock time.

Per the dashboard contract, ``warning`` is taken verbatim from the record and is never
recomputed from probability and threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

#: Fraction of the probability scale a trend has to move before it is called a trend.
TREND_DEADBAND = 0.02

TREND_RISING = "RISING"
TREND_FALLING = "FALLING"
TREND_STABLE = "STABLE"
TREND_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PredictionPoint:
    """One bottleneck prediction, on the simulator clock."""

    timestamp_ms: int
    probability: float
    warning: bool
    threshold: float | None = None
    zone: str | None = None
    route: str | None = None
    state_confidence: float | None = None
    vehicle_id: str | None = None
    prediction_trigger: str | None = None

    @property
    def risk_percent(self) -> float:
        return self.probability * 100.0

    @property
    def threshold_percent(self) -> float | None:
        return None if self.threshold is None else self.threshold * 100.0


@dataclass(frozen=True)
class WarningPeriod:
    """A contiguous stretch of records whose ``warning`` flag was true.

    ``start_ms`` and ``end_ms`` are the first and last flagged records' own timestamps.
    A period that is still accumulating has ``open_ended`` set: its ``end_ms`` is simply
    the newest flagged record so far, not a claim that the period has ended there.
    """

    start_ms: int
    end_ms: int
    point_count: int
    open_ended: bool = False

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class StationAnalytics:
    """Descriptive temporal analytics over one station's accumulated history."""

    station_id: str
    point_count: int = 0
    current_risk: float | None = None
    peak_risk: float | None = None
    average_risk: float | None = None
    threshold: float | None = None
    threshold_crossings: int = 0
    time_above_threshold_ms: int = 0
    warning_count: int = 0
    warning_periods: tuple[WarningPeriod, ...] = ()
    trend: str = TREND_UNKNOWN
    trend_delta: float = 0.0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    warning_now: bool = False

    @property
    def observed_span_ms(self) -> int:
        if self.first_timestamp_ms is None or self.last_timestamp_ms is None:
            return 0
        return self.last_timestamp_ms - self.first_timestamp_ms


class StationSeries:
    """One station's prediction history plus running aggregates.

    Aggregates are maintained on append rather than recomputed on read, so a long run
    stays cheap to display and the numbers shown mid-run are the same ones the finished
    file would produce.
    """

    def __init__(self, station_id: str):
        self.station_id = station_id
        self.points: list[PredictionPoint] = []
        self._probability_sum = 0.0
        self._peak: float | None = None
        self._threshold: float | None = None
        self._warning_count = 0
        self._crossings = 0
        self._time_above_ms = 0
        self._periods: list[list[int]] = []  # [start_ms, end_ms, point_count]
        self._open_period = False
        self._previous_warning = False

    # -- accumulation ----------------------------------------------------------------

    def append(self, point: PredictionPoint) -> None:
        previous = self.points[-1] if self.points else None
        self.points.append(point)
        self._probability_sum += point.probability
        if self._peak is None or point.probability > self._peak:
            self._peak = point.probability
        if point.threshold is not None:
            self._threshold = point.threshold

        if point.warning:
            self._warning_count += 1
            if not self._previous_warning:
                # A crossing is a transition into the warning state, so the first
                # record of a run counts only if it is already flagged.
                self._crossings += 1
                self._periods.append([point.timestamp_ms, point.timestamp_ms, 1])
            else:
                current = self._periods[-1]
                current[1] = point.timestamp_ms
                current[2] += 1
                if previous is not None:
                    # Elapsed simulator time between two consecutive flagged records.
                    # An isolated flagged record contributes nothing, because nothing
                    # observed says how long it lasted.
                    self._time_above_ms += max(0, point.timestamp_ms - previous.timestamp_ms)
            self._open_period = True
        else:
            self._open_period = False
        self._previous_warning = point.warning

    # -- reading ---------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.points)

    @property
    def latest(self) -> PredictionPoint | None:
        return self.points[-1] if self.points else None

    def warning_periods(self) -> tuple[WarningPeriod, ...]:
        last = len(self._periods) - 1
        return tuple(
            WarningPeriod(
                start_ms=start,
                end_ms=end,
                point_count=count,
                open_ended=self._open_period and index == last,
            )
            for index, (start, end, count) in enumerate(self._periods)
        )

    def trend(self) -> tuple[str, float]:
        """Compare the newest window of points against the one before it.

        Descriptive only: it summarises points the runtime already emitted and does not
        forecast. Fewer than four points is not enough to call a direction.
        """
        count = len(self.points)
        if count < 4:
            return TREND_UNKNOWN, 0.0
        window = min(20, count // 2)
        recent = self.points[-window:]
        earlier = self.points[-2 * window : -window]
        recent_mean = sum(p.probability for p in recent) / len(recent)
        earlier_mean = sum(p.probability for p in earlier) / len(earlier)
        delta = recent_mean - earlier_mean
        if abs(delta) < TREND_DEADBAND:
            return TREND_STABLE, delta
        return (TREND_RISING if delta > 0 else TREND_FALLING), delta

    def analytics(self) -> StationAnalytics:
        latest = self.latest
        trend, delta = self.trend()
        return StationAnalytics(
            station_id=self.station_id,
            point_count=len(self.points),
            current_risk=latest.probability if latest else None,
            peak_risk=self._peak,
            average_risk=(self._probability_sum / len(self.points)) if self.points else None,
            threshold=self._threshold,
            threshold_crossings=self._crossings,
            time_above_threshold_ms=self._time_above_ms,
            warning_count=self._warning_count,
            warning_periods=self.warning_periods(),
            trend=trend,
            trend_delta=delta,
            first_timestamp_ms=self.points[0].timestamp_ms if self.points else None,
            last_timestamp_ms=latest.timestamp_ms if latest else None,
            warning_now=bool(latest.warning) if latest else False,
        )

    def rows(self) -> list[dict[str, Any]]:
        """Chart-ready rows, in emission order along the simulator clock."""
        return [
            {
                "timestamp_ms": p.timestamp_ms,
                "probability": p.probability,
                "risk_percent": p.risk_percent,
                "threshold": p.threshold,
                "threshold_percent": p.threshold_percent,
                "warning": p.warning,
                "zone": p.zone,
                "route": p.route,
                "state_confidence": p.state_confidence,
                "vehicle_id": p.vehicle_id,
            }
            for p in self.points
        ]


def parse_point(record: dict[str, Any]) -> PredictionPoint | None:
    """Turn one contract record into a point, or None when it is unusable.

    Only ``timestamp_ms`` and ``bottleneck_probability`` are mandatory: a record without
    a simulator timestamp cannot be placed on the axis, and one without a probability
    has nothing to plot. Every other field degrades to None.
    """
    timestamp = record.get("timestamp_ms")
    probability = record.get("bottleneck_probability")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
        return None
    if not isinstance(probability, (int, float)) or isinstance(probability, bool):
        return None
    probability = float(probability)
    if math.isnan(probability):
        return None
    threshold = record.get("decision_threshold")
    confidence = record.get("state_confidence")
    return PredictionPoint(
        timestamp_ms=int(timestamp),
        probability=probability,
        # Taken verbatim from the stream; never derived from probability >= threshold.
        warning=record.get("warning") is True,
        threshold=float(threshold) if isinstance(threshold, (int, float)) else None,
        zone=str(record["zone"]) if record.get("zone") is not None else None,
        route=str(record["route"]) if record.get("route") is not None else None,
        state_confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        vehicle_id=str(record["vehicle_id"]) if record.get("vehicle_id") is not None else None,
        prediction_trigger=(
            str(record["prediction_trigger"])
            if record.get("prediction_trigger") is not None
            else None
        ),
    )


@dataclass
class LiveBottleneckState:
    """Every station's accumulated bottleneck history for one run.

    The same object serves a run in progress and a finished one: ingesting the tail of a
    growing file and ingesting a completed file take the identical path, so a completed
    run needs no separate processing step to become a timeline.
    """

    run_id: str | None = None
    stations: dict[str, StationSeries] = field(default_factory=dict)
    record_count: int = 0
    warning_count: int = 0
    skipped_records: int = 0
    foreign_run_records: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None

    # -- ingestion --------------------------------------------------------------------

    def ingest(self, records: Iterable[dict[str, Any]]) -> int:
        """Add records to the history. Returns how many were accepted."""
        accepted = 0
        for record in records:
            station_id = record.get("station_id")
            if station_id is None:
                self.skipped_records += 1
                continue
            record_run = record.get("run_id")
            if record_run is not None:
                record_run = str(record_run)
                if self.run_id is None:
                    self.run_id = record_run
                elif record_run != self.run_id:
                    # Streams from different runs are never combined.
                    self.foreign_run_records += 1
                    continue
            point = parse_point(record)
            if point is None:
                self.skipped_records += 1
                continue

            key = str(station_id)
            series = self.stations.get(key)
            if series is None:
                series = StationSeries(key)
                self.stations[key] = series
            series.append(point)

            self.record_count += 1
            accepted += 1
            if point.warning:
                self.warning_count += 1
            if self.first_timestamp_ms is None or point.timestamp_ms < self.first_timestamp_ms:
                self.first_timestamp_ms = point.timestamp_ms
            if self.last_timestamp_ms is None or point.timestamp_ms > self.last_timestamp_ms:
                self.last_timestamp_ms = point.timestamp_ms
        return accepted

    def clear(self) -> None:
        self.stations.clear()
        self.record_count = 0
        self.warning_count = 0
        self.skipped_records = 0
        self.foreign_run_records = 0
        self.first_timestamp_ms = None
        self.last_timestamp_ms = None

    # -- reading ----------------------------------------------------------------------

    def station_ids(self) -> list[str]:
        return sorted(self.stations)

    def series(self, station_id: str) -> StationSeries | None:
        return self.stations.get(station_id)

    def latest(self, station_id: str) -> PredictionPoint | None:
        series = self.stations.get(station_id)
        return series.latest if series else None

    def analytics(self, station_id: str) -> StationAnalytics:
        series = self.stations.get(station_id)
        return series.analytics() if series else StationAnalytics(station_id=station_id)

    def latest_by_station(self) -> dict[str, PredictionPoint]:
        return {
            station_id: series.latest
            for station_id, series in self.stations.items()
            if series.latest is not None
        }

    def active_warning_stations(self) -> list[str]:
        """Stations whose most recent emitted prediction carries ``warning``."""
        return sorted(
            station_id for station_id, point in self.latest_by_station().items() if point.warning
        )
