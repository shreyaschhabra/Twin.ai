"""
Full-scale independent re-derivation check (Step 5 rigor pass), borrowed
from the reference project's causal_validation.py practice of verifying
the ENTIRE materialized dataset via an independently-coded
reimplementation, not just a synthetic mutation probe on one sample.

Runs the independently-coded bottleneck-event detector and label
assigner (backend/flow/independent_check.py) against the production
implementation across ALL 100 shifts of Dataset C and reports any
divergence.

Usage:
    python scripts/flow_independent_leakage_check.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.independent_check import detect_impact_intervals_independent, label_rows_independent
from backend.flow.labels import label_rows
from backend.flow.pipeline import build_station_minute_grid

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    t0 = time.time()
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    events = pd.read_parquet(BASE / "observable" / "events.parquet")
    print(f"Loaded {len(events):,} events across {events.shift_id.nunique()} shifts in {time.time()-t0:.1f}s")

    section("BOTTLENECK EVENT DETECTION: production vs. independent re-derivation")
    t0 = time.time()
    production = detect_bottleneck_events(events, config)
    print(f"Production detector: {len(production)} events in {time.time()-t0:.1f}s")

    t0 = time.time()
    independent = detect_impact_intervals_independent(events, config)
    print(f"Independent detector: {len(independent)} events in {time.time()-t0:.1f}s")

    prod_keys = set(zip(production.shift_id, production.blocked_station_id,
                         production.onset_time.round(6), production.end_time.round(6)))
    indep_keys = set(zip(independent.shift_id, independent.blocked_station_id,
                          independent.onset_time.round(6), independent.end_time.round(6)))

    only_in_prod = prod_keys - indep_keys
    only_in_indep = indep_keys - prod_keys
    print(f"Events matching exactly: {len(prod_keys & indep_keys)} / {len(prod_keys)}")
    print(f"Only in production (missed by independent): {len(only_in_prod)}")
    print(f"Only in independent (missed by production): {len(only_in_indep)}")
    if only_in_prod:
        print(f"  sample: {list(only_in_prod)[:5]}")
    if only_in_indep:
        print(f"  sample: {list(only_in_indep)[:5]}")

    # impact_station_id attribution check on the matching subset
    prod_map = {(r.shift_id, r.blocked_station_id, round(r.onset_time, 6)): r.impact_station_id
                for r in production.itertuples()}
    attribution_mismatches = 0
    for r in independent.itertuples():
        key = (r.shift_id, r.blocked_station_id, round(r.onset_time, 6))
        if key in prod_map and prod_map[key] != r.impact_station_id:
            attribution_mismatches += 1
    print(f"impact_station_id attribution mismatches (on matched events): {attribution_mismatches}")

    section("LABEL ASSIGNMENT: production vs. independent re-derivation (full 100-shift grid)")
    station_ids = sorted(config.stations.keys())
    t0 = time.time()
    grid = build_station_minute_grid(events, station_ids)
    print(f"Grid: {len(grid):,} rows in {time.time()-t0:.1f}s")

    t0 = time.time()
    production_labeled = label_rows(grid, production)
    print(f"Production labels: {time.time()-t0:.1f}s")

    t0 = time.time()
    independent_labeled = label_rows_independent(grid, independent)
    print(f"Independent labels: {time.time()-t0:.1f}s")

    merged = production_labeled[["shift_id", "station_id", "window_end_time", "label"]].merge(
        independent_labeled[["shift_id", "station_id", "window_end_time", "label"]],
        on=["shift_id", "station_id", "window_end_time"], suffixes=("_prod", "_indep"),
    )
    mismatches = merged[merged.label_prod != merged.label_indep]
    print(f"\nTotal rows compared: {len(merged):,}")
    print(f"Label mismatches: {len(mismatches)}")
    if len(mismatches):
        print(mismatches.groupby(["label_prod", "label_indep"]).size())
        print(mismatches.head(20))

    section("VERDICT")
    all_ok = (len(only_in_prod) == 0 and len(only_in_indep) == 0
              and attribution_mismatches == 0 and len(mismatches) == 0)
    print("PASS -- independent re-derivation matches production exactly across the full dataset."
          if all_ok else "FAIL -- see divergence details above.")
    return all_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
