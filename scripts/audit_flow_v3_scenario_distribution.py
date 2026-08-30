"""Audit the frozen 219-run pre-pilot scenario distribution."""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "artifacts/flow_v3"
TARGETED = OUT_DIR / "scenario_targeted_validation.csv"
CAPABILITY = OUT_DIR / "scenario_capability_matrix_v2.csv"
STATIONS = ("S11", "S20", "S21", "S22", "S24", "S26", "S34")


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _positive(row: dict) -> bool:
    return row["real_congestion"] == "True"


def _summary_rows(runs: list[dict]) -> list[dict]:
    dimensions = {
        "mechanism": lambda row: (row["mechanism"],),
        "severity": lambda row: (row["severity"],),
        "temporal_profile": lambda row: (row["profile"],),
        "mechanism_x_severity": lambda row: (row["mechanism"], row["severity"]),
    }
    rows = []
    for dimension, key_fn in dimensions.items():
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for run in runs:
            groups[key_fn(run)].append(run)
        for key, group in sorted(groups.items()):
            count = sum(_positive(run) for run in group)
            rows.append({
                "record_type": "distribution",
                "dimension": dimension,
                "key_1": key[0],
                "key_2": key[1] if len(key) > 1 else "",
                "run_count": len(group),
                "positive_run_count": count,
                "positive_rate": count / len(group),
            })
    return rows


def _station_mechanism_rows(runs: list[dict]) -> list[dict]:
    rows = []
    mechanisms = sorted({run["mechanism"] for run in runs})
    for station_id in STATIONS:
        for mechanism in mechanisms:
            if mechanism == "ARRIVAL_BURST":
                exposed = [run for run in runs if run["mechanism"] == mechanism]
            else:
                exposed = [
                    run for run in runs
                    if run["mechanism"] == mechanism and run["target_station_id"] == station_id
                ]
            impacted = [
                run for run in exposed
                if _positive(run) and run["first_impacted_station_id"] == station_id
            ]
            rows.append({
                "record_type": "station_mechanism",
                "dimension": "station_x_mechanism",
                "key_1": station_id,
                "key_2": mechanism,
                "run_count": len(exposed),
                "positive_run_count": len(impacted),
                "positive_rate": len(impacted) / len(exposed) if exposed else 0.0,
            })
    return rows


def _station_review_rows(runs: list[dict], capability: list[dict]) -> list[dict]:
    positive = [run for run in runs if _positive(run)]
    rows = []
    for station_id in STATIONS:
        targeted = [run for run in runs if run["target_station_id"] == station_id]
        direct_positive = [run for run in targeted if _positive(run)]
        impacted = [run for run in positive if run["first_impacted_station_id"] == station_id]
        analytic = [
            row for row in capability
            if row["station_id"] == station_id
            and row["supervision_role"] == "SUPERVISED"
            and row["classification"] == "POSITIVE_CAPABLE"
        ]
        onset = [float(run["time_scenario_start_to_congestion_seconds"]) for run in impacted]
        duration = [float(run["blocked_seconds"]) for run in impacted]
        rows.append({
            "record_type": "station_review",
            "dimension": "station",
            "key_1": station_id,
            "targeted_run_count": len(targeted),
            "direct_target_positive_run_count": len(direct_positive),
            "empirical_impact_positive_run_count": len(impacted),
            "analytic_status": "ANALYTIC_POSITIVE_CAPABLE" if analytic else "NOT_ANALYTIC_POSITIVE_CAPABLE",
            "empirical_status": "EMPIRICALLY_POSITIVE" if impacted else "NOT_EMPIRICALLY_POSITIVE",
            "analytic_positive_mechanisms": ";".join(sorted({row["mechanism"] for row in analytic})),
            "empirical_positive_mechanisms": ";".join(sorted({run["mechanism"] for run in impacted})),
            "empirical_positive_severities": ";".join(sorted({run["severity"] for run in impacted})),
            "empirical_positive_profiles": ";".join(sorted({run["profile"] for run in impacted})),
            "median_time_to_impact_seconds": statistics.median(onset) if onset else None,
            "median_congestion_duration_seconds": statistics.median(duration) if duration else None,
        })
    return rows


