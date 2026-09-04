"""Structural validation of ``factory.json`` against the existing simulator contract.

The authority for these rules is ``simulation/src/ConfigLoader.cpp``. This module is a
read-only mirror of that contract so the dashboard can report VALID / INVALID without
launching the C++ simulator. It never rewrites or repairs a factory definition.

Two distinct result channels are produced:

``errors``
    The factory would be rejected by ``ConfigLoader::load``. The dashboard must treat
    the configuration as unusable.

``warnings``
    The factory is accepted by the simulator but violates a dashboard *generation*
    policy (for example the 3-station DARK corridor cap the demo generator applies).
    The repository's own ``simulation/config/factory.json`` legitimately carries a
    4-station corridor, so these are never promoted to errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Station archetypes accepted by ``ConfigLoader::validArchetype``.
ARCHETYPES = ("AUTOMATED", "MANUAL", "INSPECTION")

#: Sensor coverage levels accepted by ``ConfigLoader::validCoverage``.
SENSOR_COVERAGE = ("HIGH", "PARTIAL", "NONE")

#: Checkpoint kinds accepted by the simulator's checkpoint block.
CHECKPOINT_TYPES = ("RFID", "POWER_DRAW")

#: Minimum stations required by ``ConfigLoader`` ("line needs at least three stations").
MIN_STATIONS = 3

#: Shortest DARK corridor the simulator accepts (``startStationId >= endStationId`` fails).
MIN_DARK_CORRIDOR = 2

#: Longest DARK corridor the dashboard demo generator will emit. Policy, not a simulator
#: rule -- longer corridors are reported as warnings only.
MAX_DARK_CORRIDOR_POLICY = 3


@dataclass
class FactoryValidation:
    """Outcome of validating one factory definition."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_stations(stations: Any, errors: list[str]) -> list[dict[str, Any]]:
    """Validate the stations array and return the entries that parsed cleanly, id-ordered."""
    if not isinstance(stations, list):
        errors.append("stations must be an array")
        return []
    if len(stations) < MIN_STATIONS:
        errors.append(
            f"stations must contain at least {MIN_STATIONS} entries (simulator requirement)"
        )

    parsed: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, station in enumerate(stations):
        label = f"stations[{index}]"
        if not isinstance(station, dict):
            errors.append(f"{label} must be an object")
            continue

        station_id = station.get("id")
        if not _is_int(station_id):
            errors.append(f"{label}.id must be an integer")
        elif station_id in seen_ids:
            errors.append(f"{label}.id duplicates station {station_id}")
        else:
            seen_ids.add(station_id)

        name = station.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}.name must be a non-empty string")

        if station.get("archetype") not in ARCHETYPES:
            errors.append(f"{label}.archetype must be one of {', '.join(ARCHETYPES)}")

        cycle_time = station.get("meanCycleTimeMs")
        if not _is_int(cycle_time) or cycle_time <= 0:
            errors.append(f"{label}.meanCycleTimeMs must be a positive integer")

        cv = station.get("cycleTimeCV")
        if not _is_number(cv) or cv < 0:
            errors.append(f"{label}.cycleTimeCV must be a number >= 0")

        buffer_capacity = station.get("bufferCapacity")
        if not _is_int(buffer_capacity) or buffer_capacity < 0:
            errors.append(f"{label}.bufferCapacity must be an integer >= 0")

        if station.get("sensorCoverage") not in SENSOR_COVERAGE:
            errors.append(f"{label}.sensorCoverage must be one of {', '.join(SENSOR_COVERAGE)}")

        parsed.append(station)

    # The simulator sorts by id, then requires ids to be exactly 0..n-1 and the first/last
    # station in that order to be the source/sink.
    ordered = sorted((s for s in parsed if _is_int(s.get("id"))), key=lambda s: s["id"])
    if ordered and [s["id"] for s in ordered] != list(range(len(ordered))):
        errors.append("station ids must be contiguous from 0")
    if len(ordered) >= MIN_STATIONS:
        if ordered[0].get("source") is not True:
            errors.append("the first station (id 0) must set source=true")
        if ordered[-1].get("sink") is not True:
            errors.append(f"the last station (id {ordered[-1]['id']}) must set sink=true")
        extra_sources = [s["id"] for s in ordered[1:] if s.get("source") is True]
        if extra_sources:
            errors.append(f"only station 0 may be the source; also marked: {extra_sources}")
        extra_sinks = [s["id"] for s in ordered[:-1] if s.get("sink") is True]
        if extra_sinks:
            errors.append(f"only the last station may be the sink; also marked: {extra_sinks}")
    return ordered


