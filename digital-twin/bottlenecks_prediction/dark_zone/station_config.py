"""
Dark Zone Tracking Engine — Station Scoping
=================================================
Not every station in the factory is a dark zone. Stations with real sensor
coverage (AUTOMATED/INSPECTION archetypes, sensor_coverage HIGH/PARTIAL)
already have ground-truth telemetry (sensor_readings.csv) — they don't need
probabilistic tracking, and fitting/tracking them wastes compute and can
dilute Layer 1 fits if accidentally pooled with true dark-zone data.

This module reads stations.csv and derives the dark-zone station set from
its data, rather than hardcoding station IDs — so it stays correct if the
simulator's station layout or coverage assignments change between runs.
"""

from __future__ import annotations

import pandas as pd


def load_dark_zone_stations(
    stations_csv: str,
    sensor_coverage_value: str = "NONE",
) -> pd.DataFrame:
    """
    Returns the subset of stations.csv rows that qualify as dark zones:
    sensor_coverage == 'NONE'. This is the primary signal — a station with
    zero sensor coverage is dark by definition, regardless of its declared
    archetype label (archetype is informative, not authoritative — a
    station mislabeled as AUTOMATED with no sensors would still need
    tracking, so we gate on the sensor fact, not the label).
    """
    stations = pd.read_csv(stations_csv)
    dark = stations[stations["sensor_coverage"] == sensor_coverage_value].copy()

    # Sanity note, not an error: flag if any "dark" station isn't labeled
    # MANUAL — worth a human glance, since it's an unusual combination.
    if "archetype" in dark.columns:
        odd = dark[dark["archetype"] != "MANUAL"]
        if len(odd) > 0:
            print(f"Note: {len(odd)} station(s) have sensor_coverage="
                  f"'{sensor_coverage_value}' but archetype != 'MANUAL': "
                  f"{odd['station_id'].tolist()} — tracking them anyway, "
                  f"since coverage (not archetype) is what defines a dark zone.")

    return dark


def dark_zone_station_ids(stations_csv: str, sensor_coverage_value: str = "NONE") -> set[str]:
    """Convenience wrapper — just the station_id set, for filtering event/unit dataframes."""
    return set(load_dark_zone_stations(stations_csv, sensor_coverage_value)["station_id"])