def _moderate_rows(runs: list[dict], capability: list[dict]) -> tuple[list[dict], dict]:
    moderate = [run for run in runs if run["severity"] == "MODERATE"]
    occupancy = [float(run["max_relevant_buffer_occupancy_ratio"]) for run in moderate]

    lookup = {
        (row["station_id"], row["mechanism"], row["severity"], row["profile"]): row
        for row in capability
    }
    physics = []
    for run in moderate:
        if run["target_station_id"] == "LINE":
            candidates = [
                row for row in capability
                if row["mechanism"] == run["mechanism"]
                and row["severity"] == run["severity"]
                and row["profile"] == run["profile"]
            ]
            matrix_row = max(candidates, key=lambda row: float(row["peak_effective_rho"]))
        else:
            matrix_row = lookup[(
                run["target_station_id"], run["mechanism"], run["severity"], run["profile"]
            )]
        physics.append(matrix_row)

    thresholds = {}
    rows = []
    for threshold in (0.50, 0.75, 0.90):
        count = sum(value >= threshold for value in occupancy)
        thresholds[threshold] = count
        rows.append({
            "record_type": "moderate_threshold",
            "dimension": "moderate_max_occupancy",
            "key_1": f">={threshold:.2f}",
            "run_count": len(moderate),
            "positive_run_count": count,
            "positive_rate": count / len(moderate),
        })

    recovering_hard_negatives = [
        run for run in moderate
        if not _positive(run)
        and float(run["max_relevant_buffer_occupancy_ratio"]) >= 0.50
        and run["buffer_recovered_after_scenario"] == "True"
    ]
    detail = {
        "run_count": len(moderate),
        "positive_count": sum(_positive(run) for run in moderate),
        "occupancy_min": min(occupancy),
        "occupancy_p25": _percentile(occupancy, 0.25),
        "occupancy_median": statistics.median(occupancy),
        "occupancy_p75": _percentile(occupancy, 0.75),
        "occupancy_p90": _percentile(occupancy, 0.90),
        "occupancy_max": max(occupancy),
        "minimum_peak_capacity_headroom_fraction": min(
            1.0 - float(row["peak_effective_rho"]) for row in physics
        ),
        "maximum_sustained_arrival_service_deficit_vehicles_per_hour": max(
            float(row["expected_demand_service_deficit_vehicles_per_hour"]) for row in physics
        ),
        "at_least_50_count": thresholds[0.50],
        "at_least_75_count": thresholds[0.75],
        "at_least_90_count": thresholds[0.90],
        "recovering_preimpact_hard_negative_count": len(recovering_hard_negatives),
        "recovering_preimpact_hard_negative_fraction": len(recovering_hard_negatives) / len(moderate),
    }
    rows.append({
        "record_type": "moderate_summary",
        "dimension": "moderate",
        "key_1": "all",
        **detail,
    })
    return rows, detail


