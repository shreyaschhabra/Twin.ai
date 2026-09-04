"""
Dark Zone Tracking Engine — CSV Schema Adapter
====================================================
Maps your actual simulator output into DarkZoneEvent objects:

    station_events.csv : unit_id, station_id, timestamp_ms, event_type
    units.csv           : unit_id, vehicle_model

Two things you MUST configure before this works correctly on real data:

  1. EVENT_TYPE_MAP — maps your raw `event_type` strings to our EventType
     enum. Run `inspect_event_types()` on your CSV first to see the actual
     distinct values, then fill this in.

  2. CHECKPOINT_PROGRESS_MAP — maps (station_id, event_type) -> nominal
     progress fraction (0-1). This is NOT in your CSV and can't be inferred
     — it's "where physically is this checkpoint in the station's work
     sequence," which only you know from the station layout. Placeholder
     values are provided; replace with real ones.
"""

from __future__ import annotations

import pandas as pd
from typing import Optional

from orchestrator import DarkZoneEvent, EventType


# =====================================================================
# CONFIG — edit these two maps for your real station layout
# =====================================================================

# Raw event_type string (from your CSV) -> our EventType enum.
# INSPECT YOUR CSV FIRST (see inspect_event_types below) and adjust keys
# to match exactly what's in the file — these are placeholder guesses.
# Raw event_type string (from your CSV) -> our EventType enum.
# Set a value to None for event types you recognize but deliberately don't
# use (e.g. a queue-arrival event that isn't a dwell-time boundary) — these
# are skipped silently. Omitting a key entirely means "unrecognized," which
# triggers a loud ⚠ warning instead, since that's usually a real mismatch.
EVENT_TYPE_MAP: dict[str, Optional[EventType]] = {
    "UNIT_ARRIVED": None,                          # queue arrival, not a dwell boundary — intentional skip
    "PROCESSING_STARTED": EventType.STATION_ENTRY,  # work begins = dwell clock starts
    "PROCESSING_COMPLETED": EventType.STATION_EXIT, # work ends = dwell clock stops
    # If/when your simulator adds real boundary sensors, extend here, e.g.:
    # "RFID_CHECKPOINT": EventType.RFID_CHECKPOINT,
    # "TORQUE_SPIKE": EventType.POWER_DRAW,
    # "ANDON_SCAN": EventType.ANDON_SCAN,
}

# (station_id, raw_event_type) -> nominal progress fraction.
# EMPTY for now: your current schema has no RFID/power-draw/Andon events, so
# there's nothing to map yet. The filter runs on Layers 1+2 only (predict
# between PROCESSING_STARTED and PROCESSING_COMPLETED, no mid-station
# corrections) — this is a legitimate mode, just without Layer 3-5 benefits.
# Add entries here once your simulator produces real checkpoint events, e.g.:
# ("__DEFAULT__", "RFID_CHECKPOINT"): 0.5,
CHECKPOINT_PROGRESS_MAP: dict[tuple[str, str], float] = {}


# =====================================================================
# INSPECTION HELPER — run this FIRST on your real file
# =====================================================================

def inspect_event_types(station_events_csv: str) -> pd.DataFrame:
    """
    Prints the distinct event_type values in your CSV with counts, so you
    can correctly fill in EVENT_TYPE_MAP and CHECKPOINT_PROGRESS_MAP
    instead of guessing. Run this before your first real replay.

    Distinguishes:
      - genuinely unrecognized values (not in EVENT_TYPE_MAP at all) -> loud warning
      - recognized-but-intentionally-skipped values (mapped to None) -> quiet note
    """
    df = pd.read_csv(station_events_csv)
    counts = df["event_type"].value_counts().reset_index()
    counts.columns = ["event_type", "count"]
    print(counts.to_string(index=False))

    seen = set(df["event_type"].unique())
    unrecognized = seen - set(EVENT_TYPE_MAP.keys())
    intentionally_skipped = {t for t in seen if EVENT_TYPE_MAP.get(t) is None} - unrecognized

    if intentionally_skipped:
        print(f"\n(Intentionally skipped, not an error: {intentionally_skipped})")
    if unrecognized:
        print(f"\n⚠ UNRECOGNIZED event_type values (add these to EVENT_TYPE_MAP): {unrecognized}")
    return counts


