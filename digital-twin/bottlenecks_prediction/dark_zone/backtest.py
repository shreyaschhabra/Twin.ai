"""
Dark Zone Tracking Engine — Accuracy Backtest
===================================================
Everything validated so far (crash recovery, event routing, gating,
0-rejection full runs) proves the pipeline RUNS CORRECTLY. Nothing has yet
proven the filter's predictions are ACCURATE — that progress_mean/eta_seconds
are actually close to what really happened.

This script answers that. For every real completed transit at a dark-zone
station, we know the ground truth (real entry/exit time). At fixed points
through each transit (25%/50%/75% of the TRUE dwell time), we snapshot what
the filter believed at that instant, and compare it against the truth.

TRAIN/TEST SPLIT (the thing flagged as "later" work early on — this is
"later"): Layer 1 is fit ONLY on transits that started before a time cutoff
(default: first 70% of the shift, chronologically). Only transits that
started AFTER the cutoff are used for backtest evaluation. This avoids the
circularity of testing the filter against data it was directly fit on.

Usage:
    python3 backtest.py \\
        --stations stations.csv --station-events station_events.csv \\
        --units units.csv --manual-checks manual_checks.csv \\
        --checkpoint-events checkpoint_events_corrected.csv \\
        --station-checkpoints station_checkpoints.csv \\
        --output backtest_results.csv
"""

from __future__ import annotations

import argparse
import pandas as pd
import numpy as np

from dark_zone_tracker import fit_dwell_distribution
from orchestrator import DarkZoneOrchestrator, DarkZoneEvent, EventType
from csv_adapter import load_all_dark_zone_events, derive_historical_dwell_csv
from station_config import dark_zone_station_ids


def build_ground_truth_windows(station_events_csv: str, dark_zone_ids: set) -> pd.DataFrame:
    """One row per COMPLETED transit at a dark-zone station: real start/end/dwell."""
    ev = pd.read_csv(station_events_csv)
    ev = ev[ev["station_id"].isin(dark_zone_ids)]
    starts = ev[ev.event_type == "PROCESSING_STARTED"][
        ["station_id", "unit_id", "timestamp_ms"]
    ].rename(columns={"timestamp_ms": "true_start_ms"})
    ends = ev[ev.event_type == "PROCESSING_COMPLETED"][
        ["station_id", "unit_id", "timestamp_ms"]
    ].rename(columns={"timestamp_ms": "true_end_ms"})
    windows = starts.merge(ends, on=["station_id", "unit_id"])
    windows["true_dwell_ms"] = windows.true_end_ms - windows.true_start_ms
    return windows


def train_test_split_by_time(windows: pd.DataFrame, train_frac: float = 0.7):
    """
    Time-based split (not random) — mimics a real deployment: fit on the
    past, evaluate on the future. Cutoff is a single global percentile of
    true_start_ms across all dark-zone transits.
    """
    cutoff = windows["true_start_ms"].quantile(train_frac)
    train_units = set(
        windows[windows.true_start_ms < cutoff]
        .apply(lambda r: (r.station_id, r.unit_id), axis=1)
    )
    test_windows = windows[windows.true_start_ms >= cutoff].copy()
    return cutoff, train_units, test_windows


