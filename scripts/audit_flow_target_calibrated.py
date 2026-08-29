"""
Step 5 continuation (Decision 37), Sections 17-22: Flow target audit on
Dataset C -- BEFORE building features. Reports target distribution
overall and by TRAIN/VALIDATION/TEST/UNSEEN_EQUIPMENT_DEGRADATION,
checks the viability gates, runs the opportunity-conversion audit
(no-congestion / queue-growth-no-blocking / actual-blocking per
scheduled opportunity), and compares Datasets A/B/C.

Usage:
    python scripts/audit_flow_target_calibrated.py
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
from backend.historical.flow_enrichment import MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
BASE_A = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100"
BASE_B = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_enriched"
BASE_C = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"


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


def _load(base):
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    events = pd.read_parquet(base / "observable" / "events.parquet")
    scenario_truth = pd.read_parquet(base / "latent" / "scenario_truth.parquet")
    impacts = detect_bottleneck_events(events, config)
    return config, events, scenario_truth, impacts


def _dataset_stats(base, config, events, impacts):
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)
    labeled = label_rows(grid, impacts)
    pos = (labeled.label == "POSITIVE").sum()
    pos_shifts = labeled[labeled.label == "POSITIVE"].shift_id.nunique()
    qc = pd.read_parquet(base / "observable" / "qc_results.parquet")
    rate = (qc.qc_result == "DEFECT").mean()
    station_share = impacts.impact_station_id.value_counts().iloc[0] / len(impacts) if len(impacts) else float("nan")
    shift_share = impacts.shift_id.value_counts().iloc[0] / len(impacts) if len(impacts) else float("nan")
    return labeled, dict(pos=pos, pos_shifts=pos_shifts, events=len(impacts), rate=rate,
                          station_share=station_share, shift_share=shift_share)


def _opportunity_conversion_audit(schedule_plan, events, impacts, config):
    known = [o for o in schedule_plan if o["kind"] == "known_flow_enrichment"]
    buffers_by_downstream = {b.downstream_station: (bid, b.capacity) for bid, b in config.buffers.items()}
    occ_events = events[events.event_type == "VEHICLE_ENTERED_BUFFER"][
        ["shift_id", "buffer_id", "simulation_time", "occupancy"]
    ]
    impact_lookup = impacts[["shift_id", "impact_station_id", "onset_time"]] if len(impacts) else pd.DataFrame()

    rows = []
    for i_by_shift in {}.fromkeys(o["shift_id"] for o in known):
        pass  # placeholder to keep structure simple; real loop below

    # reconstruct per-shift opportunity index (matches scenario_id
    # assignment order in build_shift_schedule_enriched)
    per_shift_counter = Counter()
    for o in known:
        idx = per_shift_counter[o["shift_id"]]
        per_shift_counter[o["shift_id"]] += 1

        target_stations = [o["station_id"]] if o["station_id"] else MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS
        start = None
        # find the actual scenario_truth start/end via naming convention
        scenario_id_guess = f"{o['shift_id']}::flow_enrich::known_flow_enrichment::{idx}"

        outcome = "no_meaningful_congestion"
        max_ratio = 0.0
        for target in target_stations:
            bid, cap = buffers_by_downstream.get(target, (None, None))
            if bid is None:
                continue
            shift_occ = occ_events[(occ_events.shift_id == o["shift_id"]) & (occ_events.buffer_id == bid)]
            if len(shift_occ):
                ratio = shift_occ.occupancy.max() / cap
                max_ratio = max(max_ratio, ratio)
            if len(impact_lookup):
                hit = impact_lookup[(impact_lookup.shift_id == o["shift_id"]) & (impact_lookup.impact_station_id == target)]
                if len(hit):
                    outcome = "actual_blocking"
        if outcome != "actual_blocking" and max_ratio >= 0.75:
            outcome = "queue_growth_no_blocking"

        rows.append({
            "shift_id": o["shift_id"], "family": o["family"], "station_id": o["station_id"],
            "severity_stratum": o["severity_stratum"], "severity": o["severity"],
            "expected_bottleneck_capable": o["expected_bottleneck_capable"],
            "max_buffer_occupancy_ratio": max_ratio, "outcome": outcome,
        })
    return pd.DataFrame(rows)


def main():
    config, events, scenario_truth, impacts = _load(BASE_C)
    with (BASE_C / "flow_calibrated_schedule.json").open() as f:
        schedule_plan = json.load(f)

    section("BOTTLENECK IMPACT EVENTS (Dataset C, 100-shift calibrated corpus)")
    print(f"Total impact events: {len(impacts)}")
    print(f"\nBy shift (top 15):\n{impacts.shift_id.value_counts().head(15)}")
    print(f"\nBy station:\n{impacts.impact_station_id.value_counts()}")
    zone_counts = impacts.impact_station_id.map(_zone_of).value_counts()
    print(f"\nBy zone:\n{zone_counts}")
    n_shifts_with_events = impacts.shift_id.nunique()
    print(f"\nDistinct shifts with >=1 impact event: {n_shifts_with_events} / 100")

    section("STATION-MINUTE GRID + LABELS (Dataset C, full 100 shifts)")
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)
    labeled = label_rows(grid, impacts)
    print(labeled.label.value_counts())
    pos_df = labeled[labeled.label == "POSITIVE"]
    if len(pos_df):
        print(f"\nLead-time distribution for POSITIVE rows:\n{pos_df.lead_time_s.describe()}")
    total_valid = (labeled.label.isin(["POSITIVE", "NEGATIVE"])).sum()
    print(f"\nOverall positive prevalence: {pos_df.shape[0] / total_valid * 100:.5f}%")

    section("EQUIPMENT_DEGRADATION HOLDOUT")
    holdout_mask = compute_holdout_mask(labeled, scenario_truth)
    labeled["partition"] = "supervised"
    labeled.loc[holdout_mask, "partition"] = "UNSEEN_EQUIPMENT_DEGRADATION_ROBUSTNESS"
    holdout_df = labeled[holdout_mask]
    print(f"Total held-out rows: {holdout_mask.sum()}")
    print(f"Held-out label breakdown:\n{holdout_df.label.value_counts()}")
    degradation_events = scenario_truth[scenario_truth.family == "EQUIPMENT_DEGRADATION"]
    print(f"EQUIPMENT_DEGRADATION scenario instances: {len(degradation_events)}, "
          f"shifts: {degradation_events.shift_id.nunique()}")

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

    section("VIABILITY GATE (Section 19)")
    def gate(name, pos, shifts, min_pos, min_shifts):
        ok = pos >= min_pos and shifts >= min_shifts
        print(f"  {name}: positives={pos} (need >={min_pos}), distinct_shifts={shifts} "
              f"(need >={min_shifts}) -> {'PASS' if ok else 'FAIL'}")
        return ok

    train_ok = gate("TRAIN", train_pos, train_shifts, 100, 5)
    val_ok = gate("VALIDATION", val_pos, val_shifts, 20, 2)
    test_ok = gate("TEST", test_pos, test_shifts, 20, 2)

    section("CONCENTRATION")
    sup_pos = supervised[supervised.label == "POSITIVE"]
    if len(sup_pos):
        shift_share = sup_pos.shift_id.value_counts().iloc[0] / len(sup_pos)
        station_share = sup_pos.station_id.value_counts().iloc[0] / len(sup_pos)
        zone_share = sup_pos.station_id.map(_zone_of).value_counts().iloc[0] / len(sup_pos)
        print(f"Supervised positives across {sup_pos.shift_id.nunique()} shifts, {sup_pos.station_id.nunique()} stations")
        print(f"Largest single-shift share: {shift_share*100:.1f}%  station share: {station_share*100:.1f}%  "
              f"zone share: {zone_share*100:.1f}%")
        print(f"Station breakdown:\n{sup_pos.station_id.value_counts()}")

    section("OPPORTUNITY CONVERSION AUDIT (Section 20)")
    conversion = _opportunity_conversion_audit(schedule_plan, events, impacts, config)
    if len(conversion):
        print("By family:")
        print(conversion.groupby("family").outcome.value_counts().unstack(fill_value=0))
        print("\nBy severity stratum:")
        print(conversion.groupby("severity_stratum").outcome.value_counts().unstack(fill_value=0))
        print("\nBy station:")
        print(conversion.groupby("station_id", dropna=False).outcome.value_counts().unstack(fill_value=0))
        severe = conversion[conversion.severity_stratum == "SEVERE"]
        if len(severe):
            blocking_rate = (severe.outcome == "actual_blocking").mean()
            print(f"\nSEVERE actual_blocking rate: {blocking_rate*100:.1f}% "
                  f"({'FLAG: over-strength, always blocks' if blocking_rate >= 0.98 else 'FLAG: under-strength, never blocks' if blocking_rate == 0 else 'within expected genuinely-possible-not-guaranteed range'})")

    section("QC DEFECT-RATE CHECK")
    qc_c = pd.read_parquet(BASE_C / "observable" / "qc_results.parquet")
    rate_c = (qc_c.qc_result == "DEFECT").mean()
    print(f"Dataset C defect rate: {rate_c*100:.3f}% (audit metric only -- Dataset C is not the Quality corpus)")

    section("DATASET A / B / C COMPARISON (Section 22)")
    config_a, events_a, scenario_truth_a, impacts_a = _load(BASE_A)
    _, stats_a = _dataset_stats(BASE_A, config_a, events_a, impacts_a)
    config_b, events_b, scenario_truth_b, impacts_b = _load(BASE_B)
    _, stats_b = _dataset_stats(BASE_B, config_b, events_b, impacts_b)
    _, stats_c = _dataset_stats(BASE_C, config, events, impacts)

    def family_diversity(scenario_truth):
        fams = scenario_truth[scenario_truth.family != "RANDOM_QUALITY_EVENT"].family.nunique()
        return fams

    comparison = pd.DataFrame({
        "Dataset A (naturalistic)": {
            "Flow positives": stats_a["pos"], "positive shifts": stats_a["pos_shifts"],
            "impact events": stats_a["events"], "largest station share": f"{stats_a['station_share']*100:.1f}%",
            "largest shift share": f"{stats_a['shift_share']*100:.1f}%",
            "known scenario-family diversity": family_diversity(scenario_truth_a),
            "QC defect rate": f"{stats_a['rate']*100:.3f}%",
        },
        "Dataset B (coverage exp.)": {
            "Flow positives": stats_b["pos"], "positive shifts": stats_b["pos_shifts"],
            "impact events": stats_b["events"], "largest station share": f"{stats_b['station_share']*100:.1f}%",
            "largest shift share": f"{stats_b['shift_share']*100:.1f}%",
            "known scenario-family diversity": family_diversity(scenario_truth_b),
            "QC defect rate": f"{stats_b['rate']*100:.3f}%",
        },
        "Dataset C (calibrated)": {
            "Flow positives": stats_c["pos"], "positive shifts": stats_c["pos_shifts"],
            "impact events": stats_c["events"], "largest station share": f"{stats_c['station_share']*100:.1f}%",
            "largest shift share": f"{stats_c['shift_share']*100:.1f}%",
            "known scenario-family diversity": family_diversity(scenario_truth),
            "QC defect rate": f"{rate_c*100:.3f}%",
        },
    })
    print(comparison)
    print("\nA = naturalistic audit corpus. B = first coverage-balanced experiment (superseded for "
          "modeling purposes, kept as evidence). C = mechanistically calibrated Flow-modeling "
          "candidate corpus. Neither B nor C's scenario prevalence represents real production "
          "occurrence rates.")

    all_pass = train_ok and val_ok and test_ok
    print(f"\n{'='*90}\nOVERALL GATE: {'PASS' if all_pass else 'FAIL'}\n{'='*90}")
    return all_pass


if __name__ == "__main__":
    passed = main()
    sys.exit(0 if passed else 1)
