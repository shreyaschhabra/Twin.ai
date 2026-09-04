"""Generate reproducible simulator inputs from a factory definition."""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any


DEGRADATION_MODES = ("HEALTHY", "GRADUAL", "ACCELERATING", "STEP", "INTERMITTENT", "SEVERE")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def _factory_stations(factory: dict[str, Any]) -> list[dict[str, Any]]:
    stations = factory.get("stations")
    if not isinstance(stations, list) or len(stations) < 3:
        raise ValueError("factory.json must contain at least three stations")
    for station in stations:
        if not isinstance(station.get("id"), int):
            raise ValueError("each factory station requires an integer id")
    return sorted(stations, key=lambda station: station["id"])


def _internal_stations(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [station for station in stations if not station.get("source") and not station.get("sink")]
    if not result:
        raise ValueError("factory.json has no internal stations")
    return result


def _zone_station_ids(factory: dict[str, Any], station_ids: set[int]) -> set[int]:
    result: set[int] = set()
    for zone in factory.get("darkZones", []):
        start, end = zone.get("startStationId"), zone.get("endStationId")
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            raise ValueError("factory darkZones must have valid startStationId/endStationId")
        result.update(station_id for station_id in range(start, end + 1) if station_id in station_ids)
    return result


def _choose_station(
    stations: list[dict[str, Any]], zone_ids: set[int], mode: str, rng: random.Random
) -> dict[str, Any]:
    candidates = stations
    if mode in {"STEP", "INTERMITTENT", "SEVERE"} and zone_ids:
        zone_candidates = [station for station in stations if station["id"] in zone_ids]
        if zone_candidates:
            candidates = zone_candidates
    if mode == "SEVERE":
        candidates = sorted(candidates, key=lambda station: station["meanCycleTimeMs"], reverse=True)
        return candidates[rng.randrange(min(3, len(candidates)))]
    return candidates[rng.randrange(len(candidates))]


def _sensor_effects(station: dict[str, Any], severity: float) -> dict[str, dict[str, float]]:
    coverage = station.get("sensorCoverage", "NONE")
    effects: dict[str, dict[str, float]] = {}
    if coverage in {"PARTIAL", "HIGH"}:
        effects["VIBRATION"] = {"meanShift": round(0.2 + severity * 0.9, 3)}
        effects["TEMPERATURE"] = {"meanShift": round(1.0 + severity * 5.0, 3)}
    if coverage == "HIGH":
        effects["TORQUE"] = {"meanShift": round(1.0 + severity * 7.0, 3)}
    return effects


def _defects_for(
    stations: list[dict[str, Any]], target: dict[str, Any], run_number: int, rng: random.Random
) -> dict[str, Any]:
    severity = rng.uniform(0.25, 0.9)
    target_effect: dict[str, Any] = {
        "stationId": target["id"],
        "cycleTimeMultiplier": round(1.05 + severity * 0.45, 3),
        "extraCV": round(severity * 0.12, 3),
    }
    sensor_effects = _sensor_effects(target, severity)
    if sensor_effects:
        target_effect["sensorEffects"] = sensor_effects
    if target.get("archetype") == "MANUAL":
        target_effect["manualCheckEffects"] = [
            {"measurement": "VISUAL_ALIGNMENT", "failProbability": round(0.08 + severity * 0.55, 3)}
        ]

    effects: list[dict[str, Any]] = [target_effect]
    downstream_inspections = [
        station
        for station in stations
        if station["id"] > target["id"] and station.get("archetype") == "INSPECTION"
    ]
    if downstream_inspections:
        effects.append(
            {
                "stationId": downstream_inspections[0]["id"],
                "inspection": {
                    "detectionProbability": round(0.35 + severity * 0.55, 3),
                    "severity": max(1, round(1 + severity * 4)),
                },
            }
        )
    return {
        "defects": [
            {
                "type": f"GENERATED_DEFECT_{run_number:04d}",
                "introductionStations": [target["id"]],
                "baseProbability": round(0.01 + severity * 0.10, 3),
                "degradationSensitivity": round(severity * 0.45, 3),
                "effects": effects,
            }
        ]
    }


def generate(
    factory_file: Path,
    output_directory: Path,
    count: int,
    seed: int,
    duration_ms: int,
    *,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Create scenario/defect pairs and return their manifest path."""
    if count <= 0:
        raise ValueError("count must be positive")
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    factory = _read_json(factory_file)
    stations = _factory_stations(factory)
    candidates = _internal_stations(stations)
    zone_ids = _zone_station_ids(factory, {station["id"] for station in stations})
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_runs: list[dict[str, Any]] = []

    if progress:
        progress(f"Generating {count} scenario(s) in {output_directory}...")

    for index in range(1, count + 1):
        run_id = f"run_{index:04d}"
        run_seed = seed + index - 1
        rng = random.Random(run_seed)
        mode = DEGRADATION_MODES[(index - 1) % len(DEGRADATION_MODES)]
        target = _choose_station(candidates, zone_ids, mode, rng)
        degradation: list[dict[str, Any]] = []
        if mode != "HEALTHY":
            degradation.append(
                {
                    "stationId": target["id"],
                    "scenario": mode,
                    "initialLevel": round(rng.uniform(0.04, 0.22), 3),
                }
            )
        scenario = {"randomSeed": run_seed, "durationMs": duration_ms, "degradation": degradation}
        scenario_name, defects_name = f"scenario_{index:04d}.json", f"defects_{index:04d}.json"
        _write_json(output_directory / scenario_name, scenario)
        _write_json(output_directory / defects_name, _defects_for(stations, target, index, rng))
        manifest_runs.append(
            {
                "run_id": run_id,
                "seed": run_seed,
                "scenario": scenario_name,
                "defects": defects_name,
                "degradation_mode": mode,
                "primary_station_id": target["id"],
                "primary_station_name": target["name"],
                "in_dark_zone": target["id"] in zone_ids,
            }
        )
        if progress:
            progress(f"Generated scenario {index}/{count}: {run_id} ({mode})")

    manifest = {
        "schema_version": "1.0",
        "factory": str(factory_file.resolve()),
        "generator_seed": seed,
        "duration_ms": duration_ms,
        "dark_zone_ids": [zone["id"] for zone in factory.get("darkZones", [])],
        "runs": manifest_runs,
    }
    manifest_path = output_directory / "manifest.json"
    _write_json(manifest_path, manifest)
    if progress:
        progress(f"Scenario generation complete: {manifest_path}")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate factory-specific simulator scenarios.")
    parser.add_argument("--factory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration-ms", type=int, default=28_800_000)
    args = parser.parse_args()
    try:
        print(generate(args.factory, args.output, args.count, args.seed, args.duration_ms, progress=print))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"scenario generation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
