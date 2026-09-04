"""Summary reader for ``defect_predictions.jsonl``.

Field names follow ``DASHBOARD_CONTRACTS.md`` section 4 (schema
``defect-prediction-v2``). Two contract details are honoured here:

* ``warning`` is the actionable alert and is intentionally suppressed at the final
  inspection station, so a record may carry ``threshold_crossed = true`` with
  ``warning = false``. Both are counted separately and neither is recomputed.
* This stream stays independent of the bottleneck stream. Nothing here joins them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DefectStreamSummary:
    """Shape of one defect prediction stream, not its conclusions."""

    exists: bool = False
    path: str | None = None
    record_count: int = 0
    warning_count: int = 0
    threshold_crossed_count: int = 0
    malformed_lines: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    run_ids: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)
    routes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "path": self.path,
            "record_count": self.record_count,
            "warning_count": self.warning_count,
            "threshold_crossed_count": self.threshold_crossed_count,
            "malformed_lines": self.malformed_lines,
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "run_ids": self.run_ids,
            "unit_count": len(self.unit_ids),
            "routes": self.routes,
        }


def read_defect_summary(path: str | Path) -> DefectStreamSummary:
    """Summarise a defect prediction stream. Missing files are not an error."""
    path = Path(path)
    summary = DefectStreamSummary(path=str(path))
    if not path.is_file():
        return summary
    summary.exists = True

    run_ids: set[str] = set()
    units: set[str] = set()
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
                if record.get("warning") is True:
                    summary.warning_count += 1
                if record.get("threshold_crossed") is True:
                    summary.threshold_crossed_count += 1

                timestamp = record.get("timestamp_ms")
                if isinstance(timestamp, (int, float)):
                    timestamp = int(timestamp)
                    if summary.first_timestamp_ms is None or timestamp < summary.first_timestamp_ms:
                        summary.first_timestamp_ms = timestamp
                    if summary.last_timestamp_ms is None or timestamp > summary.last_timestamp_ms:
                        summary.last_timestamp_ms = timestamp

                if record.get("run_id") is not None:
                    run_ids.add(str(record["run_id"]))
                if record.get("unit_id") is not None:
                    units.add(str(record["unit_id"]))

                route = record.get("route")
                if route:
                    summary.routes[str(route)] = summary.routes.get(str(route), 0) + 1
    except OSError as error:
        logger.warning("could not read defect stream %s: %s", path, error)

    summary.run_ids = sorted(run_ids)
    summary.unit_ids = sorted(units)
    return summary