def run_backtest(
    stations_csv: str,
    station_events_csv: str,
    units_csv: str,
    manual_checks_csv: str = None,
    checkpoint_events_csv: str = None,
    station_checkpoints_csv: str = None,
    snapshot_fractions: tuple = (0.25, 0.5, 0.75),
    train_frac: float = 0.7,
    min_dwell_s: float = 15.0,   # skip transits too short for meaningful mid-cycle snapshots
    output_csv: str = "backtest_results.csv",
):
    dz = dark_zone_station_ids(stations_csv)
    windows = build_ground_truth_windows(station_events_csv, dz)
    windows = windows[windows.true_dwell_ms >= min_dwell_s * 1000]

    cutoff_ms, train_units, test_windows = train_test_split_by_time(windows, train_frac)
    print(f"Time cutoff: {cutoff_ms:.0f} ms. Train transits: {len(train_units)}, "
          f"Test transits: {len(test_windows)}.\n")

    # ---- Fit Layer 1 ONLY on training-period data ----
    hist_df = pd.read_csv(_write_temp_hist(station_events_csv, units_csv, dz))
    # Resolution-agnostic ms conversion — .astype('int64') on a datetime64
    # column assumes nanosecond resolution, but pandas may store it in
    # microseconds depending on version, silently corrupting this by 1000x
    # if assumed wrong. Timedelta division sidesteps the internal unit
    # entirely and is correct regardless of resolution.
    hist_df["entry_ms"] = (
        pd.to_datetime(hist_df["entry_ts"]) - pd.Timestamp("1970-01-01")
    ) / pd.Timedelta(milliseconds=1)
    train_hist = hist_df[hist_df.entry_ms < cutoff_ms].drop(columns=["entry_ms"])

    dwell_models = fit_dwell_distribution(train_hist, dist_name="gamma")
    for station in dz:
        fallback_key = (station, "__ALL__")
        if fallback_key not in dwell_models:
            candidates = [v for k, v in dwell_models.items() if k[0] == station]
            if candidates:
                dwell_models[fallback_key] = candidates[0]
    if ("__GLOBAL__", "__ALL__") not in dwell_models and len(train_hist) > 0:
        g = train_hist.copy()
        g["station_id"] = "__GLOBAL__"
        g["variant"] = "__ALL__"
        gfit = fit_dwell_distribution(g, dist_name="gamma", min_samples_for_own_fit=1)
        if ("__GLOBAL__", "__ALL__") in gfit:
            dwell_models[("__GLOBAL__", "__ALL__")] = gfit[("__GLOBAL__", "__ALL__")]

    print(f"Fitted Layer 1 on {len(train_hist)} training-period transits only.\n")

    # ---- Load full event stream, keep only TEST-set vehicles ----
    test_unit_ids = set(test_windows.unit_id)
    events = load_all_dark_zone_events(
        station_events_csv, units_csv, manual_checks_csv,
        checkpoint_events_csv, station_checkpoints_csv,
        dark_zone_station_ids=dz,
    )
    events = [e for e in events if e.vehicle_id in test_unit_ids]

    # ---- Inject synthetic snapshot TICKs at fixed fractions of TRUE dwell ----
    snapshot_lookup = {}  # (unit_id, snapshot_ts) -> (station_id, fraction, true_progress, true_remaining_s)
    for w in test_windows.itertuples(index=False):
        for frac in snapshot_fractions:
            snap_ts_ms = w.true_start_ms + frac * w.true_dwell_ms
            snap_ts_s = snap_ts_ms / 1000.0
            events.append(DarkZoneEvent(
                event_type=EventType.TICK, vehicle_id=w.unit_id,
                station_id=w.station_id, ts=snap_ts_s,
            ))
            true_remaining_s = (w.true_end_ms - snap_ts_ms) / 1000.0
            snapshot_lookup[(w.unit_id, round(snap_ts_s, 3))] = {
                "station_id": w.station_id, "fraction": frac,
                "true_progress": frac, "true_remaining_s": true_remaining_s,
            }

    events.sort(key=lambda e: (e.ts, 0 if e.event_type == EventType.STATION_ENTRY else
                                (2 if e.event_type == EventType.STATION_EXIT else 1)))

    # ---- Replay, capturing predictions at each snapshot ----
    orch = DarkZoneOrchestrator(dwell_models, persistence=None)
    results = []
    for ev in events:
        orch.route_event(ev)
        if ev.event_type == EventType.TICK:
            key = (ev.vehicle_id, round(ev.ts, 3))
            truth = snapshot_lookup.get(key)
            if truth and ev.vehicle_id in orch.active:
                snap = orch.export_snapshot(ev.vehicle_id)
                results.append({
                    "unit_id": ev.vehicle_id, "station_id": truth["station_id"],
                    "fraction": truth["fraction"],
                    "true_progress": truth["true_progress"],
                    "pred_progress": snap["progress_mean"],
                    "progress_error": abs(snap["progress_mean"] - truth["true_progress"]),
                    "true_remaining_s": truth["true_remaining_s"],
                    "pred_eta_s": snap["eta_seconds"],
                    "eta_error_s": abs(snap["eta_seconds"] - truth["true_remaining_s"]),
                    "pred_std": snap["progress_std"],
                    "pred_eta_std": snap["eta_std"],
                    "pred_confidence": snap["render_confidence"],
                })

    results_df = pd.DataFrame(results)
    results_df.to_csv(output_csv, index=False)
    print(f"Wrote {len(results_df)} snapshot comparisons -> {output_csv}\n")

    if len(results_df) == 0:
        print("⚠ No snapshots captured — check that test-set vehicles actually had events to replay.")
        return results_df

    print("=== Overall accuracy ===")
    print(f"Mean progress error:  {results_df.progress_error.mean():.3f} "
          f"(median {results_df.progress_error.median():.3f})")
    print(f"Mean ETA error:       {results_df.eta_error_s.mean():.1f}s "
          f"(median {results_df.eta_error_s.median():.1f}s)")
    print()
    print("=== By fraction through cycle ===")
    print(results_df.groupby("fraction")[["progress_error", "eta_error_s"]].mean().round(3))
    print()
    print("=== By station ===")
    print(results_df.groupby("station_id")[["progress_error", "eta_error_s"]].mean().round(3))
    print()
    print("=== Does filter confidence correlate with actual error? (want: negative correlation) ===")
    corr = results_df["pred_confidence"].corr(results_df["eta_error_s"])
    print(f"Correlation(confidence, eta_error_s): {corr:.3f}  "
          f"({'good — higher confidence means lower error, as intended' if corr < -0.1 else 'weak/no relationship — worth investigating' if corr > 0.1 else 'inconclusive'})")

    return results_df