def derive_historical_dwell_csv(
    station_events_csv: str,
    units_csv: str,
    output_csv: str = "historical_dwell.csv",
    entry_event_type: str = "PROCESSING_STARTED",
    exit_event_type: str = "PROCESSING_COMPLETED",
    dark_zone_station_ids: Optional[set] = None,
) -> pd.DataFrame:
    """
    Builds the historical_dwell.csv that Layer 1 needs (station_id, variant,
    entry_ts, exit_ts) DIRECTLY from your existing station_events.csv +
    units.csv — no separate data source required.

    Pairs each vehicle's `entry_event_type` and `exit_event_type` rows per
    station. Vehicles missing either half of the pair (e.g. still mid-station
    in a truncated simulation run) are dropped with a warning, since a Gamma
    fit needs COMPLETE dwell times, not in-progress ones.

    NOTE: if you're using this to fit the SAME data you're about to replay
    through the filter, that's fine for a first pass/demo, but it's
    circular for real validation — the filter will "predict" data it was
    trained on. For a genuine backtest, fit on an earlier historical batch
    and replay a later, separate batch.
    """
    events_df = pd.read_csv(station_events_csv)
    units_df = pd.read_csv(units_csv)
    variant_lookup = dict(zip(units_df["unit_id"], units_df["vehicle_model"]))

    if dark_zone_station_ids is not None:
        events_df = events_df[events_df["station_id"].isin(dark_zone_station_ids)]

    entries = events_df[events_df["event_type"] == entry_event_type]
    exits = events_df[events_df["event_type"] == exit_event_type]

    merged = entries.merge(
        exits, on=["unit_id", "station_id"], suffixes=("_entry", "_exit"),
    )

    dropped = len(entries) - len(merged)
    if dropped > 0:
        print(f"⚠ Dropped {dropped} unpaired entry event(s) — vehicle likely "
              f"still in-station or missing its exit event in this file.")

    out = pd.DataFrame({
        "station_id": merged["station_id"],
        "variant": merged["unit_id"].map(variant_lookup),
        "entry_ts": pd.to_datetime(merged["timestamp_ms_entry"], unit="ms"),
        "exit_ts": pd.to_datetime(merged["timestamp_ms_exit"], unit="ms"),
    })

    missing_variant = out["variant"].isna().sum()
    if missing_variant > 0:
        print(f"⚠ {missing_variant} row(s) have no variant match in units.csv — "
              f"these will be excluded from station+variant-specific fits.")
    out = out.dropna(subset=["variant"])

    out.to_csv(output_csv, index=False)
    print(f"Wrote {len(out)} historical dwell rows to {output_csv}")
    return out


# =====================================================================
# ADAPTER — CSV rows -> DarkZoneEvent stream
# =====================================================================

def load_events_from_csv(
    station_events_csv: str,
    units_csv: str,
) -> list[DarkZoneEvent]:
    """
    Reads both CSVs, joins unit_id -> vehicle_model (as `variant`), and
    returns a chronologically sorted list of DarkZoneEvent ready to feed
    into DarkZoneOrchestrator.route_event().
    """
    events_df = pd.read_csv(station_events_csv)
    units_df = pd.read_csv(units_csv)

    missing = set(events_df["unit_id"]) - set(units_df["unit_id"])
    if missing:
        print(f"⚠ {len(missing)} unit_id(s) in station_events.csv have no "
              f"matching row in units.csv (variant will be None): "
              f"{list(missing)[:5]}{'...' if len(missing) > 5 else ''}")

    variant_lookup = dict(zip(units_df["unit_id"], units_df["vehicle_model"]))

    events_df = events_df.sort_values("timestamp_ms").reset_index(drop=True)

    events: list[DarkZoneEvent] = []
    unrecognized_types_seen: set[str] = set()
    intentionally_skipped_count = 0

    for row in events_df.itertuples(index=False):
        raw_type = row.event_type

        if raw_type not in EVENT_TYPE_MAP:
            unrecognized_types_seen.add(raw_type)
            continue  # genuinely unknown — skip and warn

        mapped_type = EVENT_TYPE_MAP[raw_type]
        if mapped_type is None:
            intentionally_skipped_count += 1
            continue  # recognized, deliberately not used (e.g. UNIT_ARRIVED) — skip quietly

        vehicle_id = row.unit_id
        station_id = row.station_id
        ts_s = row.timestamp_ms / 1000.0  # ms -> s, matches DarkZoneEvent.ts contract
        variant = variant_lookup.get(vehicle_id)

        checkpoint_progress: Optional[float] = None
        if mapped_type in (EventType.RFID_CHECKPOINT, EventType.POWER_DRAW, EventType.ANDON_SCAN):
            checkpoint_progress = CHECKPOINT_PROGRESS_MAP.get(
                (station_id, raw_type),
                CHECKPOINT_PROGRESS_MAP.get(("__DEFAULT__", raw_type)),
            )
            if checkpoint_progress is None:
                unrecognized_types_seen.add(f"{raw_type} (no progress mapping for station {station_id})")
                continue

        events.append(DarkZoneEvent(
            event_type=mapped_type,
            vehicle_id=vehicle_id,
            station_id=station_id,
            ts=ts_s,
            variant=variant,
            checkpoint_progress=checkpoint_progress,
        ))

    if intentionally_skipped_count:
        print(f"(Skipped {intentionally_skipped_count} intentionally-unused event(s), e.g. queue arrivals.)")
    if unrecognized_types_seen:
        print(f"⚠ Skipped events with UNRECOGNIZED types/configs: {unrecognized_types_seen}")

    return events


