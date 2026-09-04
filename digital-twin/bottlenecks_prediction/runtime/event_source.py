"""Small ordered-event seam shared by replay, simulator, and future plant inputs."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class SequentialEventSource(Protocol):
    """Yields station/evidence events in causal, nondecreasing time order."""

    def __iter__(self) -> Iterator[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class OrderedEvents:
    """Validate an iterable at the live-runtime boundary instead of re-sorting it."""

    events: Iterable[Mapping[str, Any]]

    def __iter__(self) -> Iterator[Mapping[str, Any]]:
        previous: int | None = None
        for event in self.events:
            if "timestamp_ms" not in event:
                raise ValueError("Sequential event source emitted an event without timestamp_ms")
            timestamp = int(event["timestamp_ms"])
            if previous is not None and timestamp < previous:
                raise ValueError(
                    f"Sequential event source is out of order: {timestamp} follows {previous}"
                )
            previous = timestamp
            yield event


class CsvStationEventSource(OrderedEvents):
    """Completed-run adapter. CSV remains a replay source, not a second pipeline."""

    def __init__(self, station_events_csv: str | Path):
        events = pd.read_csv(station_events_csv)
        required = {"timestamp_ms", "station_id", "event_type"}
        missing = sorted(required - set(events.columns))
        if missing:
            raise ValueError(f"station_events.csv missing columns: {missing}")
        # Simulator output is already ordered. Stable sort makes legacy CSV replay
        # deterministic while preserving equal-time causal emission order.
        events = events.assign(_source_sequence=range(len(events))).sort_values(
            ["timestamp_ms", "_source_sequence"], kind="stable"
        )
        super().__init__([row._asdict() for row in events.drop(columns="_source_sequence").itertuples(index=False)])
