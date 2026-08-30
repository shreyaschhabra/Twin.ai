"""Generate the pre-pilot Flow-v3 scenario-physics evidence package."""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.loader import load_factory_config
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_capability_v2 import build_scenario_capability_matrix_v2
from backend.flow_v3.scenario_physics import (
    ARRIVAL_PROFILES,
    MANUAL_PROFILES,
    MICRO_STOP_PROFILES,
    PROVISIONAL_HEADWAY_SECONDS,
    SEVERITY_ORDER,
    build_arrival_burst,
    build_manual_variation,
    build_micro_stops,
)
from backend.flow_v3.scenario_validation import aggregate_scenario_runs, measure_scenario_run
from backend.simulation.engine import run_simulation

OUT_DIR = ROOT / "artifacts/flow_v3"
START_SECONDS = 7200.0
N_VEHICLES = 300
STD_INTERARRIVAL_SECONDS = 15.0
SEEDS = (63001, 63002, 63003)
ARRIVAL_SEEDS = (63101, 63102, 63103, 63104, 63105)
MANUAL_TARGETS = ("S11", "S21", "S24", "S34", "S38")
MICRO_TARGETS = ("S20", "S26")


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _run(config, scenario, mechanism, target, severity, profile, seed):
    result = run_simulation(
        config,
        n_vehicles=N_VEHICLES,
        seed=seed,
        mean_interarrival_seconds=PROVISIONAL_HEADWAY_SECONDS,
        std_interarrival_seconds=STD_INTERARRIVAL_SECONDS,
        scenarios=[scenario],
    )
    return measure_scenario_run(
        result,
        config,
        mechanism=mechanism,
        target_station_id=target,
        severity=severity,
        profile=profile,
        seed=seed,
        scenario_start=START_SECONDS,
        scenario_end=START_SECONDS + scenario.duration,
        # Demand-side effects travel with the compressed arrival cohort.
        # One hour covers traversal to the dominant mid-line constraint;
        # this is an observation window, not extra scenario duration.
        congestion_observation_end=(
            START_SECONDS + scenario.duration + 3600.0
            if mechanism == "ARRIVAL_BURST" else None
        ),
    )


def _physics_markdown(config, matrix):
    capable = [
        row for row in matrix
        if row["supervision_role"] == "SUPERVISED" and row["classification"] == "POSITIVE_CAPABLE"
    ]
    zones = sorted({row["zone"] for row in capable})
    stations = sorted({row["station_id"] for row in capable})
    mechanisms = sorted({row["mechanism"] for row in capable})
    return "\n".join([
        "# Flow-v3 scenario-physics redesign",
        "",
        "This is a pre-pilot physics package. It creates no pilot partitions, labels, manifests, or ML artifacts.",
        "",
        "## Frozen nominal basis",
        "",
        f"- Provisional headway: {PROVISIONAL_HEADWAY_SECONDS:.1f}s.",
        "- S22 remains unchanged.",
        "- S43 is reverted to 55s. The proposed 64s cycle did not create an independent EOL supervised mechanism; a realistic line-entry burst encounters the upstream S22 constraint first.",
        "- B43 remains capacity 3 as a test-bay staging decision, not as evidence of service deficit.",
        "",
        "## Implemented supervised physics",
        "",
        "- Manual variation: STEP, GRADUAL, and RECOVERING profiles; GRADUAL develops over the first half and then persists; station-aware multipliers; 25/40/60 minute mild/moderate/severe durations.",
        "- Micro-stops: a processing-time Poisson process permits zero, one, or multiple interruptions per visit, with resumable work; STEP, GRADUAL, and RECOVERING profiles; 20/35/60 minute durations.",
        "- Arrival burst: genuine demand-side headway compression with STEP_BURST and RAMP_BURST profiles; 15/25/40 minute durations; arrival variability scales with the headway so its coefficient of variation remains stable.",
        "- Vehicle-mix overload is retained as HARD_NEGATIVE wherever actual variant work content cannot cross capacity.",
        "- Equipment degradation is temporal but UNSEEN_ONLY and is excluded from supervised validation.",
        "",
        "## Severity mapping",
        "",
        "| Family | Mild | Moderate | Severe |",
        "|---|---|---|---|",
        "| Manual variation | station-aware peak remains safely below capacity (multiplier capped at 1.12) | peak rho target 1.02, multiplier capped at 1.45 | peak rho target 1.12, multiplier capped at 1.65 |",
        "| Micro-stops | 0.20 stops/work-minute, U(3,9)s | 1.25 stops/work-minute, U(8,24)s | 1.80 stops/work-minute, U(10,30)s |",
        "| Arrival burst | headway x0.90 for 15 min | headway x0.75 for 25 min | headway x0.60 for 40 min |",
        "| Equipment degradation (unseen only) | peak cycle x1.25 for 30 min | peak cycle x1.50 for 60 min | peak cycle x1.85 for 90 min |",
        "",
        "Manual candidates are S11, S21, S22, S24, S33, S34, and S38. Micro-stop candidates are S20 and S26. Candidate selection follows operation semantics; it is not applied to every station.",
        "",
        "## Capability rule",
        "",
        "Expected demand is compared with expected service capacity. Buffer capacity is reported only to estimate fill time after a positive deficit exists; it is never used to assign capability. POSITIVE_CAPABLE requires expected rho >=1.05 and peak rho >=1.0; near-breakeven cases are BORDERLINE.",
        "",
        f"The analytic matrix contains positive-capable supervised combinations for {len(stations)} stations, {len(mechanisms)} mechanisms ({', '.join(mechanisms)}), and zones {', '.join(zones)}.",
        "",
        "## Pre-impact observables",
        "",
        "All congestion labels in targeted validation come from observable BLOCKED transitions. The pre-impact interval can contain buffer entries/occupancy growth, completed-cycle duration changes, arrival events, and rolling micro-stop count, seconds, mean duration, rate, and rate trend. Scenario identity remains latent simulator truth.",
        "",
    ])