def load_manual_checks_as_andon_events(
    manual_checks_csv: str,
    units_csv: str,
    dark_zone_station_ids: Optional[set] = None,
    station_events_csv: Optional[str] = None,
) -> list[DarkZoneEvent]:
    """
    Layer 5 adapter: manual_checks.csv (station_id, unit_id, timestamp_ms,
    check_type, result) -> ANDON_SCAN events.  ``unit_id`` is required:
    ANDON evidence is vehicle-specific and cannot be routed without it.

    Older simulator runs may contain anonymous manual checks.  They cannot be
    turned into a vehicle-specific event without inventing an identity, so
    they are excluded with a precise source diagnostic.  New simulator output
    provides ``unit_id`` directly.

    Data-verified behavior (checked against real run_001 output): the
    VISUAL_ALIGNMENT check fires exactly at PROCESSING_COMPLETED for every
    recorded check (progress fraction 1.0, std 0.0 across 2,257 samples) —
    so checkpoint_progress=1.0 is not a guess here, it's confirmed from the
    data. If a future simulator run adds mid-cycle manual checks, this
    assumption will need revisiting — the ANDON_SCAN likelihood in
    orchestrator.py already handles non-1.0 claims correctly via its
    plausibility gate, so no downstream change would be needed, just this
    constant.

    The check's PASS/FAIL result doesn't detectably shift dwell time in the
    data (FAIL mean 59.3s vs PASS mean 59.9s) but is carried through in
    `payload` anyway — useful for downstream QA/defect-rate reporting even
    though it isn't currently used as filter evidence.
    """
    mc_df = pd.read_csv(manual_checks_csv)
    units_df = pd.read_csv(units_csv)
    variant_lookup = dict(zip(units_df["unit_id"], units_df["vehicle_model"]))

    if dark_zone_station_ids is not None:
        before = len(mc_df)
        mc_df = mc_df[mc_df["station_id"].isin(dark_zone_station_ids)]
        dropped = before - len(mc_df)
        if dropped > 0:
            print(f"(Filtered out {dropped} manual_checks row(s) at non-dark-zone stations.)")

    events: list[DarkZoneEvent] = []
    rejected_anonymous_rows = 0
    for source_index, row in mc_df.iterrows():
        unit_id = row["unit_id"]
        if pd.isna(unit_id) or not str(unit_id).strip():
            rejected_anonymous_rows += 1
            if rejected_anonymous_rows == 1:
                available_fields = sorted(str(field) for field in row.index)
                print(
                    "Skipping unrouteable replay evidence at creation: "
                    f"source_file={manual_checks_csv!r}, row/index={source_index!r}, "
                    "event_type='ANDON_SCAN', "
                    f"station={row.get('station_id')!r}, available_fields={available_fields!r}, "
                    f"unit_id={row.get('unit_id')!r}"
                )
            continue
        events.append(DarkZoneEvent(
            event_type=EventType.ANDON_SCAN,
            vehicle_id=str(unit_id),
            station_id=row["station_id"],
            ts=row["timestamp_ms"] / 1000.0,
            variant=variant_lookup.get(unit_id),
            checkpoint_progress=1.0,
            payload={"check_type": row["check_type"], "result": row["result"]},
        ))
    if rejected_anonymous_rows:
        print(
            f"(Skipped {rejected_anonymous_rows} manual_checks row(s) without unit_id; "
            "they cannot be routed as vehicle-specific ANDON evidence.)"
        )
    return events


