"""
Multi-Station Corridor Tracker — Real Data Driver
=======================================================
Runs the multi-station particle filter (multi_station_tracker.py) against
a REAL detected corridor, not synthetic data.

CALIBRATION NOTE (read this before trusting the numbers): stations.csv's
declared base_cycle_time_ms values are PURE PROCESSING time. The real
observed corridor dwell (DARK_ZONE_EXITED ts - DARK_ZONE_ENTERED ts) is
~2.6x larger — the gap is queueing/blocking wait time at buffer-constrained
interior stations, which the declared processing-time parameters don't
capture. Using declared values directly would badly under-predict ETA.
This script rescales each interior station's prior proportionally so the
SUM matches the real observed aggregate corridor mean/std — an honest,
documented calibration step, not a silent fix.

WHAT THIS CAN AND CANNOT VALIDATE:
  CAN validate: ETA-to-corridor-exit accuracy — real ground truth exists
  (every vehicle's actual DARK_ZONE_EXITED timestamp).
  CANNOT validate: "which station" accuracy — the whole point of a
  corridor is that interior per-station boundaries are genuinely unknown
  in this file. That needs a SEPARATE ground-truth reference file from the
  simulation engineer, generated for scoring purposes only, never fed to
  the filter itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dark_zone_tracker import DwellDistribution
from multi_station_tracker import MultiStationParticleFilter, MultiStationConfig
from corridor_config import detect_corridors, corridor_interior_stations


def build_calibrated_priors(
    stations_csv: str,
    interior_stations: list[str],
    real_mean_s: float,
    real_std_s: float,
) -> dict[str, DwellDistribution]:
    """
    Rescales stations.csv's declared per-station (mean, std) so their SUM
    matches the real observed aggregate corridor timing, preserving each
    station's RELATIVE share of the total (a station declared 2x longer
    than another stays 2x longer post-scaling) while fixing the absolute
    scale to match reality.
    """
    stations = pd.read_csv(stations_csv).set_index("station_id")
    declared_means = np.array([stations.loc[s, "base_cycle_time_ms"] / 1000 for s in interior_stations])
    declared_stds = np.array([stations.loc[s, "cycle_time_std_ms"] / 1000 for s in interior_stations])

    scale_factor = real_mean_s / declared_means.sum()
    calibrated_means = declared_means * scale_factor
    # scale std by the SAME factor (preserves each station's coefficient of
    # variation, a defensible assumption absent better information)
    calibrated_stds = declared_stds * scale_factor

    print(f"Calibration: declared sum={declared_means.sum():.1f}s, "
          f"real observed mean={real_mean_s:.1f}s, scale factor={scale_factor:.2f}x")

    dwell_distributions = {}
    for station, mean, std in zip(interior_stations, calibrated_means, calibrated_stds):
        shape = (mean / std) ** 2
        scale = (std ** 2) / mean
        dwell_distributions[station] = DwellDistribution(
            station=station, variant="__ALL__", dist_name="gamma",
            params=(shape, 0, scale), n_samples=0, fallback=True,  # fallback=True: not fit from real per-station data
        )
        print(f"  {station}: declared mean={stations.loc[station,'base_cycle_time_ms']/1000:.1f}s "
              f"-> calibrated mean={mean:.1f}s (std={std:.1f}s)")
    return dwell_distributions


def load_corridor_windows(station_events_csv: str, entry_station: str, exit_station: str) -> pd.DataFrame:
    ev = pd.read_csv(station_events_csv)
    entered = ev[(ev.event_type == "DARK_ZONE_ENTERED") & (ev.station_id == entry_station)][
        ["unit_id", "timestamp_ms"]
    ].rename(columns={"timestamp_ms": "enter_ms"})
    exited = ev[(ev.event_type == "DARK_ZONE_EXITED") & (ev.station_id == exit_station)][
        ["unit_id", "timestamp_ms"]
    ].rename(columns={"timestamp_ms": "exit_ms"})
    windows = entered.merge(exited, on="unit_id")
    windows["dwell_s"] = (windows.exit_ms - windows.enter_ms) / 1000
    return windows


def load_valid_checkpoints(checkpoint_events_csv: str, interior_stations: list[str],
                            station_checkpoints_csv: str) -> pd.DataFrame:
    ce = pd.read_csv(checkpoint_events_csv)
    sc = pd.read_csv(station_checkpoints_csv)

    before = len(ce)
    ce = ce.dropna(subset=["unit_id"])
    dropped_null = before - len(ce)
    if dropped_null:
        print(f"({dropped_null} checkpoint event(s) with null unit_id excluded — this is "
              f"EXPECTED for checkpoint types with identifiesUnit=false in the source config "
              f"(e.g. POWER_DRAW sensors that detect activity but can't identify which vehicle), "
              f"not a data bug. These can't be attributed to any specific particle filter, but "
              f"could inform aggregate station-activity signals in a future extension.)")

    ce = ce[ce.station_id.isin(interior_stations)]
    ce = ce.merge(sc[["station_id", "checkpoint_id", "nominal_progress_fraction"]],
                   on=["station_id", "checkpoint_id"], how="left")
    print(f"Valid intra-corridor checkpoint events usable as evidence: {len(ce)}")
    print(ce.groupby("station_id").size())
    return ce


def run_corridor_backtest(
    stations_csv: str, station_events_csv: str, checkpoint_events_csv: str,
    station_checkpoints_csv: str, train_frac: float = 0.7,
):
    corridors = detect_corridors(station_events_csv)
    if not corridors:
        print("No multi-station corridors detected in this file.")
        return
    c = corridors[0]
    entry_station, exit_station = c["entry_station"], c["exit_station"]
    interior = corridor_interior_stations(station_events_csv, stations_csv, entry_station, exit_station)
    print(f"Corridor: {entry_station} -> {exit_station}, interior stations: {interior}\n")

    windows = load_corridor_windows(station_events_csv, entry_station, exit_station)

    # CAUSALITY FIX: calibrate priors using only EARLIER-starting transits;
    # evaluate only on LATER-starting transits. Using the full dataset's
    # aggregate mean/std to calibrate priors for EVERY vehicle (including
    # ones from early in the shift) leaks information from vehicles that
    # hadn't been created yet at prediction time — the same mistake we
    # already caught and fixed once for the single-station backtest, ported
    # forward here without the fix. Fixing it the same way now.
    cutoff_ms = windows["enter_ms"].quantile(train_frac)
    train_windows = windows[windows.enter_ms < cutoff_ms]
    test_windows = windows[windows.enter_ms >= cutoff_ms]
    print(f"Time cutoff: {cutoff_ms:.0f} ms. "
          f"Calibration transits (train): {len(train_windows)}, "
          f"Evaluation transits (test): {len(test_windows)}.\n")

    real_mean_s = train_windows.dwell_s.mean()
    real_std_s = train_windows.dwell_s.std()
    print(f"Calibration corridor dwell (train-only): mean={real_mean_s:.1f}s, std={real_std_s:.1f}s\n")

    dwell_distributions = build_calibrated_priors(stations_csv, interior, real_mean_s, real_std_s)
    print()

    checkpoints = load_valid_checkpoints(checkpoint_events_csv, interior, station_checkpoints_csv)
    checkpoint_lookup = {}  # unit_id -> list of (ts_s, station_id, progress)
    for row in checkpoints.itertuples(index=False):
        checkpoint_lookup.setdefault(row.unit_id, []).append(
            (row.timestamp_ms / 1000.0, row.station_id, row.nominal_progress_fraction)
        )
    print()

    # ---- Backtest: ETA-to-corridor-exit accuracy, TEST SET ONLY ----
    query_fractions = [0.25, 0.5, 0.75, 0.95]
    results = {f: [] for f in query_fractions}
    rng = np.random.default_rng(123)

    for w in test_windows.itertuples(index=False):
        pf = MultiStationParticleFilter(interior, dwell_distributions,
                                         MultiStationConfig(n_particles=1500), rng=rng)
        enter_s = w.enter_ms / 1000.0
        cps = sorted(checkpoint_lookup.get(w.unit_id, []), key=lambda x: x[0])

        prev_t = enter_s
        cp_idx = 0
        for frac in query_fractions:
            target_t = enter_s + frac * w.dwell_s
            # apply any checkpoints that fall before this query point
            while cp_idx < len(cps) and cps[cp_idx][0] <= target_t:
                cp_ts, cp_station, cp_progress = cps[cp_idx]
                pf.predict(cp_ts - prev_t)
                if cp_station in interior and not np.isnan(cp_progress):
                    pf.update_checkpoint(cp_station, cp_progress, sensor_std=0.05)
                prev_t = cp_ts
                cp_idx += 1
            pf.predict(target_t - prev_t)
            prev_t = target_t

            est = pf.estimate()
            true_remaining_s = w.dwell_s - (target_t - enter_s)
            results[frac].append({
                "eta_error_s": abs(est["eta_block_exit_s"] - true_remaining_s),
                "confidence": est["confidence"],
            })

    print(f"{'fraction':>8} {'n':>5} {'mean_eta_error_s':>17} {'median_eta_error_s':>19}")
    for frac in query_fractions:
        errs = [r["eta_error_s"] for r in results[frac]]
        print(f"{frac:>8.2f} {len(errs):>5} {np.mean(errs):>17.1f} {np.median(errs):>19.1f}")


if __name__ == "__main__":
    run_corridor_backtest(
        stations_csv="stations.csv",
        station_events_csv="station_events.csv",
        checkpoint_events_csv="checkpoint_events.csv",
        station_checkpoints_csv="station_checkpoints.csv",
    )