def _validate_checkpoints(checkpoints: Any, station_ids: set[int], errors: list[str]) -> None:
    if checkpoints is None:
        return
    if not isinstance(checkpoints, list):
        errors.append("checkpoints must be an array when present")
        return

    seen: set[str] = set()
    for index, checkpoint in enumerate(checkpoints):
        label = f"checkpoints[{index}]"
        if not isinstance(checkpoint, dict):
            errors.append(f"{label} must be an object")
            continue

        checkpoint_id = checkpoint.get("id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            errors.append(f"{label}.id must be a non-empty string")
        elif checkpoint_id in seen:
            errors.append(f"{label}.id duplicates an earlier checkpoint id")
        else:
            seen.add(checkpoint_id)

        station_id = checkpoint.get("stationId")
        if not _is_int(station_id) or station_id not in station_ids:
            errors.append(f"{label}.stationId must reference an existing station")

        if checkpoint.get("type") not in CHECKPOINT_TYPES:
            errors.append(f"{label}.type must be one of {', '.join(CHECKPOINT_TYPES)}")

        progress = checkpoint.get("progress")
        if not _is_number(progress) or not (0 < progress < 1):
            errors.append(f"{label}.progress is required and must be strictly between 0 and 1")

        reliability = checkpoint.get("reliability")
        if not _is_number(reliability) or not (0 <= reliability <= 1):
            errors.append(f"{label}.reliability is required and must be between 0 and 1")

        false_positive = checkpoint.get("falsePositiveRate", 0.0)
        if not _is_number(false_positive) or not (0 <= false_positive <= 1):
            errors.append(f"{label}.falsePositiveRate must be between 0 and 1")


def _validate_dark_zones(
    dark_zones: Any,
    ordered_stations: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    if dark_zones is None:
        return
    if not isinstance(dark_zones, list):
        errors.append("darkZones must be an array when present")
        return

    station_ids = {s["id"] for s in ordered_stations}
    archetype_by_id = {s["id"]: s.get("archetype") for s in ordered_stations}
    station_count = len(ordered_stations)

    seen: set[str] = set()
    previous_end: int | None = None
    for index, zone in enumerate(dark_zones):
        label = f"darkZones[{index}]"
        if not isinstance(zone, dict):
            errors.append(f"{label} must be an object")
            continue

        zone_id = zone.get("id")
        if not isinstance(zone_id, str) or not zone_id.strip():
            errors.append(f"{label}.id must be a non-empty string")
        elif zone_id in seen:
            errors.append(f"{label}.id duplicates an earlier dark zone id")
        else:
            seen.add(zone_id)

        name = zone.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(
                f"{label}.name is required by the simulator and must be a non-empty string"
            )

        if not isinstance(zone.get("observability"), dict):
            errors.append(
                f"{label}.observability is required by the simulator and must be an object"
            )

        start = zone.get("startStationId")
        end = zone.get("endStationId")
        if not _is_int(start) or start not in station_ids:
            errors.append(f"{label}.startStationId must reference an existing station")
            continue
        if not _is_int(end) or end not in station_ids:
            errors.append(f"{label}.endStationId must reference an existing station")
            continue

        if start >= end:
            errors.append(
                f"{label} must span at least {MIN_DARK_CORRIDOR} stations "
                "(startStationId must be strictly less than endStationId)"
            )
        if start == 0:
            errors.append(
                f"{label} may not include the source station (startStationId must be > 0)"
            )
        if end + 1 >= station_count:
            errors.append(
                f"{label} must stay internal: endStationId must be <= {station_count - 2}"
            )
        if previous_end is not None and start <= previous_end + 1:
            errors.append(
                f"{label} must be non-adjacent to the previous zone "
                f"(startStationId must be >= {previous_end + 2}) and listed in ascending order"
            )

        inspections = [
            sid for sid in range(start, end + 1) if archetype_by_id.get(sid) == "INSPECTION"
        ]
        if inspections:
            errors.append(f"{label} may not contain INSPECTION stations: {inspections}")

        span = end - start + 1
        if span > MAX_DARK_CORRIDOR_POLICY:
            warnings.append(
                f"{label} spans {span} stations. This is valid and needs no action -- the "
                f"note exists only because the dashboard's own demo generator caps corridors "
                f"at {MAX_DARK_CORRIDOR_POLICY}. Do not shorten an operator-supplied corridor "
                f"to satisfy it: the trained factory model's contract is tied to the corridor "
                f"extent, and changing it invalidates that model."
            )

        previous_end = end


def validate_factory(data: Any) -> FactoryValidation:
    """Validate a parsed ``factory.json`` payload against the simulator contract."""
    result = FactoryValidation()
    if not isinstance(data, dict):
        result.errors.append("factory.json must contain a JSON object")
        return result
    if "stations" not in data:
        result.errors.append("factory.json must contain a stations array")
        return result

    ordered = _validate_stations(data["stations"], result.errors)
    station_ids = {s["id"] for s in ordered}
    _validate_checkpoints(data.get("checkpoints"), station_ids, result.errors)
    _validate_dark_zones(data.get("darkZones"), ordered, result.errors, result.warnings)
    return result


def is_valid_factory(data: Any) -> bool:
    """Return True when the payload would be accepted by the simulator."""
    return validate_factory(data).ok


def validate_factory_file(path: str | Path) -> FactoryValidation:
    """Read and validate a factory file, reporting IO/JSON problems as errors."""
    path = Path(path)
    if not path.is_file():
        return FactoryValidation(errors=[f"factory.json not found: {path}"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return FactoryValidation(errors=[f"factory.json is not valid JSON: {error}"])
    except OSError as error:
        return FactoryValidation(errors=[f"factory.json could not be read: {error}"])
    return validate_factory(payload)