def load_all_dark_zone_events(
    station_events_csv: str,
    units_csv: str,
    manual_checks_csv: Optional[str] = None,
    checkpoint_events_csv: Optional[str] = None,
    station_checkpoints_csv: Optional[str] = None,
    dark_zone_station_ids: Optional[set] = None,
    validate_checkpoint_windows: bool = True,
) -> list[DarkZoneEvent]:
    """
    Combines entry/exit events (station_events.csv), Layer 5 events
    (manual_checks.csv), and Layer 3/4 events (checkpoint_events.csv, needs
    station_checkpoints.csv for progress-fraction lookup) into a single
    chronologically sorted stream ready for orchestrator.route_event().
    This is the function run_pipeline.py should call — it's the one entry
    point that assembles the full event stream for the dark-zone stations.
    """
    events = load_events_from_csv(station_events_csv, units_csv)

    if dark_zone_station_ids is not None:
        before = len(events)
        events = [e for e in events if e.station_id in dark_zone_station_ids]
        dropped = before - len(events)
        if dropped > 0:
            print(f"(Filtered out {dropped} station_events.csv event(s) at non-dark-zone stations "
                  f"— those stations have real sensor coverage and are out of scope here.)")

    if manual_checks_csv:
        andon_events = load_manual_checks_as_andon_events(
            manual_checks_csv, units_csv, dark_zone_station_ids
        )
        events.extend(andon_events)

    if checkpoint_events_csv:
        if not station_checkpoints_csv:
            raise ValueError(
                "checkpoint_events_csv was given but station_checkpoints_csv was not — "
                "the progress-fraction lookup needs both files together."
            )
        rfid_power_events = load_checkpoint_events(
            checkpoint_events_csv, station_checkpoints_csv, units_csv, dark_zone_station_ids,
            station_events_csv=station_events_csv if validate_checkpoint_windows else None,
        )
        events.extend(rfid_power_events)

    # Sort by timestamp, with a tie-break priority: when two events share the
    # exact same ts (common here — the VISUAL_ALIGNMENT check fires at the
    # same instant as PROCESSING_COMPLETED), evidence/checkpoint events MUST
    # be applied before STATION_EXIT, or the vehicle gets torn down first and
    # the evidence is silently rejected as "unknown vehicle." Verified this
    # was happening 1:1 with the real data before this fix.
    _tie_priority = {
        EventType.STATION_ENTRY: 0,
        EventType.RFID_CHECKPOINT: 1,
        EventType.POWER_DRAW: 1,
        EventType.ANDON_SCAN: 1,
        EventType.TICK: 1,
        EventType.STATION_EXIT: 2,
    }
    events.sort(key=lambda e: (e.ts, _tie_priority.get(e.event_type, 1)))
    return events


def load_checkpoint_progress_map(station_checkpoints_csv: str) -> dict[tuple[str, str], float]:
    """
    Reads station_checkpoints.csv (station_id, checkpoint_id, checkpoint_type,
    nominal_progress_fraction, read_reliability, false_positive_rate) and
    returns a lookup: (station_id, checkpoint_id) -> nominal_progress_fraction.

    read_reliability / false_positive_rate aren't used here — they describe
    the DATA's generation process (how the simulator decided whether to emit
    an event), not something the tracking pipeline needs to consume. The
    pipeline finds out about unreliability/false-positives empirically, from
    which events actually show up and get gated — that's the whole point of
    the Layer 3 gating logic already in orchestrator.py.
    """
    df = pd.read_csv(station_checkpoints_csv)
    return {
        (row.station_id, row.checkpoint_id): row.nominal_progress_fraction
        for row in df.itertuples(index=False)
    }


