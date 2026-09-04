# configure_stations.py

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def get_dark_stations(available_station_ids: set[str]) -> set[str]:
    """
    Ask the user which stations should operate as DARK stations.

    DARK station  -> sensor_coverage = "NONE"
    LIGHT station -> sensor_coverage = "NORMAL"
    """

    print("\n" + "=" * 60)
    print("DIGITAL TWIN - DARK ZONE CONFIGURATION")
    print("=" * 60)

    print("\nAvailable stations:")
    print(", ".join(sorted(available_station_ids)))

    print(
        "\nEnter DARK stations separated by commas.\n"
        "Example: S04,S05,S09\n"
        "Press Enter if there are no dark stations."
    )

    dark_input = input("\nDark stations: ").strip()

    # No dark stations selected
    if not dark_input:
        return set()

    dark_stations = {
        station.strip()
        for station in dark_input.split(",")
        if station.strip()
    }

    # Validate station IDs
    invalid_stations = dark_stations - available_station_ids

    if invalid_stations:
        raise ValueError(
            "\nInvalid DARK station(s): "
            + ", ".join(sorted(invalid_stations))
            + "\nAvailable stations are: "
            + ", ".join(sorted(available_station_ids))
        )

    return dark_stations


def configure_sensor_coverage(
    stations: pd.DataFrame,
    dark_stations: set[str],
) -> pd.DataFrame:
    """
    Add/update sensor_coverage for every station.

    DARK  -> "NONE"
    LIGHT -> NORMAL
    """

    configured = stations.copy()

    configured["station_id"] = configured["station_id"].astype(str)

    configured["sensor_coverage"] = configured["station_id"].apply(
        lambda station_id: (
            "NONE"
            if station_id in dark_stations
            else "NORMAL"
        )
    )

    return configured



def dark_stations_from_dz(
    stations: pd.DataFrame,
    dz_csv: str | Path,
) -> set[str]:
    """Resolve simulator DARK-zone membership from ``dz.csv``.

    ``sensor_coverage`` describes telemetry richness and is deliberately NOT a
    zone-membership flag in simulator schema v2.1.  ``dz.csv`` is the stable
    topology contract.  Ranges are expanded by station row order so this also
    works for non-numeric station IDs.
    """
    dz_path = Path(dz_csv).expanduser().resolve()
    if not dz_path.is_file():
        raise FileNotFoundError(f"dz.csv not found: {dz_path}")
    if "station_id" not in stations.columns:
        raise ValueError("stations.csv must contain station_id")

    order = stations["station_id"].astype(str).str.strip().tolist()
    pos = {sid: i for i, sid in enumerate(order)}
    if len(pos) != len(order):
        raise ValueError("Duplicate station IDs are not allowed")

    dz = pd.read_csv(dz_path)
    required = {"start_station_id", "end_station_id"}
    missing = required - set(dz.columns)
    if missing:
        raise ValueError(f"dz.csv missing required columns: {sorted(missing)}")

    dark: set[str] = set()
    for row in dz.itertuples(index=False):
        start = str(row.start_station_id).strip()
        end = str(row.end_station_id).strip()
        if start not in pos or end not in pos:
            raise ValueError(
                f"DARK zone range {start}..{end} references station(s) absent from stations.csv"
            )
        a, b = pos[start], pos[end]
        if a > b:
            raise ValueError(f"DARK zone start {start} occurs after end {end}")
        dark.update(order[a : b + 1])
    return dark


def configure_from_dz(
    stations_csv: str | Path,
    dz_csv: str | Path,
) -> tuple[pd.DataFrame, set[str]]:
    """Build the bottleneck runtime topology from simulator run artifacts."""
    stations_path = Path(stations_csv).expanduser().resolve()
    if not stations_path.is_file():
        raise FileNotFoundError(f"stations.csv not found: {stations_path}")
    stations = pd.read_csv(stations_path)
    dark = dark_stations_from_dz(stations, dz_csv)
    return configure_sensor_coverage(stations, dark), dark


RUNTIME_CONTRACT_COLUMNS = (
    "station_id",
    "archetype",
    "base_cycle_time_ms",
    "cycle_time_std_ms",
    "buffer_capacity",
    "sensor_coverage",
)