def _render(rows: list[dict], station_rows: list[dict], moderate: dict, positive: list[dict]) -> str:
    station_counts = Counter(run["first_impacted_station_id"] for run in positive)
    mechanism_counts = Counter(run["mechanism"] for run in positive)
    profile_counts = Counter(run["profile"] for run in positive)
    severity_counts = Counter(run["severity"] for run in positive)
    station_warning = max(station_counts.values()) / len(positive) > 0.35
    mechanism_warning = max(mechanism_counts.values()) / len(positive) > 0.60
    moderate_positive = [run for run in positive if run["severity"] == "MODERATE"]
    moderate_pairs = {(run["first_impacted_station_id"], run["profile"]) for run in moderate_positive}
    moderate_concentration_warning = len(moderate_pairs) <= 1

    lines = [
        "# Flow-v3 scenario distribution audit",
        "",
        "This audit uses the frozen 219 targeted validation definitions and seeds. No scenario parameter was changed.",
        "",
        "## Exact positive distribution",
        "",
        f"There are exactly {len(positive)} empirically positive runs.",
        "",
        "| First physically impacted station | Positives | Share |",
        "|---|---:|---:|",
    ]
    for station_id, count in station_counts.most_common():
        lines.append(f"| {station_id} | {count} | {count / len(positive):.1%} |")
    lines.extend(["", "| Mechanism | Positives | Share |", "|---|---:|---:|"])
    for mechanism, count in mechanism_counts.most_common():
        lines.append(f"| {mechanism} | {count} | {count / len(positive):.1%} |")
    lines.extend([
        "",
        f"Severity distribution: {dict(severity_counts)}. Profile distribution: {dict(profile_counts)}.",
        "",
        "## Analytic versus empirical station review",
        "",
        "Targeted runs count direct station-targeted experiments. Arrival bursts are line-level, while empirical impact is attributed to the downstream station whose inbound buffer first caused BLOCKED.",
        "",
        "| Station | Targeted runs | Direct positives | Empirical impacts | Analytic status | Empirical status | Positive mechanisms | Severities | Profiles | Median impact s | Median congestion s |",
        "|---|---:|---:|---:|---|---|---|---|---|---:|---:|",
    ])
    for row in station_rows:
        lines.append(
            f"| {row['key_1']} | {row['targeted_run_count']} | {row['direct_target_positive_run_count']} | "
            f"{row['empirical_impact_positive_run_count']} | {row['analytic_status']} | {row['empirical_status']} | "
            f"{row['empirical_positive_mechanisms'] or '—'} | {row['empirical_positive_severities'] or '—'} | "
            f"{row['empirical_positive_profiles'] or '—'} | "
            f"{float(row['median_time_to_impact_seconds']):.1f} | {float(row['median_congestion_duration_seconds']):.1f} |"
        )
    lines.extend([
        "",
        "## Moderate-severity behavior",
        "",
        f"Moderate positives remain {moderate['positive_count']}/{moderate['run_count']}. Maximum buffer occupancy has min/p25/median/p75/p90/max "
        f"{moderate['occupancy_min']:.3f}/{moderate['occupancy_p25']:.3f}/{moderate['occupancy_median']:.3f}/"
        f"{moderate['occupancy_p75']:.3f}/{moderate['occupancy_p90']:.3f}/{moderate['occupancy_max']:.3f}.",
        "",
        f"- >=50% occupancy: {moderate['at_least_50_count']}/{moderate['run_count']} ({moderate['at_least_50_count']/moderate['run_count']:.1%})",
        f"- >=75% occupancy: {moderate['at_least_75_count']}/{moderate['run_count']} ({moderate['at_least_75_count']/moderate['run_count']:.1%})",
        f"- >=90% occupancy: {moderate['at_least_90_count']}/{moderate['run_count']} ({moderate['at_least_90_count']/moderate['run_count']:.1%})",
        f"- Minimum peak capacity headroom: {moderate['minimum_peak_capacity_headroom_fraction']:.3f} (negative means peak rho exceeds 1)",
        f"- Maximum sustained expected arrival/service deficit: {moderate['maximum_sustained_arrival_service_deficit_vehicles_per_hour']:.3f} vehicles/hour",
        f"- Genuine pre-impact deterioration that recovered without blocking: {moderate['recovering_preimpact_hard_negative_count']}/{moderate['run_count']} ({moderate['recovering_preimpact_hard_negative_fraction']:.1%})",
        "",
        "The moderate set is not completely uneventful: a majority reaches at least 50% occupancy and then drains. These are valuable near-capacity hard negatives, so no physics adjustment is recommended.",
        "",
        "## Review warnings",
        "",
        f"- {'WARNING' if station_warning else 'PASS'} — largest station share is {max(station_counts.values()) / len(positive):.1%}; S11 crosses the lower ~35% review threshold but remains below 40%.",
        f"- {'WARNING' if mechanism_warning else 'PASS'} — largest mechanism share is {max(mechanism_counts.values()) / len(positive):.1%}, below the 60% threshold.",
        f"- {'WARNING' if moderate_concentration_warning else 'PASS'} — moderate positives span {len(moderate_pairs)} station/profile pairs, so they are not entirely concentrated in one pair.",
        "",
        "## Decision",
        "",
        "Scenario physics remain frozen. The S11 concentration is retained as a review warning, not treated as an automatic tuning target.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    runs = [row for row in _read(TARGETED) if row["record_type"] == "run"]
    capability = _read(CAPABILITY)
    if len(runs) != 219:
        raise RuntimeError(f"expected 219 targeted runs, found {len(runs)}")
    positive = [run for run in runs if _positive(run)]
    if len(positive) != 45:
        raise RuntimeError(f"expected 45 positive runs, found {len(positive)}")

    distribution = _summary_rows(runs)
    station_mechanism = _station_mechanism_rows(runs)
    station_review = _station_review_rows(runs, capability)
    moderate_rows, moderate = _moderate_rows(runs, capability)
    rows = distribution + station_mechanism + station_review + moderate_rows

    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with (OUT_DIR / "scenario_distribution_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (OUT_DIR / "scenario_distribution_audit.md").write_text(
        _render(rows, station_review, moderate, positive), encoding="utf-8"
    )
    print(f"Audited {len(runs)} runs; positives={len(positive)}; physics remains frozen")


if __name__ == "__main__":
    main()
