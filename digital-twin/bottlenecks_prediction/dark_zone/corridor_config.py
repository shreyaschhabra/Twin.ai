"""
Dark Zone Tracking Engine — Corridor Detection
====================================================
Distinguishes two DIFFERENT dark-zone shapes that can exist in the same
dataset:
  1. SINGLE-STATION dark stations (sensor_coverage=NONE, individually
     tracked via PROCESSING_STARTED/COMPLETED) — handled by the existing
     production pipeline (orchestrator.py / run_pipeline.py).
  2. MULTI-STATION CORRIDORS (DARK_ZONE_ENTERED/EXITED marker events
     spanning several consecutive stations with ZERO individual processing
     events) — handled by multi_station_tracker.py.

A station can appear sensor_coverage=NONE in stations.csv AND still have
ZERO individual events anywhere in station_events.csv, because it's fully
absorbed into a multi-station corridor. Silently treating it as a normal
single-station dark station would waste effort fitting on zero data — this
module makes that distinction explicit rather than letting it fail silently.
"""

from __future__ import annotations

import pandas as pd


def detect_corridors(station_events_csv: str) -> list[dict]:
    """
    Finds DARK_ZONE_ENTERED / DARK_ZONE_EXITED marker pairs and reports,
    per corridor: entry station, exit station, the dark_zone_id tag, and
    which interior stations have ZERO individual processing events
    anywhere in the file (the stations that genuinely need the
    multi-station filter, not the single-station one).
    """
    ev = pd.read_csv(station_events_csv)

    entered = ev[ev.event_type == "DARK_ZONE_ENTERED"]
    exited = ev[ev.event_type == "DARK_ZONE_EXITED"]

    if len(entered) == 0:
        return []

    corridors = []
    # group by dark_zone_id if present, else infer a single corridor from entry/exit stations
    if "dark_zone_id" in ev.columns and entered["dark_zone_id"].notna().any():
        zone_ids = entered["dark_zone_id"].dropna().unique()
    else:
        zone_ids = [None]

    all_stations_with_events = set(
        ev[ev.event_type.isin(["PROCESSING_STARTED", "PROCESSING_COMPLETED"])].station_id
    )

    for zid in zone_ids:
        e_rows = entered[entered.dark_zone_id == zid] if zid is not None else entered
        x_rows = exited[exited.dark_zone_id == zid] if zid is not None else exited
        if len(e_rows) == 0 or len(x_rows) == 0:
            continue

        entry_station = e_rows.station_id.iloc[0]
        exit_station = x_rows.station_id.iloc[0]

        corridors.append({
            "dark_zone_id": zid,
            "entry_station": entry_station,
            "exit_station": exit_station,
            "entry_station_has_own_events": entry_station in all_stations_with_events,
            "exit_station_has_own_events": exit_station in all_stations_with_events,
            "n_entered": len(e_rows),
            "n_exited": len(x_rows),
        })

    return corridors


def validate_corridor_config(
    stations_csv: str,
    entry_station: str,
    exit_station: str,
) -> None:
    """
    Validates a corridor definition BEFORE using it, with specific,
    actionable error messages — not a generic Python exception. Catches
    exactly the failure mode a malformed simulator config can produce
    (e.g. an endStationId that doesn't exist in the factory layout at
    all — a real example seen in a deliberately-invalid test config).
    Raises ValueError with a clear diagnosis; never fails silently or
    with an unhelpful message a person can't act on.
    """
    stations = pd.read_csv(stations_csv)
    all_ids = set(stations.station_id)

    missing = [s for s in (entry_station, exit_station) if s not in all_ids]
    if missing:
        raise ValueError(
            f"Corridor config error: station(s) {missing} do not exist in "
            f"{stations_csv} (factory has {len(all_ids)} stations: "
            f"{sorted(all_ids)[0]}..{sorted(all_ids)[-1]}). This usually means "
            f"the simulator config's startStationId/endStationId is out of range "
            f"for this factory layout — check the source config, not this file."
        )

    ordered = sorted(all_ids)
    i_entry, i_exit = ordered.index(entry_station), ordered.index(exit_station)
    if i_entry >= i_exit:
        raise ValueError(
            f"Corridor config error: entry station {entry_station} (position {i_entry}) "
            f"is not BEFORE exit station {exit_station} (position {i_exit}) in the line "
            f"sequence. A corridor's entry must come before its exit."
        )


def corridor_interior_stations(
    station_events_csv: str,
    stations_csv: str,
    entry_station: str,
    exit_station: str,
) -> list[str]:
    """
    Returns the ordered list of stations strictly between entry_station and
    exit_station (by station_id sort order, matching line sequence) that
    have ZERO individual processing events anywhere — the true blind
    interior. Includes entry_station itself if IT also has no individual
    events (as was the case for S12 in the validated dataset).

    Fully generic — works for ANY entry/exit station pair the data defines,
    not hardcoded to any specific corridor. validate_corridor_config() is
    called first so a malformed config fails with a clear diagnosis rather
    than a confusing internal error.
    """
    validate_corridor_config(stations_csv, entry_station, exit_station)

    stations = pd.read_csv(stations_csv).sort_values("station_id")
    all_ids = list(stations.station_id)
    i_entry, i_exit = all_ids.index(entry_station), all_ids.index(exit_station)
    candidates = all_ids[i_entry:i_exit]  # entry inclusive, exit exclusive

    ev = pd.read_csv(station_events_csv)
    has_events = set(
        ev[ev.event_type.isin(["PROCESSING_STARTED", "PROCESSING_COMPLETED"])].station_id
    )
    return [s for s in candidates if s not in has_events]


def single_station_dark_ids_excluding_corridors(
    stations_csv: str,
    station_events_csv: str,
    sensor_coverage_value: str = "NONE",
) -> set[str]:
    """
    The set of dark stations correctly handled by the EXISTING
    single-station pipeline: sensor_coverage=NONE AND NOT swallowed into a
    multi-station corridor (i.e. they DO have individual processing events
    somewhere in the file). Stations that are sensor_coverage=NONE but
    have zero individual events (like S13 in the validated dataset) are
    excluded here — they need the corridor tracker instead, not a wasted
    zero-sample fit attempt.
    """
    stations = pd.read_csv(stations_csv)
    nominally_dark = set(stations[stations.sensor_coverage == sensor_coverage_value].station_id)

    ev = pd.read_csv(station_events_csv)
    has_events = set(
        ev[ev.event_type.isin(["PROCESSING_STARTED", "PROCESSING_COMPLETED"])].station_id
    )

    trackable = nominally_dark & has_events
    corridor_only = nominally_dark - has_events
    if corridor_only:
        print(f"Note: {corridor_only} are sensor_coverage=NONE but have zero individual "
              f"processing events — swallowed into a multi-station corridor. Excluded from "
              f"single-station tracking; route these to the corridor tracker instead.")
    return trackable