def load_checkpoint_events(
    checkpoint_events_csv: str,
    station_checkpoints_csv: str,
    units_csv: str,
    dark_zone_station_ids: Optional[set] = None,
    station_events_csv: Optional[str] = None,
    drop_out_of_window: bool = True,
) -> list[DarkZoneEvent]:
    """
    Layer 3 (RFID_CHECKPOINT) and Layer 4 (POWER_DRAW) adapter.
    checkpoint_events.csv columns: event_id, timestamp_ms, event_type,
    station_id, unit_id, checkpoint_id.

    If station_events_csv is provided, each checkpoint's timestamp is
    validated against that unit's ACTUAL entry/exit window at that station
    (from PROCESSING_STARTED/PROCESSING_COMPLETED). Checkpoints landing
    outside [entry, exit] are a data-generation problem, not sensor noise —
    a real RFID/CT-clamp reading physically cannot occur before a vehicle
    arrives or after it's already left. Without this check, such events
    would silently become "unknown_vehicle" rejections in the orchestrator
    (the vehicle's tracker is already torn down by the time the mistimed
    event arrives), which looks identical to a genuinely late/missed read
    and hides a real upstream bug behind a normal-looking noise category.
    """
    ce_df = pd.read_csv(checkpoint_events_csv)
    ce_df["_source_index"] = ce_df.index
    units_df = pd.read_csv(units_csv)
    variant_lookup = dict(zip(units_df["unit_id"], units_df["vehicle_model"]))
    progress_map = load_checkpoint_progress_map(station_checkpoints_csv)

    if dark_zone_station_ids is not None:
        before = len(ce_df)
        ce_df = ce_df[ce_df["station_id"].isin(dark_zone_station_ids)]
        dropped = before - len(ce_df)
        if dropped > 0:
            print(f"(Filtered out {dropped} checkpoint_events.csv row(s) at non-dark-zone stations.)")

    if station_events_csv:
        sev = pd.read_csv(station_events_csv)
        starts = sev[sev["event_type"] == "PROCESSING_STARTED"][
            ["station_id", "unit_id", "timestamp_ms"]
        ].rename(columns={"timestamp_ms": "_start_ms"})
        ends = sev[sev["event_type"] == "PROCESSING_COMPLETED"][
            ["station_id", "unit_id", "timestamp_ms"]
        ].rename(columns={"timestamp_ms": "_end_ms"})
        windows = starts.merge(ends, on=["station_id", "unit_id"])

        before = len(ce_df)
        ce_df = ce_df.merge(windows, on=["station_id", "unit_id"], how="left")
        matched = ce_df["_start_ms"].notna() & ce_df["_end_ms"].notna()
        out_mask = matched & (
            (ce_df["timestamp_ms"] < ce_df["_start_ms"])
            | (ce_df["timestamp_ms"] > ce_df["_end_ms"])
        )
        n_out = int(out_mask.sum())

        if n_out > 0:
            pct = 100 * n_out / max(int(matched.sum()), 1)
            print(f"⚠ DATA QUALITY ISSUE: {n_out} checkpoint event(s) ({pct:.0f}% of matched rows) "
                  f"fall OUTSIDE their unit's directly observed station window. "
                  f"{'Dropping only those matched-invalid events.' if drop_out_of_window else 'KEEPING them anyway.'}")

        if drop_out_of_window:
            # IMPORTANT: unmatched evidence is not automatically invalid. Simulator
            # schema v2.1 intentionally suppresses internal DARK processing rows,
            # so a legitimate RFID/POWER event may have no direct station window.
            ce_df = ce_df[~out_mask]

    raw_to_event_type = {
        "RFID_CHECKPOINT": EventType.RFID_CHECKPOINT,
        "RFID": EventType.RFID_CHECKPOINT,       # accept shorthand seen in station_checkpoints.csv's checkpoint_type
        "BLE": EventType.RFID_CHECKPOINT,
        "POWER_DRAW": EventType.POWER_DRAW,
    }

    events: list[DarkZoneEvent] = []
    unmapped_progress = 0
    unmapped_event_type: set = set()
    for _, row in ce_df.iterrows():
        mapped_type = raw_to_event_type.get(row["event_type"])
        if mapped_type is None:
            unmapped_event_type.add(row["event_type"])
            continue  # future checkpoint types not yet supported here

        progress = progress_map.get((row["station_id"], row["checkpoint_id"]))
        if progress is None:
            unmapped_progress += 1
            continue  # checkpoint_id not found in station_checkpoints.csv — skip, don't guess

        unit_id = row["unit_id"]
        anonymous = pd.isna(unit_id) or not str(unit_id).strip()
        if anonymous and mapped_type != EventType.POWER_DRAW:
            available_fields = sorted(
                str(field) for field in row.index if field != "_source_index"
            )
            raise ValueError(
                "Identity checkpoint evidence is missing unit_id: "
                f"source_file={checkpoint_events_csv!r}, row/index={row['_source_index']!r}, "
                f"event_type={row['event_type']!r}, station={row['station_id']!r}, "
                f"available_fields={available_fields!r}"
            )

        vehicle_id = "" if anonymous else str(unit_id)
        events.append(DarkZoneEvent(
            event_type=mapped_type,
            vehicle_id=vehicle_id,
            station_id=row["station_id"],
            ts=row["timestamp_ms"] / 1000.0,
            variant=None if anonymous else variant_lookup.get(str(unit_id)),
            checkpoint_progress=progress,
            payload={"checkpoint_id": row["checkpoint_id"]},
        ))

    if unmapped_progress:
        print(f"⚠ {unmapped_progress} checkpoint event(s) had no matching row in "
              f"station_checkpoints.csv — skipped.")
    if unmapped_event_type:
        print(f"⚠ {len(ce_df) - len(events) - unmapped_progress} checkpoint event(s) had "
              f"UNRECOGNIZED event_type value(s) {unmapped_event_type} — skipped. "
              f"Add them to raw_to_event_type if these are legitimate.")

    return events
