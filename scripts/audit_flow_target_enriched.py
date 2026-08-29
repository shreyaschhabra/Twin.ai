"""
Step 5 continuation (Decision 36), Sections 24-30: Flow target audit on
Dataset B (the coverage-balanced 100-shift corpus) -- BEFORE building
features across the whole thing. Reports target distribution overall and
by TRAIN/VALIDATION/TEST/UNSEEN_EQUIPMENT_DEGRADATION partition, checks
the same viability gates as the naturalistic audit, runs the
negative-opportunity audit (Section 29), and compares against Dataset A
(Section 30).

Usage:
    python scripts/audit_flow_target_enriched.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.holdout import compute_holdout_mask
from backend.flow.labels import label_rows
from backend.flow.pipeline import build_station_minute_grid
from backend.flow.split import locked_100_shift_split
from backend.historical.flow_enrichment import STATION_CANDIDATES

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
BASE_A = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100"
BASE_B = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_enriched"


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
    events = pd.read_parquet(BASE_B / "observable" / "events.parquet")
    scenario_truth = pd.read_parquet(BASE_B / "latent" / "scenario_truth.parquet")
    with (BASE_B / "flow_enriched_schedule.json").open() as f:
        schedule_plan = json.load(f)

    section("BOTTLENECK IMPACT EVENTS (Dataset B, 100-shift enriched corpus)")
    impacts = detect_bottleneck_events(events, config)
    print(f"Total impact events: {len(impacts)}")
    print(f"\nBy shift (top 15):\n{impacts.shift_id.value_counts().head(15)}")
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

    section("STATION-MINUTE GRID + LABELS (Dataset B, full 100 shifts)")
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
    if len(impacts):
        durations = (impacts.end_time - impacts.onset_time)
        print(f"\nImpact duration distribution (seconds):\n{durations.describe()}")

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
    holdout_impacts = impacts[impacts.shift_id.isin(degradation_events.shift_id.unique())]
    print(f"Impact events in shifts containing EQUIPMENT_DEGRADATION: {len(holdout_impacts)}")

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

    train_events = impacts[impacts.shift_id.isin(split.train_shifts)]
    val_events = impacts[impacts.shift_id.isin(split.validation_shifts)]
    test_events = impacts[impacts.shift_id.isin(split.test_shifts)]
    print(f"\nImpact events -- TRAIN: {len(train_events)}  VALIDATION: {len(val_events)}  TEST: {len(test_events)}")

    section("VIABILITY GATE (Section 27)")
    def gate(name, pos, shifts, min_pos, min_shifts):
        ok = pos >= min_pos and shifts >= min_shifts
        print(f"  {name}: positives={pos} (need >={min_pos}), distinct_shifts={shifts} "
              f"(need >={min_shifts}) -> {'PASS' if ok else 'FAIL'}")
        return ok

    train_ok = gate("TRAIN", train_pos, train_shifts, 100, 5)
    val_ok = gate("VALIDATION", val_pos, val_shifts, 20, 2)
    test_ok = gate("TEST", test_pos, test_shifts, 20, 2)

    section("CONCENTRATION GATE (Section 28)")
    sup_pos = supervised[supervised.label == "POSITIVE"]
    overall_pos_shifts = sup_pos.shift_id.nunique()
    overall_pos_stations = sup_pos.station_id.nunique()
    shift_share = (sup_pos.shift_id.value_counts().iloc[0] / max(1, len(sup_pos))) if len(sup_pos) else float("nan")
    station_share = (sup_pos.station_id.value_counts().iloc[0] / max(1, len(sup_pos))) if len(sup_pos) else float("nan")
    zone_share_pos = sup_pos.station_id.map(_zone_of).value_counts()
    zone_share = (zone_share_pos.iloc[0] / max(1, len(sup_pos))) if len(sup_pos) else float("nan")
    print(f"Supervised positives across {overall_pos_shifts} distinct shifts, {overall_pos_stations} distinct stations")
    print(f"Largest single-shift share of SUPERVISED positives: {shift_share * 100:.1f}%")
    print(f"Largest single-station share of SUPERVISED positives: {station_share * 100:.1f}%")
    print(f"Largest single-zone share of SUPERVISED positives: {zone_share * 100:.1f}%")
    print(f"Station breakdown of positives:\n{sup_pos.station_id.value_counts()}")

    # attribute each impact event to the scenario family active on its
    # station/shift at onset, purely for reporting (never used to relabel)
    family_by_shift_station = {}
    for _, row in scenario_truth.iterrows():
        try:
            sids = json.loads(row.station_ids) if isinstance(row.station_ids, str) else row.station_ids
        except (TypeError, json.JSONDecodeError):
            sids = []
        for sid in sids:
            family_by_shift_station.setdefault((row.shift_id, sid), []).append(row.family)
        if not sids:
            family_by_shift_station.setdefault((row.shift_id, "__line_level__"), []).append(row.family)

    def _attribute_family(ev):
        candidates = family_by_shift_station.get((ev.shift_id, ev.impact_station_id), [])
        line_level = family_by_shift_station.get((ev.shift_id, "__line_level__"), [])
        all_candidates = [f for f in candidates + line_level if f != "RANDOM_QUALITY_EVENT"]
        return Counter(all_candidates).most_common(1)[0][0] if all_candidates else "UNKNOWN_OR_NATURAL"

    if len(impacts):
        impacts = impacts.copy()
        impacts["attributed_family"] = impacts.apply(_attribute_family, axis=1)
        family_share = impacts.attributed_family.value_counts()
        print(f"\nImpact events by attributed scenario family:\n{family_share}")
        top_family_share = family_share.iloc[0] / len(impacts)
        print(f"Largest single-family share of events: {top_family_share * 100:.1f}%")

    section("NEGATIVE-OPPORTUNITY AUDIT (Section 29)")
    known_opps = [o for o in schedule_plan if o["kind"] == "known_flow_enrichment"]
    impact_shift_stations = set(zip(impacts.shift_id, impacts.impact_station_id)) if len(impacts) else set()
    outcome_rows = []
    for o in known_opps:
        key_station = o["station_id"] if o["station_id"] else None
        if key_station is not None:
            became_positive_station = (o["shift_id"], key_station) in impact_shift_stations
        else:
            expected = {"S22", "S26", "S36"}
            became_positive_station = any((o["shift_id"], s) in impact_shift_stations for s in expected)
        outcome_rows.append({
            "family": o["family"], "severity_stratum": o["severity_stratum"],
            "produced_blocking": became_positive_station,
        })
    outcome_df = pd.DataFrame(outcome_rows)
    if len(outcome_df):
        print("Outcome by family:")
        print(outcome_df.groupby("family").produced_blocking.agg(["sum", "count", "mean"]))
        print("\nOutcome by severity stratum:")
        print(outcome_df.groupby("severity_stratum").produced_blocking.agg(["sum", "count", "mean"]))
        n_no_congestion = (~outcome_df.produced_blocking).sum()
        print(f"\n{n_no_congestion}/{len(outcome_df)} scheduled Flow opportunities produced NO detected "
              f"blocking at their target station -- confirms abnormal != automatically bottleneck.")

    section("QC DEFECT-RATE CHECK (Section 17)")
    qc_b = pd.read_parquet(BASE_B / "observable" / "qc_results.parquet")
    qc_a = pd.read_parquet(BASE_A / "observable" / "qc_results.parquet")
    rate_b = (qc_b.qc_result == "DEFECT").mean()
    rate_a = (qc_a.qc_result == "DEFECT").mean()
    print(f"Dataset A defect rate: {rate_a*100:.3f}%  |  Dataset B defect rate: {rate_b*100:.3f}%  "
          f"|  delta: {(rate_b-rate_a)*100:+.3f}pp")

    section("COMPARISON WITH DATASET A (Section 30)")
    events_a = pd.read_parquet(BASE_A / "observable" / "events.parquet")
    scenario_truth_a = pd.read_parquet(BASE_A / "latent" / "scenario_truth.parquet")
    impacts_a = detect_bottleneck_events(events_a, config)
    grid_a = build_station_minute_grid(events_a, station_ids)
    labeled_a = label_rows(grid_a, impacts_a)
    pos_a = (labeled_a.label == "POSITIVE").sum()
    pos_shifts_a = labeled_a[labeled_a.label == "POSITIVE"].shift_id.nunique()
    top_station_share_a = impacts_a.impact_station_id.value_counts().iloc[0] / len(impacts_a) if len(impacts_a) else float("nan")
    top_shift_share_a = impacts_a.shift_id.value_counts().iloc[0] / len(impacts_a) if len(impacts_a) else float("nan")

    comparison = pd.DataFrame({
        "Naturalistic (A)": {
            "Flow-positive rows": pos_a, "positive shifts": pos_shifts_a,
            "impact events": len(impacts_a), "largest station share": f"{top_station_share_a*100:.1f}%",
            "largest shift share": f"{top_shift_share_a*100:.1f}%", "QC defect rate": f"{rate_a*100:.3f}%",
        },
        "Flow-enriched (B)": {
            "Flow-positive rows": len(pos_df), "positive shifts": overall_pos_shifts,
            "impact events": len(impacts), "largest station share": f"{station_share*100:.1f}%",
            "largest shift share": f"{shift_share*100:.1f}%", "QC defect rate": f"{rate_b*100:.3f}%",
        },
    })
    print(comparison)
    print("\nDataset B's scenario frequency/severity is a MODELING-DEVELOPMENT design choice, "
          "not a claim about real production occurrence rates -- Dataset A remains the honest "
          "naturalistic reference for false-alert / class-imbalance analysis.")

    all_pass = train_ok and val_ok and test_ok
    print(f"\n{'='*90}\nOVERALL GATE: {'PASS' if all_pass else 'FAIL'}\n{'='*90}")
    return all_pass


if __name__ == "__main__":
    passed = main()
    sys.exit(0 if passed else 1)
