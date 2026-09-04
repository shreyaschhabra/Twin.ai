"""Readers for the authoritative coordinated-runtime artifacts.

``system_health.json`` stays the authoritative coordinated runtime health source and
``system_run_manifest.json`` the authoritative completed coordinated-run summary. This
module reads them; it never writes them, never derives a competing health verdict, and
never treats an absent file as a failure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: `overall_status` value that means the coordinated system is healthy.
HEALTH_PASS = "PASS"

#: Degraded operation: one subsystem isolated, the other still producing predictions.
HEALTH_DEGRADED = "DEGRADED"


def read_json_artifact(path: str | Path) -> dict[str, Any] | None:
    """Read a JSON artifact, returning None when absent or unreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("could not read %s: %s", path, error)
        return None
    return payload if isinstance(payload, dict) else None


def read_run_metadata(run_dir: str | Path) -> dict[str, Any] | None:
    """Simulator-written ``run_metadata.json`` from a completed run directory."""
    return read_json_artifact(Path(run_dir) / "run_metadata.json")


def read_system_health(output_dir: str | Path) -> dict[str, Any] | None:
    return read_json_artifact(Path(output_dir) / "system_health.json")


def read_system_manifest(output_dir: str | Path) -> dict[str, Any] | None:
    return read_json_artifact(Path(output_dir) / "system_run_manifest.json")


@dataclass(frozen=True)
class HealthView:
    """The health indicator the dashboard shell shows, straight from the artifact."""

    available: bool
    overall_status: str | None = None

    @property
    def is_pass(self) -> bool:
        return self.overall_status == HEALTH_PASS

    @property
    def is_degraded(self) -> bool:
        return self.overall_status == HEALTH_DEGRADED

    @property
    def label(self) -> str:
        if not self.available:
            return "No coordinated run health recorded"
        return self.overall_status or "UNKNOWN"


def health_view(output_dir: str | Path) -> HealthView:
    """Summarise ``system_health.json`` without reinterpreting it.

    Only ``overall_status == "PASS"`` counts as healthy, per the contract.
    """
    payload = read_system_health(output_dir)
    if payload is None:
        return HealthView(available=False)
    status = payload.get("overall_status")
    return HealthView(available=True, overall_status=str(status) if status else None)
