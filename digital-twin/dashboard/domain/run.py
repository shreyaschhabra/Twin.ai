"""The dashboard's notion of a production run.

One completed execution of the existing factory pipeline == one simulated production
day. The production-day index lives here, in the dashboard's own persistence layer; the
simulator has no such concept and is not modified to gain one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    """Lifecycle of a dashboard run record."""

    #: Requested by the dashboard, execution not started.
    PENDING = "PENDING"
    #: Underlying execution in progress; not yet eligible for ingestion.
    RUNNING = "RUNNING"
    #: Completed run artifacts exist and were ingested.
    COMPLETED = "COMPLETED"
    #: Execution failed; kept for history, carries no usable artifacts.
    FAILED = "FAILED"
    #: Artifacts exist but are incomplete (for example one prediction stream missing).
    PARTIAL = "PARTIAL"

    @classmethod
    def coerce(cls, value: Any) -> RunStatus:
        """Map a stored value to a status, defaulting to PENDING for unknown values."""
        if isinstance(value, cls):
            return value
        try:
            return cls(value.value if isinstance(value, Enum) else str(value))
        except ValueError:
            return cls.PENDING


@dataclass
class Run:
    """One persisted production run.

    ``artifact_path`` is the completed simulator run directory. ``predictions_path`` is
    the coordinated runtime output directory that holds the two prediction streams,
    ``system_health.json`` and ``system_run_manifest.json``. The dashboard stores paths,
    never copies -- those files remain the authoritative source.
    """

    run_id: str
    production_day: int
    status: RunStatus = RunStatus.PENDING
    scenario_name: str | None = None
    scenario_reference: str | None = None
    scenario_description: str | None = None
    multiplier: float = 60.0
    seed: int | None = None
    duration_ms: int | None = None
    factory_path: str = ""
    factory_fingerprint: str | None = None
    artifact_path: str | None = None
    predictions_path: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    is_demo: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def production_day_label(self) -> str:
        return f"Production Day {self.production_day}"

    @property
    def metadata_json(self) -> str | None:
        """Metadata serialised for storage."""
        return json.dumps(self.metadata, sort_keys=True) if self.metadata else None

    @classmethod
    def from_metadata_json(cls, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
