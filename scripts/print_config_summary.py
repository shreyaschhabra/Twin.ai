"""
Human-inspection tool: load a factory configuration and print a concise
summary. Not used by any simulation/ML/API code — debugging aid only.

Usage:
    python scripts/print_config_summary.py
    python scripts/print_config_summary.py --station-types configs/station_types.yaml --line configs/full_line.yaml
"""

import argparse
from collections import Counter
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.loader import load_factory_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--station-types", default="configs/station_types.yaml")
    parser.add_argument("--line", default="configs/development_line.yaml")
    args = parser.parse_args()

    config = load_factory_config(args.station_types, args.line)

    print(f"=== FactoryConfig: {config.line_name} ===\n")

    print(f"Station count: {len(config.stations)}")
    type_counts = Counter(s.station_type for s in config.stations.values())
    print("Station-type distribution:")
    for type_id, count in sorted(type_counts.items()):
        print(f"  {type_id}: {count}")

    print(f"\nBuffer count: {len(config.buffers)}")

    maturity_counts = Counter(s.sensor_maturity.value for s in config.stations.values())
    total = len(config.stations)
    print("\nSensor maturity distribution:")
    for level in ("rich", "partial", "poor"):
        count = maturity_counts.get(level, 0)
        pct = (count / total * 100) if total else 0
        print(f"  {level}: {count} ({pct:.1f}%)")

    print("\nStations (id | type | operation | maturity | sensors):")
    for station_id, station in sorted(config.stations.items()):
        sensors = ", ".join(station.available_sensors) or "(none)"
        print(
            f"  {station_id} | {station.station_type} | "
            f"{station.specific_operation} | {station.sensor_maturity.value} | {sensors}"
        )

    print("\nVehicle variants and routes:")
    for variant_id, variant in config.vehicle_variants.items():
        print(f"  {variant_id} ({variant.display_name}): {' -> '.join(variant.route)}")
        if variant.processing_time_modifiers:
            mods = ", ".join(
                f"{sid}={mult}x" for sid, mult in variant.processing_time_modifiers.items()
            )
            print(f"      modifiers: {mods}")

    qc_stations = [
        s.station_id
        for s in config.stations.values()
        if s.station_type == "INSPECTION_EOL_TESTING"
    ]
    print(f"\nQC points: {qc_stations}")


if __name__ == "__main__":
    main()
