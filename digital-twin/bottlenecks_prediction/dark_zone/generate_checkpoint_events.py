"""
Dark Zone Tracking Engine — Checkpoint Event Generator
============================================================
Generates checkpoint_events.csv (Layer 3/4 evidence) DIRECTLY from real
per-unit dwell windows in station_events.csv, instead of relying on the
simulator's independent (and currently buggy) checkpoint-timestamp
generation.

Why this approach: we already have ground truth — every unit's actual
entry_ts/exit_ts at every dark-zone station, from real replayed data. A
checkpoint reading is just "a sensor fired at some fraction of THIS unit's
ACTUAL dwell time" — so deriving it directly from that ground truth
guarantees physical consistency by construction (no unit's checkpoint can
ever fall outside its own real window), which is exactly the property the
simulator's independent generator failed to guarantee.

Two distinct noise types are modeled, deliberately differently:

  1. MISSED READS (read_reliability): the checkpoint simply doesn't fire
     for some fraction of units. No event emitted — matches how real
     missed RFID/BLE reads look (absence of a row, not a null flag).

  2. FALSE POSITIVES (false_positive_rate): an EXTRA spurious event for a
     real unit at a real station, at a real timestamp within that unit's
     TRUE window — but claiming an implausible progress position (e.g. a
     "75% complete" checkpoint reading seconds after entry). This is
     intentional: a timestamp-based false positive would just get caught
     by the window-validity check in csv_adapter.py (a blunt "physically
     impossible" filter). A progress-based false positive instead tests
     the INTERESTING part of Layer 3 — orchestrator.py's Mahalanobis
     gating, which is supposed to catch "this claim doesn't match what
     the filter currently believes," not just "this timestamp is
     impossible."
"""

from __future__ import annotations

import numpy as np
import pandas as pd


CHECKPOINT_TYPE_TO_EVENT_TYPE = {
    "RFID": "RFID_CHECKPOINT",
    "BLE": "RFID_CHECKPOINT",
    "RFID_CHECKPOINT": "RFID_CHECKPOINT",
    "POWER_DRAW": "POWER_DRAW",
    "CURRENT": "POWER_DRAW",
}


def generate_checkpoint_events(
    station_events_csv: str,
    units_csv: str,
    station_checkpoints_csv: str,
    output_csv: str = "checkpoint_events_corrected.csv",
    dark_zone_station_ids: set = None,
    jitter_std_ms: float = 3000.0,      # realistic sensor/network jitter, ±~3s
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    ev = pd.read_csv(station_events_csv)
    checkpoints = pd.read_csv(station_checkpoints_csv)

    if dark_zone_station_ids is not None:
        ev = ev[ev["station_id"].isin(dark_zone_station_ids)]
        checkpoints = checkpoints[checkpoints["station_id"].isin(dark_zone_station_ids)]

    starts = ev[ev.event_type == "PROCESSING_STARTED"][
        ["station_id", "unit_id", "timestamp_ms"]
    ].rename(columns={"timestamp_ms": "start_ms"})
    ends = ev[ev.event_type == "PROCESSING_COMPLETED"][
        ["station_id", "unit_id", "timestamp_ms"]
    ].rename(columns={"timestamp_ms": "end_ms"})
    windows = starts.merge(ends, on=["station_id", "unit_id"])  # only COMPLETED transits — no ground truth otherwise
    windows["dwell_ms"] = windows.end_ms - windows.start_ms

    rows = []
    event_counter = 0

    for cp in checkpoints.itertuples(index=False):
        station_windows = windows[windows.station_id == cp.station_id]

        for w in station_windows.itertuples(index=False):
            # --- Real read (subject to missed-read probability) ---
            if rng.random() < cp.read_reliability:
                nominal_ts = w.start_ms + cp.nominal_progress_fraction * w.dwell_ms
                jittered_ts = nominal_ts + rng.normal(0, jitter_std_ms)
                # Clip to the unit's OWN true window — guarantees physical
                # consistency by construction, the entire point of this script.
                ts = float(np.clip(jittered_ts, w.start_ms, w.end_ms))

                event_counter += 1
                rows.append({
                    "event_id": f"CE{event_counter:06d}",
                    "timestamp_ms": round(ts),
                    "event_type": CHECKPOINT_TYPE_TO_EVENT_TYPE.get(cp.checkpoint_type, cp.checkpoint_type),
                    "station_id": cp.station_id,
                    "unit_id": w.unit_id,
                    "checkpoint_id": cp.checkpoint_id,
                })

            # --- False positive (independent extra spurious event) ---
            if rng.random() < cp.false_positive_rate:
                # Real unit, real station, timestamp WITHIN their true
                # window — but at a random point, not tied to this
                # checkpoint's nominal progress fraction. This is what
                # makes it a genuine test of PROGRESS-plausibility gating
                # rather than timestamp-validity gating.
                spurious_ts = rng.uniform(w.start_ms, w.end_ms)

                event_counter += 1
                rows.append({
                    "event_id": f"CE{event_counter:06d}",
                    "timestamp_ms": round(spurious_ts),
                    "event_type": CHECKPOINT_TYPE_TO_EVENT_TYPE.get(cp.checkpoint_type, cp.checkpoint_type),
                    "station_id": cp.station_id,
                    "unit_id": w.unit_id,
                    "checkpoint_id": cp.checkpoint_id,
                })

    columns = [
        "event_id", "timestamp_ms", "event_type",
        "station_id", "unit_id", "checkpoint_id",
    ]
    if rows:
        out = pd.DataFrame(rows, columns=columns).sort_values("timestamp_ms").reset_index(drop=True)
        out["event_id"] = [f"CE{i+1:06d}" for i in range(len(out))]  # renumber in final chronological order
    else:
        # A valid DARK topology may simply contain no configured checkpoints.
        # Keep a schema-correct empty CSV so downstream replay can treat this as
        # "no Layer-3/4 evidence" instead of failing on a missing timestamp column.
        out = pd.DataFrame(columns=columns)
    out.to_csv(output_csv, index=False)

    print(f"Generated {len(out)} checkpoint events -> {output_csv}")
    if not out.empty:
        print(out.groupby(["station_id", "checkpoint_id"]).size())
    else:
        print("No configured checkpoint evidence applies to the selected DARK stations.")
    return out


def main():
    import argparse
    from station_config import dark_zone_station_ids

    parser = argparse.ArgumentParser(description="Generate corrected checkpoint_events.csv from real dwell windows")
    parser.add_argument("--stations", required=True, help="stations.csv path")
    parser.add_argument("--station-events", required=True, help="station_events.csv path")
    parser.add_argument("--units", required=True, help="units.csv path")
    parser.add_argument("--station-checkpoints", required=True, help="station_checkpoints.csv path (checkpoint config)")
    parser.add_argument("--output", default="checkpoint_events_corrected.csv", help="output CSV path")
    parser.add_argument("--jitter-std-ms", type=float, default=3000.0, help="sensor timing jitter, ms")
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    args = parser.parse_args()

    dz = dark_zone_station_ids(args.stations)
    generate_checkpoint_events(
        station_events_csv=args.station_events,
        units_csv=args.units,
        station_checkpoints_csv=args.station_checkpoints,
        output_csv=args.output,
        dark_zone_station_ids=dz,
        jitter_std_ms=args.jitter_std_ms,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