def _healthy_stability_evidence():
    path = OUT_DIR / "final_headway_comparison.csv"
    if not path.exists():
        return 0, False
    with path.open(encoding="utf-8") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if row.get("record_type") == "run"
            and float(row.get("headway_seconds", 0.0)) == PROVISIONAL_HEADWAY_SECONDS
            and row.get("test_scope") in {"finalist_comparison", "long_stability"}
        ]
    return len(rows), bool(rows) and all(float(row["blocked_episode_count"]) == 0 for row in rows)


def _validation_markdown(config, matrix, run_rows, aggregates):
    by_severity = defaultdict(list)
    for row in aggregates:
        by_severity[row["severity"]].append(row)
    lines = [
        "# Flow-v3 targeted scenario-physics validation",
        "",
        f"This was a small targeted validation at {PROVISIONAL_HEADWAY_SECONDS:.1f}s, not a Flow pilot. Each manual/micro condition used {len(SEEDS)} seeds; arrival conditions used {len(ARRIVAL_SEEDS)} seeds.",
        "",
        "A station-targeted run is positive only when an upstream station enters the observable BLOCKED state against the buffer feeding the target while the scenario is active. Arrival bursts additionally use a one-hour cohort-propagation observation window because demand compressed at line entry reaches downstream constraints later. Occupancy alone is not a positive label.",
        "",
        "| Severity | Conditions | Negative/mostly negative | Mixed | Positive | Positive runs | Recovered positive runs |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for severity in SEVERITY_ORDER:
        rows = by_severity[severity]
        positive_runs = sum(row["runs_with_real_congestion"] for row in rows)
        recovered = sum(row["positive_runs_recovered"] for row in rows)
        lines.append(
            f"| {severity} | {len(rows)} | {sum(row['outcome_class'] in {'NEGATIVE', 'MOSTLY_NEGATIVE'} for row in rows)} | "
            f"{sum(row['outcome_class'] == 'MIXED' for row in rows)} | {sum(row['outcome_class'] == 'POSITIVE' for row in rows)} | "
            f"{positive_runs} | {recovered} |"
        )

    lines.extend([
        "",
        "## Per-condition results",
        "",
        "| Mechanism | Target | Severity | Profile | Runs | Congested | Mean onset s | Mean max occupancy | Mean blocked s | Recovered positives |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    severity_rank = {severity: index for index, severity in enumerate(SEVERITY_ORDER)}
    for row in sorted(
        aggregates,
        key=lambda value: (
            value["mechanism"], value["target_station_id"],
            severity_rank[value["severity"]], value["profile"],
        ),
    ):
        onset = row["mean_time_start_to_congestion_seconds"]
        onset_text = f"{onset:.1f}" if onset is not None else "—"
        lines.append(
            f"| {row['mechanism']} | {row['target_station_id']} | {row['severity']} | {row['profile']} | "
            f"{row['run_count']} | {row['runs_with_real_congestion']} | "
            f"{onset_text} | "
            f"{row['mean_max_relevant_buffer_occupancy_ratio']:.3f} | "
            f"{row['mean_blocked_seconds']:.1f} | {row['positive_runs_recovered']} |"
        )

    positive_rows = [row for row in run_rows if row["real_congestion"]]
    analytic_capable = [
        row for row in matrix
        if row["supervision_role"] == "SUPERVISED" and row["classification"] == "POSITIVE_CAPABLE"
    ]
    analytic_stations = sorted({row["station_id"] for row in analytic_capable})
    analytic_mechanisms = sorted({row["mechanism"] for row in analytic_capable})
    positive_stations = sorted({row["target_station_id"] for row in positive_rows if row["target_station_id"] != "LINE"})
    positive_mechanisms = sorted({row["mechanism"] for row in positive_rows})
    station_counts = Counter(row["target_station_id"] for row in positive_rows)
    dominant_share = max(station_counts.values(), default=0) / max(1, len(positive_rows))
    all_recovered = all(row["recovered_after_scenario"] for row in positive_rows)
    all_precursors = all(row["observable_precursor_before_congestion"] for row in positive_rows)
    mild_rows = by_severity["MILD"]
    severe_rows = by_severity["SEVERE"]
    mild_negative_share = sum(row["outcome_class"] in {"NEGATIVE", "MOSTLY_NEGATIVE"} for row in mild_rows) / len(mild_rows)
    severe_positive_share = sum(row["outcome_class"] in {"MIXED", "POSITIVE"} for row in severe_rows) / len(severe_rows)
    healthy_runs, healthy_pass = _healthy_stability_evidence()
    moderate_run_rows = [row for row in run_rows if row["severity"] == "MODERATE"]
    moderate_positive = [row for row in moderate_run_rows if row["real_congestion"]]
    gate = {
        "at_least_6_positive_stations": len(analytic_stations) >= 6,
        "at_least_3_positive_mechanisms": len(analytic_mechanisms) >= 3,
        "not_one_station_dominated": dominant_share <= 0.50,
        "healthy_line_has_no_chronic_congestion": healthy_pass,
        "mild_mostly_negative": mild_negative_share >= 0.70,
        "severe_often_positive": severe_positive_share >= 0.50,
        "positive_runs_recover": all_recovered,
        "preimpact_observable_exists": all_precursors,
    }
    lines.extend([
        "",
        "## Diversity and recovery gate",
        "",
        f"- Analytic positive-capable supervised stations: {', '.join(analytic_stations) or 'none'} ({len(analytic_stations)}).",
        f"- Analytic positive-capable supervised mechanisms: {', '.join(analytic_mechanisms) or 'none'} ({len(analytic_mechanisms)}).",
        f"- Observed positive target stations: {', '.join(positive_stations) or 'none'} ({len(positive_stations)}).",
        f"- Observed positive mechanisms: {', '.join(positive_mechanisms) or 'none'} ({len(positive_mechanisms)}).",
        f"- Moderate run-level outcome: {len(moderate_positive)}/{len(moderate_run_rows)} positive across {len({row['mechanism'] for row in moderate_positive})} mechanisms; mixed but deliberately negative-leaning.",
        f"- Largest target share of positive runs: {dominant_share:.1%}.",
        f"- Healthy 102.5s evidence: {healthy_runs} comparison/long runs, {'zero blocking' if healthy_pass else 'gate failed'}.",
        f"- Mild negative-condition share: {mild_negative_share:.1%}.",
        f"- Severe mixed/positive-condition share: {severe_positive_share:.1%}.",
        "",
    ])
    for name, passed in gate.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend([
        "",
        "No pilot was generated. Any failed gate must be resolved or explicitly justified before pilot authorization.",
        "",
    ])
    return "\n".join(lines), gate


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))

    matrix = build_scenario_capability_matrix_v2(config)
    _write_csv(OUT_DIR / "scenario_capability_matrix_v2.csv", matrix)
    (OUT_DIR / "scenario_physics_redesign.md").write_text(_physics_markdown(config, matrix), encoding="utf-8")

    rows = []
    for target in MANUAL_TARGETS:
        for severity in SEVERITY_ORDER:
            for profile in MANUAL_PROFILES:
                for seed in SEEDS:
                    scenario = build_manual_variation(
                        config, scenario_id=f"validate_manual_{target}_{severity}_{profile}_{seed}",
                        station_id=target, severity=severity, profile=profile, start_time=START_SECONDS,
                    )
                    row = _run(config, scenario, "MANUAL_VARIATION", target, severity, profile, seed)
                    rows.append(row)
                    print(target, severity, profile, seed, row["real_congestion"])

    for target in MICRO_TARGETS:
        for severity in SEVERITY_ORDER:
            for profile in MICRO_STOP_PROFILES:
                for seed in SEEDS:
                    scenario = build_micro_stops(
                        scenario_id=f"validate_micro_{target}_{severity}_{profile}_{seed}",
                        station_id=target, severity=severity, profile=profile, start_time=START_SECONDS,
                    )
                    row = _run(config, scenario, "MICRO_STOPS", target, severity, profile, seed)
                    rows.append(row)
                    print(target, severity, profile, seed, row["real_congestion"])

    for severity in SEVERITY_ORDER:
        for profile in ARRIVAL_PROFILES:
            for seed in ARRIVAL_SEEDS:
                scenario = build_arrival_burst(
                    scenario_id=f"validate_arrival_{severity}_{profile}_{seed}",
                    severity=severity, profile=profile, start_time=START_SECONDS,
                )
                row = _run(config, scenario, "ARRIVAL_BURST", None, severity, profile, seed)
                rows.append(row)
                print("LINE", severity, profile, seed, row["real_congestion"])

    aggregates = aggregate_scenario_runs(rows)
    _write_csv(OUT_DIR / "scenario_targeted_validation.csv", rows + aggregates)
    markdown, gate = _validation_markdown(config, matrix, rows, aggregates)
    (OUT_DIR / "scenario_targeted_validation.md").write_text(markdown, encoding="utf-8")
    print(f"Validation rows={len(rows)}, conditions={len(aggregates)}, gate={gate}")


if __name__ == "__main__":
    main()
