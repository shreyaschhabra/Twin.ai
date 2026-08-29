"""
Step 5 continuation, Section 6/7: Flow target audit on the 100-shift
historical dataset — BEFORE building features across the whole thing.
Reports target distribution overall and by TRAIN/VALIDATION/TEST/
UNSEEN_EQUIPMENT_DEGRADATION partition, and checks the viability gates.

Usage:
    python scripts/audit_flow_target_100.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.holdout import compute_holdout_mask
from backend.flow.labels import label_rows
from backend.flow.pipeline import build_station_minute_grid
from backend.flow.split import locked_100_shift_split

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100"


def _zone_of(station_id: str) -> str:
    n = int(station_id[1:])
    if n <= 12:
        return "body_joining"
    if n <= 20:
        return "paint_surface"
    if n <= 38:
        return "final_assembly"
    return "inspection_eol"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def report_partition(name, labeled_part):
    pos = (labeled_part.label == "POSITIVE").sum()
    neg = (labeled_part.label == "NEGATIVE").sum()
    imm = (labeled_part.label == "IMMINENT").sum()
    act = (labeled_part.label == "ACTIVE").sum()
    n_shifts_with_pos = labeled_part[labeled_part.label == "POSITIVE"].shift_id.nunique()
    print(f"{name:<12} rows={len(labeled_part):>8}  POS={pos:>5}  NEG={neg:>8}  "
          f"IMMINENT={imm:>5}  ACTIVE={act:>5}  shifts_with_positives={n_shifts_with_pos}")
    return pos, neg, n_shifts_with_pos


def main():
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    events = pd.read_parquet(BASE / "observable" / "events.parquet")
    scenario_truth = pd.read_parquet(BASE / "latent" / "scenario_truth.parquet")

    section("BOTTLENECK IMPACT EVENTS (100-shift dataset)")
    impacts = detect_bottleneck_events(events, config)
    print(f"Total impact events: {len(impacts)}")
    print(f"\nBy shift:\n{impacts.shift_id.value_counts()}")
    print(f"\nBy station:\n{impacts.impact_station_id.value_counts()}")
    zone_counts = impacts.impact_station_id.map(_zone_of).value_counts()
    print(f"\nBy zone:\n{zone_counts}")

    n_shifts_with_events = impacts.shift_id.nunique()
    top_shift_share = impacts.shift_id.value_counts().iloc[0] / len(impacts) if len(impacts) else float("nan")
    top_station_share = impacts.impact_station_id.value_counts().iloc[0] / len(impacts) if len(impacts) else float("nan")
    top_zone_share = zone_counts.iloc[0] / len(impacts) if len(impacts) else float("nan")
    print(f"\nDistinct shifts with >=1 impact event: {n_shifts_with_events} / 100")
    print(f"Largest single-shift share of events: {top_shift_share * 100:.1f}%")
    print(f"Largest single-station share of events: {top_station_share * 100:.1f}%")
    print(f"Largest single-zone share of events: {top_zone_share * 100:.1f}%")

    section("STATION-MINUTE GRID + LABELS (full 100-shift dataset)")
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)
    labeled = label_rows(grid, impacts)
    print(f"Total rows: {len(labeled)}")
    print(labeled.label.value_counts())
    pos_df = labeled[labeled.label == "POSITIVE"]
    if len(pos_df):
        print(f"\nLead-time distribution for POSITIVE rows:\n{pos_df.lead_time_s.describe()}")
    total_valid = (labeled.label.isin(["POSITIVE", "NEGATIVE"])).sum()
    print(f"\nOverall positive prevalence (of valid POS+NEG): "
          f"{pos_df.shape[0] / total_valid * 100:.5f}%")

    section("EQUIPMENT_DEGRADATION HOLDOUT")
    holdout_mask = compute_holdout_mask(labeled, scenario_truth)
    labeled["partition"] = "supervised"
    labeled.loc[holdout_mask, "partition"] = "UNSEEN_EQUIPMENT_DEGRADATION_ROBUSTNESS"
    n_holdout = holdout_mask.sum()
    holdout_df = labeled[holdout_mask]
    print(f"Total held-out rows: {n_holdout}")
    print(f"Held-out label breakdown:\n{holdout_df.label.value_counts()}")
    degradation_events = scenario_truth[scenario_truth.family == "EQUIPMENT_DEGRADATION"]
    print(f"EQUIPMENT_DEGRADATION scenario instances: {len(degradation_events)}")
    print(f"Shifts with EQUIPMENT_DEGRADATION: {degradation_events.shift_id.nunique()}")

    supervised = labeled[~holdout_mask]

    section("SPLIT PARTITIONS (locked chronological, supervised rows only)")
    split = locked_100_shift_split()
    train = supervised[supervised.shift_id.isin(split.train_shifts)]
    val = supervised[supervised.shift_id.isin(split.validation_shifts)]
    test = supervised[supervised.shift_id.isin(split.test_shifts)]

    train_pos, train_neg, train_shifts = report_partition("TRAIN", train)
    val_pos, val_neg, val_shifts = report_partition("VALIDATION", val)
    test_pos, test_neg, test_shifts = report_partition("TEST", test)
    report_partition("HOLDOUT", holdout_df)

    section("VIABILITY GATE (Section 7)")
    def gate(name, pos, shifts, min_pos, min_shifts):
        ok = pos >= min_pos and shifts >= min_shifts
        print(f"  {name}: positives={pos} (need >={min_pos}), distinct_shifts={shifts} "
              f"(need >={min_shifts}) -> {'PASS' if ok else 'FAIL'}")
        return ok

    train_ok = gate("TRAIN", train_pos, train_shifts, 100, 5)
    val_ok = gate("VALIDATION", val_pos, val_shifts, 20, 2)
    test_ok = gate("TEST", test_pos, test_shifts, 20, 2)

    overall_pos_shifts = supervised[supervised.label == "POSITIVE"].shift_id.nunique()
    overall_pos_stations = supervised[supervised.label == "POSITIVE"].station_id.nunique()
    single_shift_dominance = (
        supervised[supervised.label == "POSITIVE"].shift_id.value_counts().iloc[0]
        / max(1, (supervised.label == "POSITIVE").sum())
    ) if (supervised.label == "POSITIVE").sum() else float("nan")
    print(f"\nSupervised (non-holdout) positives across {overall_pos_shifts} distinct shifts, "
          f"{overall_pos_stations} distinct stations")
    print(f"Largest single-shift share of SUPERVISED positives: {single_shift_dominance * 100:.1f}%")

    all_pass = train_ok and val_ok and test_ok
    print(f"\n{'='*90}\nOVERALL GATE: {'PASS' if all_pass else 'FAIL'}\n{'='*90}")
    return all_pass


if __name__ == "__main__":
    passed = main()
    sys.exit(0 if passed else 1)