def _write_temp_hist(station_events_csv, units_csv, dz):
    """derive_historical_dwell_csv doesn't preserve unit_id/timestamp for
    time-filtering — this rebuilds it directly with what we need for the split."""
    ev = pd.read_csv(station_events_csv)
    units = pd.read_csv(units_csv)
    variant_lookup = dict(zip(units.unit_id, units.vehicle_model))
    ev = ev[ev.station_id.isin(dz)]
    starts = ev[ev.event_type == "PROCESSING_STARTED"][["station_id", "unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "start_ms"})
    ends = ev[ev.event_type == "PROCESSING_COMPLETED"][["station_id", "unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "end_ms"})
    merged = starts.merge(ends, on=["station_id", "unit_id"])
    out = pd.DataFrame({
        "station_id": merged.station_id,
        "variant": merged.unit_id.map(variant_lookup),
        "entry_ts": pd.to_datetime(merged.start_ms, unit="ms"),
        "exit_ts": pd.to_datetime(merged.end_ms, unit="ms"),
    }).dropna(subset=["variant"])
    path = "_tmp_hist_for_backtest.csv"
    out.to_csv(path, index=False)
    return path


def main():
    parser = argparse.ArgumentParser(description="Dark Zone Tracking Engine — accuracy backtest")
    parser.add_argument("--stations", required=True)
    parser.add_argument("--station-events", required=True)
    parser.add_argument("--units", required=True)
    parser.add_argument("--manual-checks", default=None)
    parser.add_argument("--checkpoint-events", default=None)
    parser.add_argument("--station-checkpoints", default=None)
    parser.add_argument("--train-frac", type=float, default=0.7)
    parser.add_argument("--output", default="backtest_results.csv")
    args = parser.parse_args()

    run_backtest(
        stations_csv=args.stations,
        station_events_csv=args.station_events,
        units_csv=args.units,
        manual_checks_csv=args.manual_checks,
        checkpoint_events_csv=args.checkpoint_events,
        station_checkpoints_csv=args.station_checkpoints,
        train_frac=args.train_frac,
        output_csv=args.output,
    )


if __name__ == "__main__":
    main()
