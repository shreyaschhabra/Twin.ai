"""
Dark Zone Tracking Engine — Runner
========================================
THIS is the script you actually run.

Usage:
    python3 run_pipeline.py \\
        --stations stations.csv \\
        --station-events station_events.csv \\
        --units units.csv \\
        [--manual-checks manual_checks.csv] \\
        [--checkpoint-events checkpoint_events.csv --station-checkpoints station_checkpoints.csv]

--stations, --station-events, --units are required.
--manual-checks is optional: Layer 5 (Andon/QR) evidence.
--checkpoint-events + --station-checkpoints must be given together (or not
at all): Layer 3 (RFID) + Layer 4 (power-draw) evidence.
"""

from __future__ import annotations

import argparse
import pandas as pd

from dark_zone_tracker import fit_dwell_distribution
from persistence import SQLitePersistence
from orchestrator import DarkZoneOrchestrator
from csv_adapter import inspect_event_types, derive_historical_dwell_csv, load_all_dark_zone_events
from corridor_config import single_station_dark_ids_excluding_corridors


def run(
    stations_csv: str,
    station_events_csv: str,
    units_csv: str,
    manual_checks_csv: str = None,
    checkpoint_events_csv: str = None,
    station_checkpoints_csv: str = None,
    db_path: str = "dark_zone_state.db",
):
    # ---- Step 0: figure out which stations are actually dark zones ----
    # Correctly excludes any station that's nominally sensor_coverage=NONE
    # but has ZERO individual processing events because it's actually
    # swallowed into a multi-station corridor (see corridor_config.py) —
    # feeding such a station to single-station fitting would silently waste
    # effort on zero data instead of routing it to the corridor tracker.
    dz_ids = single_station_dark_ids_excluding_corridors(stations_csv, station_events_csv)
    print(f"Dark-zone stations (sensor_coverage=NONE): {sorted(dz_ids)}\n")

    print("Distinct event_type values in your CSV:")
    inspect_event_types(station_events_csv)
    print()

    # ---- Step 1 (Layer 1): fit dwell-time distributions, dark zones only ----
    hist_df = derive_historical_dwell_csv(
        station_events_csv, units_csv, dark_zone_station_ids=dz_ids,
    )
    dwell_models = fit_dwell_distribution(hist_df, dist_name="gamma")

    for station in dz_ids:
        fallback_key = (station, "__ALL__")
        if fallback_key not in dwell_models:
            candidates = [v for k, v in dwell_models.items() if k[0] == station]
            if candidates:
                dwell_models[fallback_key] = candidates[0]

    if ("__GLOBAL__", "__ALL__") not in dwell_models and len(hist_df) > 0:
        global_hist = hist_df.copy()
        global_hist["station_id"] = "__GLOBAL__"
        global_hist["variant"] = "__ALL__"
        global_fit = fit_dwell_distribution(
            global_hist, dist_name="gamma", min_samples_for_own_fit=1,
        )
        if ("__GLOBAL__", "__ALL__") in global_fit:
            dwell_models[("__GLOBAL__", "__ALL__")] = global_fit[("__GLOBAL__", "__ALL__")]

    print(f"Fitted dwell models for {len({k[0] for k in dwell_models if k[0] != '__GLOBAL__'})} "
          f"dark-zone station(s), {len(dwell_models)} total (station, variant) entries.\n")

    # ---- Step 2: set up persistence + orchestrator ----
    persistence = SQLitePersistence(db_path)
    orch = DarkZoneOrchestrator(
        dwell_models,
        persistence=persistence,
        persist_mode="batched",
        batch_size=100,
        flush_interval_s=2.0,
    )
    print(f"Recovered {len(orch.active)} in-flight vehicle(s) from previous run.\n")

    # ---- Step 3: load FULL combined event stream (Layers 1/2 boundary + 3/4/5), dark zones only ----
    events = load_all_dark_zone_events(
        station_events_csv, units_csv,
        manual_checks_csv=manual_checks_csv,
        checkpoint_events_csv=checkpoint_events_csv,
        station_checkpoints_csv=station_checkpoints_csv,
        dark_zone_station_ids=dz_ids,
    )
    print(f"Loaded {len(events)} dark-zone events. Replaying...\n")

    for i, ev in enumerate(events):
        orch.route_event(ev)
        if i % 500 == 0 and i > 0:
            orch.flush()
            print(f"  ...{i}/{len(events)} events processed "
                  f"({len(orch.active)} vehicles currently in-flight)")

    n_flushed = orch.flush()
    print(f"\nFinal flush: {n_flushed} vehicle state(s) written.")

    # ---- Step 4: summary — broken down by rejection reason, since Layer 3/4
    # gating is EXPECTED to reject some events now (that's the point) ----
    print(f"\nDone. {len(orch.active)} vehicle(s) still in-flight at end of file.")
    print(f"{len(orch.rejected_log)} event(s) rejected/gated total (see orch.rejected_log):")
    if orch.rejected_log:
        reasons = pd.Series([r["reason"] for r in orch.rejected_log]).value_counts()
        for reason, count in reasons.items():
            print(f"  - {reason}: {count}")

    no_dwell_model = [r for r in orch.rejected_log if r["reason"] == "no_dwell_model_available"]
    if no_dwell_model:
        print(f"⚠ {len(no_dwell_model)} vehicle(s) could not be tracked — "
              f"no dwell model even at global fallback. Check historical data volume.")

    andon_fails = [e for e in events if e.event_type.value == "andon_scan"
                   and e.payload.get("result") == "FAIL"]
    if andon_fails:
        print(f"({len(andon_fails)} VISUAL_ALIGNMENT FAIL result(s) seen — carried through in "
              f"event.payload, not currently used as filter evidence, available for QA reporting.)")

    return orch


def main():
    parser = argparse.ArgumentParser(description="Dark Zone Tracking Engine runner")
    parser.add_argument("--stations", required=True, help="stations.csv path")
    parser.add_argument("--station-events", required=True, help="station_events.csv path")
    parser.add_argument("--units", required=True, help="units.csv path")
    parser.add_argument("--manual-checks", default=None, help="manual_checks.csv path (Layer 5, optional)")
    parser.add_argument("--checkpoint-events", default=None,
                         help="checkpoint_events.csv path (Layer 3/4, optional — needs --station-checkpoints too)")
    parser.add_argument("--station-checkpoints", default=None,
                         help="station_checkpoints.csv path (Layer 3/4, optional — needs --checkpoint-events too)")
    parser.add_argument("--db-path", default="dark_zone_state.db", help="SQLite persistence file path")
    args = parser.parse_args()

    if bool(args.checkpoint_events) != bool(args.station_checkpoints):
        parser.error("--checkpoint-events and --station-checkpoints must be given together, or not at all.")

    run(
        stations_csv=args.stations,
        station_events_csv=args.station_events,
        units_csv=args.units,
        manual_checks_csv=args.manual_checks,
        checkpoint_events_csv=args.checkpoint_events,
        station_checkpoints_csv=args.station_checkpoints,
        db_path=args.db_path,
    )


if __name__ == "__main__":
    main()
