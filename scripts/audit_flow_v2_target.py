"""
Flow v2 target distribution audit (Section 14) -- run BEFORE any feature
building or modeling. Reports everything required and compares against
Flow v1. Implements the Section 15/34 STOP gate: if positive prevalence
remains microscopic and independent positive episodes remain only a
handful, this script exits nonzero and no training should proceed.

Usage:
    python scripts/audit_flow_v2_target.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.holdout import compute_holdout_mask
from backend.flow.pipeline import build_station_minute_grid
from backend.flow_v2.labels import label_rows_v2
from backend.flow_v2.split import locked_flow_v2_split, validate_split

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def _episode_count(labeled_positive: pd.DataFrame) -> int:
    return labeled_positive.impact_event_id.nunique()


def main():
    t0 = time.time()
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    events = pd.read_parquet(BASE / "observable" / "events.parquet")
    scenario_truth = pd.read_parquet(BASE / "latent" / "scenario_truth.parquet")

    section("1. BOTTLENECK EVENTS (unchanged detector)")
    impacts = detect_bottleneck_events(events, config)
    print(f"Total impact events: {len(impacts)} across {impacts.shift_id.nunique()} shifts")

    section("2. STATION-MINUTE GRID + FLOW v2 LABELS (full 10-minute consequence window)")
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)
    print(f"Raw candidate rows: {len(grid):,}")
    t_label = time.time()
    labeled = label_rows_v2(grid, impacts, events)
    print(f"Labeling time: {time.time()-t_label:.1f}s")
    print(labeled.label.value_counts())

    total_eligible = labeled.label.isin(["POSITIVE", "NEGATIVE"]).sum()
    total_positive = (labeled.label == "POSITIVE").sum()
    prevalence = total_positive / total_eligible if total_eligible else float("nan")
    print(f"\nEligible rows (POSITIVE+NEGATIVE): {total_eligible:,}")
    print(f"Positive rows: {total_positive:,}  Prevalence: {prevalence*100:.4f}%")

    pos_rows = labeled[labeled.label == "POSITIVE"]
    n_episodes = _episode_count(pos_rows)
    n_positive_stations = pos_rows.station_id.nunique()
    n_positive_shifts = pos_rows.shift_id.nunique()
    print(f"Independent positive episodes (distinct impact_event_id): {n_episodes}")
    print(f"Positive stations: {n_positive_stations} -> {sorted(pos_rows.station_id.unique())}")
    print(f"Positive shifts: {n_positive_shifts} -> {sorted(pos_rows.shift_id.unique())}")
    print(f"\nPositives by station:\n{pos_rows.station_id.value_counts()}")

    section("3. EQUIPMENT_DEGRADATION HOLDOUT (Decision 35, unchanged)")
    holdout_mask = compute_holdout_mask(labeled, scenario_truth)
    supervised = labeled[~holdout_mask].copy()
    holdout = labeled[holdout_mask].copy()
    print(f"Held-out rows: {len(holdout):,}; supervised rows: {len(supervised):,}")
    print(f"Held-out shifts touched: {holdout.shift_id.nunique()}")

    section("4. GROUPED, MECHANISM-AWARE SPLIT (predeclared, not chronological)")
    all_shifts = sorted(events.shift_id.unique(), key=lambda x: int(x[5:]))
    split = locked_flow_v2_split(all_shifts)
    validate_split(split, all_shifts)
    print(f"TRAIN: {len(split.train_shifts)} shifts, VALIDATION: {len(split.validation_shifts)}, TEST: {len(split.test_shifts)}")

    partitions = {}
    for name, shifts in [("TRAIN", split.train_shifts), ("VALIDATION", split.validation_shifts), ("TEST", split.test_shifts)]:
        part = supervised[supervised.shift_id.isin(shifts)]
        part_eligible = part[part.label.isin(["POSITIVE", "NEGATIVE"])]
        part_pos = part_eligible[part_eligible.label == "POSITIVE"]
        n_ep = _episode_count(part_pos)
        partitions[name] = part_eligible
        print(f"{name}: eligible_rows={len(part_eligible):,} positives={len(part_pos)} "
              f"prevalence={len(part_pos)/max(1,len(part_eligible))*100:.4f}% "
              f"episodes={n_ep} positive_shifts={part_pos.shift_id.nunique()} "
              f"positive_stations={sorted(part_pos.station_id.unique())}")

    section("5. MECHANISM DISTRIBUTION (audit only, using scenario truth -- never a feature)")
    fam_by_shift = {}
    for _, row in scenario_truth[scenario_truth.family != "RANDOM_QUALITY_EVENT"].iterrows():
        fam_by_shift.setdefault(row.shift_id, set()).add(row.family)
    pos_rows_fam = pos_rows.copy()
    pos_rows_fam["mechanisms_in_shift"] = pos_rows_fam.shift_id.map(lambda s: sorted(fam_by_shift.get(s, [])))
    from collections import Counter
    fam_counter = Counter()
    for fams in pos_rows_fam.mechanisms_in_shift:
        for f in fams:
            fam_counter[f] += 1
    print(f"Positive rows by co-occurring known mechanism (a row's shift may have >1 mechanism): {dict(fam_counter)}")

    section("6. COMPARISON WITH FLOW v1")
    v1_dir = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1"
    v1_train = pd.read_parquet(v1_dir / "train.parquet")
    v1_val = pd.read_parquet(v1_dir / "validation.parquet")
    v1_test = pd.read_parquet(v1_dir / "test.parquet")
    v1_total = len(v1_train) + len(v1_val) + len(v1_test)
    v1_pos = (v1_train.target == 1).sum() + (v1_val.target == 1).sum() + (v1_test.target == 1).sum()
    v1_pos_shifts = pd.concat([v1_train[v1_train.target == 1], v1_val[v1_val.target == 1], v1_test[v1_test.target == 1]]).shift_id.nunique()
    v1_pos_stations = pd.concat([v1_train[v1_train.target == 1], v1_val[v1_val.target == 1], v1_test[v1_test.target == 1]]).station_id.nunique()

    comparison = pd.DataFrame({
        "Flow v1 (narrow 5-10min)": {
            "eligible rows": v1_total, "positive rows": int(v1_pos),
            "prevalence": f"{v1_pos/v1_total*100:.4f}%", "positive shifts": v1_pos_shifts,
            "positive stations": v1_pos_stations,
        },
        "Flow v2 (full 10min consequence)": {
            "eligible rows": int(total_eligible), "positive rows": int(total_positive),
            "prevalence": f"{prevalence*100:.4f}%", "positive shifts": n_positive_shifts,
            "positive stations": n_positive_stations,
        },
    })
    print(comparison)
    print(f"\nNOTE on episode counting: v1 never stored impact_event_id on labeled rows (a genuine gap this "
          f"v2 formulation fixes per Section 6), so a like-for-like 'episodes with >=1 eligible row' count "
          f"isn't directly recoverable from v1's saved data -- v1's own audit reported ~72 CONTIGUOUS "
          f"positive-row runs (a coarser proxy, not distinct impact_event_id). Using v2's precise "
          f"impact_event_id bookkeeping: of the {len(impacts)} raw detected impact events, {n_episodes} "
          f"({n_episodes/len(impacts)*100:.0f}%) now have at least one valid precursor row somewhere in "
          f"their full 10-minute window -- the real mechanism behind the positive-count improvement is that "
          f"v1's narrow 5-10-minute-only requirement discarded the large majority of real events (most of "
          f"their 5-10min sub-windows fell too close to shift start or overlapped a prior sub-episode's "
          f"ACTIVE period), not that v2 invented new episodes.")

    section("7. STOP GATE (Section 15/34)")
    # "a handful" is treated here as <10 independent episodes OR <5 positive
    # shifts total, spread thin enough that no partition gets meaningful
    # coverage -- both conditions must be comfortably cleared.
    gate_episodes_ok = n_episodes >= 10
    gate_shifts_ok = n_positive_shifts >= 5
    gate_partition_ok = all(
        (p.label == "POSITIVE").sum() >= 5 and p[p.label == "POSITIVE"].shift_id.nunique() >= 2
        for p in partitions.values()
    )
    print(f"episodes>=10: {gate_episodes_ok} ({n_episodes})")
    print(f"positive_shifts>=5: {gate_shifts_ok} ({n_positive_shifts})")
    print(f"every partition has >=5 positive rows and >=2 positive shifts: {gate_partition_ok}")
    for name, p in partitions.items():
        pos = p[p.label == "POSITIVE"]
        print(f"  {name}: positives={len(pos)} positive_shifts={pos.shift_id.nunique()}")

    passed = gate_episodes_ok and gate_shifts_ok and gate_partition_ok
    print(f"\n{'='*90}\nOVERALL GATE: {'PASS' if passed else 'FAIL'}\n{'='*90}")
    print(f"Total runtime: {time.time()-t0:.1f}s")
    return passed


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
