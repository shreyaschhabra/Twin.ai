"""
Loads a FactoryConfig from YAML files.

Deliberately takes two file paths (station type templates + a line
definition) rather than one combined file, so the same ~10 station-type
templates can be shared between the 12-station development line and the
eventual 45-station final line without duplication.

Usage:
    config = load_factory_config(
        station_types_path="configs/station_types.yaml",
        line_path="configs/development_line.yaml",
    )

Swapping `line_path` to a future `configs/full_line.yaml` (45 stations) is
the only change needed to move to the final configuration — no changes to
this loader or to backend/config/schemas.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml

from backend.config.schemas import (
    Buffer,
    FactoryConfig,
    StationInstance,
    StationType,
    VehicleVariant,
)

PathLike = Union[str, Path]


def load_factory_config(station_types_path: PathLike, line_path: PathLike) -> FactoryConfig:
    station_types_raw = _read_yaml(station_types_path)
    line_raw = _read_yaml(line_path)

    station_types = {
        type_id: StationType(**{**fields, "type_id": type_id})
        for type_id, fields in station_types_raw.get("station_types", {}).items()
    }

    stations = {
        station_id: StationInstance(**{**fields, "station_id": station_id})
        for station_id, fields in line_raw.get("stations", {}).items()
    }

    buffers = {
        buffer_id: Buffer(**{**fields, "buffer_id": buffer_id})
        for buffer_id, fields in line_raw.get("buffers", {}).items()
    }

    vehicle_variants = {
        variant_id: VehicleVariant(**{**fields, "variant_id": variant_id})
        for variant_id, fields in line_raw.get("vehicle_variants", {}).items()
    }

    # FactoryConfig's model_validator runs all cross-reference checks here.
    return FactoryConfig(
        line_name=line_raw.get("line_name", "unnamed_line"),
        station_types=station_types,
        stations=stations,
        buffers=buffers,
        vehicle_variants=vehicle_variants,
    )


def _read_yaml(path: PathLike) -> dict:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")
    with resolved.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}
