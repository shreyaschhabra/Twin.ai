"""Load and apply the versioned Flow-v3 line-rebalance overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.config.schemas import FactoryConfig


def load_rebalance_plan(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        plan = yaml.safe_load(handle) or {}
    if not plan.get("plan_id"):
        raise ValueError("rebalance plan requires plan_id")
    return plan


def apply_rebalance(config: FactoryConfig, plan: dict[str, Any]) -> FactoryConfig:
    """Return a newly validated config; never mutate the Flow-v2 config."""
    raw = config.model_dump(mode="python")
    for station_id, change in plan.get("cycle_time_overrides", {}).items():
        if station_id not in raw["stations"]:
            raise ValueError(f"unknown rebalance station {station_id}")
        actual = float(raw["stations"][station_id]["baseline_cycle_time_seconds"])
        declared = float(change["old_seconds"])
        if actual != declared:
            raise ValueError(f"{station_id} old cycle mismatch: config={actual}, plan={declared}")
        raw["stations"][station_id]["baseline_cycle_time_seconds"] = float(change["new_seconds"])

    for buffer_id, change in plan.get("buffer_capacity_overrides", {}).items():
        if buffer_id not in raw["buffers"]:
            raise ValueError(f"unknown rebalance buffer {buffer_id}")
        actual = int(raw["buffers"][buffer_id]["capacity"])
        declared = int(change["old_capacity"])
        if actual != declared:
            raise ValueError(f"{buffer_id} old capacity mismatch: config={actual}, plan={declared}")
        raw["buffers"][buffer_id]["capacity"] = int(change["new_capacity"])

    return FactoryConfig.model_validate(raw)