def validate_runtime_topology_match(
    expected_configured_csv: str | Path,
    run_stations_csv: str | Path,
    run_dz_csv: str | Path,
) -> tuple[pd.DataFrame, set[str]]:
    """Verify a simulator run matches a factory model's immutable runtime contract.

    A factory artifact is only valid for the station order/static configuration and
    DARK topology it was trained/configured for.  ``dz.csv`` is authoritative for
    the run's DARK membership; raw ``sensor_coverage`` is not.  This guard prevents
    silently routing a run through a model artifact from another factory.
    """
    expected_path = Path(expected_configured_csv).expanduser().resolve()
    if not expected_path.is_file():
        raise FileNotFoundError(f"Configured station contract not found: {expected_path}")

    current, dark = configure_from_dz(run_stations_csv, run_dz_csv)
    expected = pd.read_csv(expected_path)

    missing_expected = [c for c in RUNTIME_CONTRACT_COLUMNS if c not in expected.columns]
    missing_current = [c for c in RUNTIME_CONTRACT_COLUMNS if c not in current.columns]
    if missing_expected or missing_current:
        raise ValueError(
            "Factory/runtime station contract is incomplete: "
            f"expected missing={missing_expected}, current missing={missing_current}"
        )

    expected = expected.loc[:, RUNTIME_CONTRACT_COLUMNS].copy()
    current_cmp = current.loc[:, RUNTIME_CONTRACT_COLUMNS].copy()
    expected["station_id"] = expected["station_id"].astype(str).str.strip()
    current_cmp["station_id"] = current_cmp["station_id"].astype(str).str.strip()

    expected_order = expected["station_id"].tolist()
    current_order = current_cmp["station_id"].tolist()
    if expected_order != current_order:
        raise ValueError(
            "Simulator station order does not match the selected factory model. "
            f"Expected {expected_order}, got {current_order}."
        )

    numeric = {"base_cycle_time_ms", "cycle_time_std_ms", "buffer_capacity"}
    mismatches: list[str] = []
    for col in RUNTIME_CONTRACT_COLUMNS:
        if col == "station_id":
            continue
        if col in numeric:
            lhs = pd.to_numeric(expected[col], errors="coerce")
            rhs = pd.to_numeric(current_cmp[col], errors="coerce")
            unequal = ~(lhs.fillna(float("inf")).eq(rhs.fillna(float("inf"))))
        else:
            lhs = expected[col].astype(str).str.strip().str.upper()
            rhs = current_cmp[col].astype(str).str.strip().str.upper()
            unequal = ~lhs.eq(rhs)
        if unequal.any():
            for idx in unequal[unequal].index[:5]:
                mismatches.append(
                    f"{expected.loc[idx, 'station_id']}:{col} "
                    f"expected={expected.loc[idx, col]!r} current={current_cmp.loc[idx, col]!r}"
                )
    if mismatches:
        raise ValueError(
            "Simulator run does not match the selected factory model contract: "
            + "; ".join(mismatches)
        )
    return current, dark

def print_configuration(
    stations: pd.DataFrame,
    dark_stations: set[str],
) -> None:

    print("\n" + "=" * 60)
    print("STATION CONFIGURATION")
    print("=" * 60)

    for row in stations.itertuples(index=False):

        station_id = str(row.station_id)

        if station_id in dark_stations:
            zone = "DARK"
            coverage = "NONE"
        else:
            zone = "LIGHT"
            coverage = "NORMAL"

        print(
            f"{station_id:<10} "
            f"Zone: {zone:<7} "
            f"Sensor coverage: {coverage}"
        )

    print("=" * 60)

    print(f"\nTotal stations : {len(stations)}")
    print(f"Dark stations  : {len(dark_stations)}")
    print(f"Light stations : {len(stations) - len(dark_stations)}")

    if dark_stations:
        print(
            "Dark station IDs:",
            ", ".join(sorted(dark_stations))
        )
    else:
        print("Dark station IDs: NONE")


def load_and_configure_stations(
    stations_csv: str | Path,
) -> tuple[pd.DataFrame, set[str]]:
    """
    Main Step-1 function.

    Returns:
        configured_stations
        dark_stations
    """

    stations_csv = Path(stations_csv)

    if not stations_csv.is_file():
        raise FileNotFoundError(
            f"stations.csv not found: {stations_csv}"
        )

    stations = pd.read_csv(stations_csv)

    if "station_id" not in stations.columns:
        raise ValueError(
            "stations.csv must contain a 'station_id' column."
        )

    # Normalize station IDs
    stations["station_id"] = (
        stations["station_id"]
        .astype(str)
        .str.strip()
    )

    # Check duplicate IDs
    duplicates = stations[
        stations["station_id"].duplicated()
    ]["station_id"].tolist()

    if duplicates:
        raise ValueError(
            f"Duplicate station IDs found: {duplicates}"
        )

    available_station_ids = set(
        stations["station_id"]
    )

    # Ask user which stations are dark
    dark_stations = get_dark_stations(
        available_station_ids
    )

    # Configure sensor coverage
    configured_stations = configure_sensor_coverage(
        stations,
        dark_stations,
    )

    print_configuration(
        configured_stations,
        dark_stations,
    )

    return configured_stations, dark_stations


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Step 1 of Digital Twin pipeline: "
            "configure Light and Dark stations."
        )
    )

    parser.add_argument(
        "--stations",
        required=True,
        help="Path to the original stations.csv",
    )

    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Optional path to save the configured station file. "
            "Example: configured_stations.csv"
        ),
    )

    args = parser.parse_args()

    configured_stations, dark_stations = (
        load_and_configure_stations(args.stations)
    )

    # Optional output CSV
    if args.output:

        output_path = Path(args.output)

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        configured_stations.to_csv(
            output_path,
            index=False,
        )

        print(
            f"\nConfigured station file written to: "
            f"{output_path}"
        )

    print("\nStep 1 complete.")

    print(
        "\nThe factory can now start with this configuration."
    )


if __name__ == "__main__":
    main()