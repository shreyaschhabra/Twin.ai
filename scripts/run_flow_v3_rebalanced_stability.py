"""Compare finalist headways on the rebalanced line and run long stability tests."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.loader import load_factory_config
from backend.flow_v3.headway_sweep import aggregate_runs, measure_healthy_run
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.simulation.engine import run_simulation

HEADWAYS = (100.0, 102.5, 105.0)
COMPARISON_SEEDS = tuple(range(42001, 42011))
LONG_SEEDS = (42901, 42902, 42903)
COMPARISON_VEHICLES = 600
LONG_VEHICLES = 2000
INTERARRIVAL_STD_SECONDS = 15.0
OUT_DIR = ROOT / "artifacts/flow_v3"


def _run(config, headway, seed, vehicles, scope):
    result = run_simulation(
        config,
        n_vehicles=vehicles,
        seed=seed,
        mean_interarrival_seconds=headway,
        std_interarrival_seconds=INTERARRIVAL_STD_SECONDS,
    )
    row = measure_healthy_run(result, config, headway_seconds=headway, seed=seed)
    row["test_scope"] = scope
    row["n_vehicles_requested"] = vehicles
    return row


def _select(aggregates):
    # Physics-only rule: no nominal blocking in any seed, no structural
    # overload, and max nominal rho <= 0.90 so unchanged S22 is not kept at
    # the very upper edge. Pick the most productive candidate satisfying it.
    eligible = [
        row for row in aggregates
        if row["healthy_runs_with_any_blocking"] == 0
        and row["physical_overloaded_station_count_ge_95pct"] == 0
        and row["physical_rho_max"] <= 0.90
    ]
    if not eligible:
        raise RuntimeError("no finalist headway passes the declared healthy-stability rule")
    return min(eligible, key=lambda row: row["headway_seconds"])


def _render(aggregates, selected, long_aggregate):
    lines = [
        "# Flow-v3 rebalanced healthy-line decision",
        "",
        "## Finalist comparison",
        "",
        f"Ten independent healthy seeds and {COMPARISON_VEHICLES} vehicles per seed were run after both cycle-time and buffer changes.",
        "",
        "| Headway | Runs blocked | Mean blocked s | Max rho/station | Mean occupancy | Busiest-buffer p95 | Mean max occupancy | Starved fraction | Steady throughput/h | Throughput std | Mean WIP |",
        "|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(aggregates, key=lambda value: value["headway_seconds"]):
        lines.append(
            f"| {row['headway_seconds']:.1f} | {int(row['healthy_runs_with_any_blocking'])}/{int(row['run_count'])} | "
            f"{row['mean_total_blocked_seconds']:.1f} | {row['physical_rho_max']:.3f}/{row['throughput_constraint_station_id']} | "
            f"{row['mean_mean_buffer_occupancy_ratio_time_weighted']:.4f} | "
            f"{row['mean_max_single_buffer_p95_occupancy_ratio_time_weighted']:.3f} | "
            f"{row['mean_max_buffer_occupancy_ratio']:.3f} | "
            f"{row['mean_starved_fraction_of_station_time']:.3f} | "
            f"{row['mean_throughput_vehicles_per_hour_steady']:.2f} | "
            f"{row['std_throughput_vehicles_per_hour_steady']:.2f} | "
            f"{row['mean_mean_line_wip_time_weighted']:.2f} |"
        )
    lines.extend([
        "",
        "## Selected nominal headway",
        "",
        f"Selected `{selected['headway_seconds']:.1f}` seconds. It is the fastest finalist with zero blocking in all comparison seeds, zero structural overload, and max nominal rho <=0.90. "
        "This keeps unchanged S22 below the aggressive upper edge while retaining stronger cross-zone disturbance sensitivity than 105s.",
        "",
        "## Longer healthy stability gate",
        "",
        f"Three additional independent runs of {LONG_VEHICLES} vehicles each were executed at the selected headway.",
        "",
        f"- Runs with blocking: {int(long_aggregate['healthy_runs_with_any_blocking'])}/{int(long_aggregate['run_count'])}",
        f"- Mean blocked seconds: {long_aggregate['mean_total_blocked_seconds']:.1f}",
        f"- Mean steady throughput: {long_aggregate['mean_throughput_vehicles_per_hour_steady']:.2f} vehicles/hour",
        f"- Throughput run-to-run standard deviation: {long_aggregate['std_throughput_vehicles_per_hour_steady']:.2f}",
        f"- Mean busiest-buffer p95 occupancy ratio: {long_aggregate['mean_max_single_buffer_p95_occupancy_ratio_time_weighted']:.3f}",
        f"- Mean maximum observed buffer occupancy ratio: {long_aggregate['mean_max_buffer_occupancy_ratio']:.3f}",
        f"- Mean starved fraction of station-time: {long_aggregate['mean_starved_fraction_of_station_time']:.3f}",
        f"- Mean line WIP: {long_aggregate['mean_mean_line_wip_time_weighted']:.2f}",
        f"- Physical throughput constraint: {long_aggregate['throughput_constraint_station_id']} at rho={long_aggregate['physical_rho_max']:.3f}",
        "",
        "No scenario pilot has been generated. This nominal-line decision is paused for review as required.",
        "",
    ])
    return "\n".join(lines)


def main():
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))
    comparison = []
    for headway in HEADWAYS:
        for seed in COMPARISON_SEEDS:
            row = _run(config, headway, seed, COMPARISON_VEHICLES, "finalist_comparison")
            comparison.append(row)
            print(f"compare h={headway:.1f} seed={seed} blocked={row['blocked_episode_count']} maxq={row['max_buffer_occupancy_ratio']:.2f}")
    aggregates = aggregate_runs(comparison)
    for row in aggregates:
        row["test_scope"] = "finalist_aggregate"
        row["n_vehicles_requested"] = COMPARISON_VEHICLES
    selected = _select(aggregates)

    long_rows = []
    for seed in LONG_SEEDS:
        row = _run(config, selected["headway_seconds"], seed, LONG_VEHICLES, "long_stability")
        long_rows.append(row)
        print(f"long h={selected['headway_seconds']:.1f} seed={seed} blocked={row['blocked_episode_count']} maxq={row['max_buffer_occupancy_ratio']:.2f}")
    long_aggregate = aggregate_runs(long_rows)[0]
    long_aggregate["test_scope"] = "long_stability_aggregate"
    long_aggregate["n_vehicles_requested"] = LONG_VEHICLES

    all_rows = comparison + aggregates + long_rows + [long_aggregate]
    for row in all_rows:
        row["selected_headway_seconds"] = selected["headway_seconds"]
    fields = []
    for row in all_rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "final_headway_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    (OUT_DIR / "rebalanced_headway_decision.md").write_text(
        _render(aggregates, selected, long_aggregate), encoding="utf-8"
    )
    print(f"Selected {selected['headway_seconds']:.1f}s; artifacts written to {OUT_DIR}")


if __name__ == "__main__":
    main()
