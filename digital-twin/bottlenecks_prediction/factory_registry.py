"""Small persistent registry for factory definitions and their configuration files."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = PROJECT_ROOT / ".digital_twin" / "factories.json"


def normalize_factory_id(value: str) -> str:
    factory_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip()).strip("-_").lower()
    if not factory_id:
        raise ValueError("Factory id must contain a letter or number")
    if factory_id == "base":
        raise ValueError("'base' is reserved for the protected initial model")
    return factory_id


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "factories": {}}
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data.get("factories"), dict):
        raise ValueError(f"Factory registry is malformed: {path}")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _factory_summary(factory_path: Path) -> dict[str, Any]:
    with factory_path.open(encoding="utf-8") as stream:
        factory = json.load(stream)
    stations = factory.get("stations")
    dark_zones = factory.get("darkZones", [])
    if not isinstance(stations, list) or not stations:
        raise ValueError("factory.json must contain a non-empty stations array")
    if not isinstance(dark_zones, list):
        raise ValueError("factory.json darkZones must be an array when present")
    return {"station_count": len(stations), "dark_zone_count": len(dark_zones)}


def register_factory(
    factory_id: str,
    factory_json: str | Path,
    registry: str | Path = DEFAULT_REGISTRY,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    path = Path(registry).expanduser().resolve()
    factory = Path(factory_json).expanduser().resolve()
    if not factory.is_file():
        raise FileNotFoundError(f"Factory JSON not found: {factory}")
    normalized = normalize_factory_id(factory_id)
    data = _read(path)
    if normalized in data["factories"] and not replace:
        raise FileExistsError(f"Factory is already registered: {normalized}")
    entry = {
        "id": normalized,
        "factory_json": str(factory),
        "registered_at_utc": datetime.now(UTC).isoformat(),
        "configured_stations": data["factories"].get(normalized, {}).get("configured_stations"),
        **_factory_summary(factory),
    }
    data["factories"][normalized] = entry
    _write(path, data)
    return entry


def list_factories(registry: str | Path = DEFAULT_REGISTRY) -> list[dict[str, Any]]:
    data = _read(Path(registry).expanduser().resolve())
    return [data["factories"][factory_id] for factory_id in sorted(data["factories"])]


def get_factory(factory_id: str, registry: str | Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    normalized = normalize_factory_id(factory_id)
    data = _read(Path(registry).expanduser().resolve())
    try:
        return data["factories"][normalized]
    except KeyError as error:
        raise FileNotFoundError(f"Factory is not registered: {normalized}") from error


def set_configured_stations(
    factory_id: str,
    configured_stations: str | Path,
    registry: str | Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    path = Path(registry).expanduser().resolve()
    data = _read(path)
    normalized = normalize_factory_id(factory_id)
    if normalized not in data["factories"]:
        raise FileNotFoundError(f"Factory is not registered: {normalized}")
    configured = Path(configured_stations).expanduser().resolve()
    if not configured.is_file():
        raise FileNotFoundError(f"Configured stations CSV not found: {configured}")
    data["factories"][normalized]["configured_stations"] = str(configured)
    data["factories"][normalized]["configured_at_utc"] = datetime.now(UTC).isoformat()
    _write(path, data)
    return data["factories"][normalized]


def delete_factory(factory_id: str, registry: str | Path = DEFAULT_REGISTRY) -> None:
    path = Path(registry).expanduser().resolve()
    data = _read(path)
    normalized = normalize_factory_id(factory_id)
    if normalized not in data["factories"]:
        raise FileNotFoundError(f"Factory is not registered: {normalized}")
    del data["factories"][normalized]
    _write(path, data)
