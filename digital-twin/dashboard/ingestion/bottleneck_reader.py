"""Summary reader for ``bottleneck_predictions.jsonl``.

Field names follow ``DASHBOARD_CONTRACTS.md`` section 3 (schema
``bottleneck-prediction-v1``). This module only counts and bounds the stream so a run
can be recorded in history; it does not aggregate risk, and it never merges the
bottleneck stream with the defect stream. Analytics belong to later work that reads the
JSONL directly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BottleneckStreamSummary:
    """Shape of one bottleneck prediction stream, not its conclusions."""

    exists: bool = False
    path: str | None = None
    record_count: int = 0
    warning_count: int = 0
    malformed_lines: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    run_ids: list[str] = field(default_factory=list)
    station_ids: list[str] = field(default_factory=list)
    routes: dict[str, int] = field(default_factory=dict)
    zones: dict[str, int] = field(default_factory=dict)
    unknown_categories_seen: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "path": self.path,
            "record_count": self.record_count,
            "warning_count": self.warning_count,
            "malformed_lines": self.malformed_lines,
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "run_ids": self.run_ids,
            "station_count": len(self.station_ids),
            "routes": self.routes,
            "zones": self.zones,
            "unknown_categories_seen": self.unknown_categories_seen,
        }


def read_bottleneck_summary(path: str | Path) -> BottleneckStreamSummary:
    """Summarise a bottleneck prediction stream. Missing files are not an error."""
    path = Path(path)
    summary = BottleneckStreamSummary(path=str(path))
    if not path.is_file():
        return summary
    summary.exists = True

    run_ids: set[str] = set()
    stations: set[str] = set()
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    summary.malformed_lines += 1
                    continue
                if not isinstance(record, dict):
                    summary.malformed_lines += 1
                    continue

                summary.record_count += 1
                # `warning` is the actionable alert per the contract; the dashboard
                # never recomputes it from probability and threshold.
                if record.get("warning") is True:
                    summary.warning_count += 1

                timestamp = record.get("timestamp_ms")
                if isinstance(timestamp, (int, float)):
                    timestamp = int(timestamp)
                    if summary.first_timestamp_ms is None or timestamp < summary.first_timestamp_ms:
                        summary.first_timestamp_ms = timestamp
                    if summary.last_timestamp_ms is None or timestamp > summary.last_timestamp_ms:
                        summary.last_timestamp_ms = timestamp

                if record.get("run_id") is not None:
                    run_ids.add(str(record["run_id"]))
                if record.get("station_id") is not None:
                    stations.add(str(record["station_id"]))

                route = record.get("route")
                if route:
                    summary.routes[str(route)] = summary.routes.get(str(route), 0) + 1
                zone = record.get("zone")
                if zone:
                    summary.zones[str(zone)] = summary.zones.get(str(zone), 0) + 1

                diagnostics = record.get("diagnostics")
                if isinstance(diagnostics, dict) and diagnostics.get("unknown_categories"):
                    summary.unknown_categories_seen = True
    except OSError as error:
        logger.warning("could not read bottleneck stream %s: %s", path, error)

    summary.run_ids = sorted(run_ids)
    summary.station_ids = sorted(stations)
    return summary
