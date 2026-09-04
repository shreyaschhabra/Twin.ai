"""Factory configuration lifecycle for the dashboard.

"Configuration defines the plant; the intelligence operates on the plant."

This module owns exactly one decision: which ``factory.json`` the dashboard should
treat as authoritative, and what to do when that file is absent. It is independent of
the UI and of the dashboard database.

Rules it enforces:

* An existing ``factory.json`` is loaded and validated -- never rewritten, never
  repaired, never overwritten. :func:`generate_demo_factory` refuses to touch a path
  that already exists unless ``overwrite=True`` is passed explicitly by a caller that
  has already confirmed the intent.
* A missing ``factory.json`` may be filled in with one deterministic demo definition,
  clearly tagged as a demo.
* The dashboard does not maintain its own topology. Whatever lives at the configured
  path is the same file the existing simulator and runtime consume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dashboard.factory.generator import (
    DEMO_NOTE,
    generate_demo_factory as _build_demo_factory,
    is_demo_factory,
)
from dashboard.factory.validator import (
    FactoryValidation,
    is_valid_factory,
    validate_factory,
    validate_factory_file,
)

__all__ = [
    "FactoryState",
    "FactoryStatus",
    "DEMO_NOTE",
    "ensure_factory",
    "factory_state",
    "generate_demo_factory",
    "is_demo_factory",
    "is_valid_factory",
    "load_factory",
    "validate_factory",
    "validate_factory_file",
    "write_factory",
]


class FactoryStatus:
    """Status labels surfaced by the dashboard shell."""

    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class FactoryState:
    """Everything the dashboard needs to describe the configured factory."""

    path: Path
    status: str
    validation: FactoryValidation
    data: dict[str, Any] | None = None

    @property
    def exists(self) -> bool:
        return self.status != FactoryStatus.MISSING

    @property
    def is_demo(self) -> bool:
        return is_demo_factory(self.data)

    @property
    def station_count(self) -> int:
        if not self.data:
            return 0
        stations = self.data.get("stations")
        return len(stations) if isinstance(stations, list) else 0

    @property
    def dark_zone_count(self) -> int:
        if not self.data:
            return 0
        zones = self.data.get("darkZones")
        return len(zones) if isinstance(zones, list) else 0

    def sensor_coverage_counts(self) -> dict[str, int]:
        """Coverage histogram, useful for the Sensor Coverage view later on."""
        counts: dict[str, int] = {}
        if not self.data:
            return counts
        for station in self.data.get("stations", []):
            if isinstance(station, dict):
                key = str(station.get("sensorCoverage", "UNKNOWN"))
                counts[key] = counts.get(key, 0) + 1
        return counts


def load_factory(path: str | Path) -> dict[str, Any]:
    """Load and validate a factory file.

    Raises ``FileNotFoundError`` if absent and ``ValueError`` if the definition would
    be rejected by the simulator.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"factory.json not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    validation = validate_factory(payload)
    if not validation.ok:
        raise ValueError(
            f"factory.json at {path} is not valid for the simulator: "
            + "; ".join(validation.errors)
        )
    return payload


def factory_state(path: str | Path) -> FactoryState:
    """Describe the configured factory without raising.

    This is the read path used by the dashboard shell: a missing, unreadable, or
    invalid file yields a state object rather than an exception.
    """
    path = Path(path)
    validation = validate_factory_file(path)
    if not path.is_file():
        return FactoryState(path=path, status=FactoryStatus.MISSING, validation=validation)
    if not validation.ok:
        return FactoryState(path=path, status=FactoryStatus.INVALID, validation=validation)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:  # pragma: no cover - re-read race
        return FactoryState(
            path=path,
            status=FactoryStatus.INVALID,
            validation=FactoryValidation(errors=[str(error)]),
        )
    return FactoryState(
        path=path, status=FactoryStatus.VALID, validation=validation, data=data
    )


def write_factory(path: str | Path, data: dict[str, Any], *, overwrite: bool = False) -> Path:
    """Write a factory definition, refusing to clobber an existing file by default."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite an existing factory configuration: {path}"
        )
    validation = validate_factory(data)
    if not validation.ok:
        raise ValueError(
            "Refusing to write an invalid factory configuration: "
            + "; ".join(validation.errors)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def generate_demo_factory(
    path: str | Path, *, seed: int = 42, overwrite: bool = False
) -> FactoryState:
    """Generate one demo factory and save it at ``path``.

    Never overwrites an existing file unless ``overwrite=True`` is passed explicitly.
    """
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite an existing factory configuration: {path}"
        )
    data = _build_demo_factory(seed=seed)
    write_factory(path, data, overwrite=overwrite)
    return factory_state(path)


def ensure_factory(path: str | Path, *, seed: int = 42, allow_generate: bool = True) -> FactoryState:
    """Return the state of the configured factory, generating a demo only if missing.

    * File present and valid -> loaded as-is.
    * File present and invalid -> reported as INVALID; the file is left untouched.
    * File absent and ``allow_generate`` -> one demo factory is generated and saved.
    * File absent and not ``allow_generate`` -> reported as MISSING.
    """
    path = Path(path)
    if path.exists():
        return factory_state(path)
    if not allow_generate:
        return factory_state(path)
    return generate_demo_factory(path, seed=seed)
