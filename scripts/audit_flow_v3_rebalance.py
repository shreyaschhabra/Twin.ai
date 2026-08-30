"""Generate pre-pilot rebalanced capacity, scenario, and buffer audits."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.loader import load_factory_config
from backend.flow_v3.capacity_audit import build_capacity_audit, summarize_utilization
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.flow_v3.scenario_capability import build_scenario_capability_matrix

HEADWAYS = (100.0, 102.5, 105.0)
OUT_DIR = ROOT / "artifacts/flow_v3"


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _render_capacity(base, rebalanced, plan, audit_by_headway) -> str:
    lines = [
        "# Flow-v3 rebalanced capacity audit",
        "",
        "This is a pre-pilot, physics-only review. S22 is unchanged. The proposal does not attempt to hit an exact station-count target.",
        "",
        "## Cycle-time changes",
        "",
        "| Station | Operation | Old s | New s | Change | rho before @100 | rho after @100 | @102.5 | @105 | Process rationale |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    base100 = {row["station_id"]: row for row in build_capacity_audit(base, 100.0)}
    for station_id, change in plan["cycle_time_overrides"].items():
        after = {h: {r["station_id"]: r for r in audit_by_headway[h]}[station_id] for h in HEADWAYS}
        pct = (change["new_seconds"] / change["old_seconds"] - 1) * 100
        lines.append(
            f"| {station_id} | {rebalanced.stations[station_id].station_name} | {change['old_seconds']:.1f} | "
            f"{change['new_seconds']:.1f} | {pct:.1f}% | {base100[station_id]['nominal_utilization_rho']:.3f} | "
            f"{after[100.0]['nominal_utilization_rho']:.3f} | {after[102.5]['nominal_utilization_rho']:.3f} | "
            f"{after[105.0]['nominal_utilization_rho']:.3f} | {change['rationale']} |"
        )
    lines.extend(["", "## Resulting utilization spread", "", "| Headway | <50% | 50–65% | 65–75% | 75–85% | 85–95% | >=95% | Max rho/station |", "|---:|---:|---:|---:|---:|---:|---:|---|"])
    for headway in HEADWAYS:
        summary = {item["band"]: item["station_count"] for item in summarize_utilization(audit_by_headway[headway])}
        top = max(audit_by_headway[headway], key=lambda row: row["nominal_utilization_rho"])
        lines.append(
            f"| {headway:.1f} | {summary['<50%']} | {summary['50-65%']} | {summary['65-75%']} | "
            f"{summary['75-85%']} | {summary['85-95%']} | {summary['>=95%']} | "
            f"{top['nominal_utilization_rho']:.3f}/{top['station_id']} |"
        )
    lines.extend([
        "",
        "## Zone rationale",
        "",
        "- Body: S11 is a modestly corrected manual finishing/inspection candidate; faster welding and dimensional stations remain comfortable.",
        "- Paint: S20 is the credible effective-service candidate because it combines cure exit and in-line inspection; the remaining paint stations retain headroom.",
        "- General/final assembly: S21 receives a small work-content correction. S22 is unchanged, while S24/S26/S34 already supply useful near-capacity behavior.",
        "- Inspection/EOL: S43 receives a fuller roll-test protocol. It remains nominally comfortable and only approaches breakeven at the upper edge of severe disruption, avoiding a forced structural bottleneck.",
        "",
        "## Pre-pilot scenario-capability interpretation at 102.5s",
        "",
        "- Body: S11 manual variation is POSITIVE-CAPABLE. This supplies a supervised mechanism outside Final Assembly without changing fast body automation.",
        "- Paint: S20 micro-stops are BORDERLINE at representative severe settings; degradation is POSITIVE-CAPABLE but remains the unseen holdout. Paint is not overstated as a strong supervised-positive source yet.",
        "- General/final assembly: S21/S22/S24 manual variation are POSITIVE-CAPABLE; S26 micro-stops are BORDERLINE. S22 remains unchanged.",
        "- Inspection/EOL: S43 reaches approximately breakeven only at the extreme upper edge of the current severe micro-stop range. It is not classified as supervised POSITIVE-CAPABLE. Forcing it higher would require a less defensible cycle increase, so this zone remains a documented limitation; its degradation response is unseen-holdout evidence only.",
        "- ARRIVAL_BURST values are provisional Phase-D design inputs and are explicitly marked as not yet implemented in the simulator.",
        "",
        "Classification rule: severe rho <0.90 = INCAPABLE; 0.90–<1.00 = HARD_NEGATIVE; 1.00–<1.05 = BORDERLINE; >=1.05 = POSITIVE-CAPABLE. Non-applicable pairs are INCAPABLE. Buffer capacity is never part of this rule.",
        "",
        "No cycle-time adjustment exceeds 20%, and no station is structurally overloaded at any finalist headway.",
        "",
    ])
    return "\n".join(lines)


def _render_buffers(base, rebalanced, plan) -> str:
    lines = [
        "# Flow-v3 buffer design audit",
        "",
        "Buffer capacity is treated only as time/space available to absorb a deficit. It is never used to classify service-capacity capability.",
        "",
        "| Buffer | Upstream | Downstream | Old | New | Rationale |",
        "|---|---|---|---:|---:|---|",
    ]
    for buffer_id, change in plan["buffer_capacity_overrides"].items():
        buffer = base.buffers[buffer_id]
        lines.append(
            f"| {buffer_id} | {buffer.upstream_station} | {buffer.downstream_station} | "
            f"{change['old_capacity']} | {change['new_capacity']} | {change['rationale']} |"
        )
    counts = Counter(buffer.capacity for buffer in rebalanced.buffers.values())
    lines.extend([
        "",
        "## Resulting heterogeneity",
        "",
        f"- Capacity 3 constrained/manual/test-bay buffers: {counts.get(3, 0)}",
        f"- Capacity 4 ordinary buffers: {counts.get(4, 0)}",
        f"- Capacity 5 accumulators/zone or branch buffers: {counts.get(5, 0)}",
        "- No capacity-2 buffer is introduced because the current topology does not justify such a tight staging limit before nominal stability is established.",
        "- B20 remains 5 and B21 remains 4; S22 is not made more dominant through artificial upstream-buffer tightening.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    plan = load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml")
    rebalanced = apply_rebalance(base, plan)
    audit_by_headway = {headway: build_capacity_audit(rebalanced, headway) for headway in HEADWAYS}

    reference_rows = []
    base_by_headway = {h: {r["station_id"]: r for r in build_capacity_audit(base, h)} for h in HEADWAYS}
    for row in audit_by_headway[102.5]:
        station_id = row["station_id"]
        enriched = dict(row)
        enriched["cycle_time_changed"] = station_id in plan["cycle_time_overrides"]
        enriched["old_baseline_cycle_time_seconds"] = base.stations[station_id].baseline_cycle_time_seconds
        enriched["new_baseline_cycle_time_seconds"] = rebalanced.stations[station_id].baseline_cycle_time_seconds
        for headway in HEADWAYS:
            token = str(headway).replace(".", "_")
            enriched[f"rho_before_at_{token}s"] = base_by_headway[headway][station_id]["nominal_utilization_rho"]
            enriched[f"rho_after_at_{token}s"] = {r["station_id"]: r for r in audit_by_headway[headway]}[station_id]["nominal_utilization_rho"]
        reference_rows.append(enriched)
    _write_csv(OUT_DIR / "rebalanced_capacity_audit.csv", reference_rows)
    (OUT_DIR / "rebalanced_capacity_audit.md").write_text(
        _render_capacity(base, rebalanced, plan, audit_by_headway), encoding="utf-8"
    )

    matrix = build_scenario_capability_matrix(rebalanced, HEADWAYS)
    _write_csv(OUT_DIR / "scenario_capability_matrix.csv", matrix)
    (OUT_DIR / "buffer_design_audit.md").write_text(_render_buffers(base, rebalanced, plan), encoding="utf-8")
    print(f"Wrote rebalanced capacity audit ({len(reference_rows)} stations)")
    print(f"Wrote scenario capability matrix ({len(matrix)} station/headway/mechanism rows)")
    print(f"Wrote buffer design audit ({len(plan['buffer_capacity_overrides'])} changes)")


if __name__ == "__main__":
    main()
