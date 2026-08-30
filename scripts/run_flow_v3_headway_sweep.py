"""Run the Phase-B healthy nominal-arrival headway sweep."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.loader import load_factory_config
from backend.flow_v3.headway_sweep import aggregate_runs, measure_healthy_run
from backend.simulation.engine import run_simulation

HEADWAYS = [115.0, 112.5, 110.0, 107.5, 105.0, 102.5, 100.0]
SEEDS = [31001, 31002, 31003, 31004, 31005]
N_VEHICLES = 450
INTERARRIVAL_STD_SECONDS = 15.0
OUT_DIR = ROOT / "artifacts" / "flow_v3"


def _render_selection(aggregates: list[dict]) -> str:
    lines = [
        "# Flow-v3 nominal headway selection",
        "",
        "## Sweep design",
        "",
        f"- Candidates: {', '.join(str(v) for v in HEADWAYS)} seconds",
        f"- Healthy independent seeds per candidate: {len(SEEDS)}",
        f"- Vehicles per run: {N_VEHICLES}",
        f"- Inter-arrival standard deviation: {INTERARRIVAL_STD_SECONDS:.1f} seconds",
        "- No scenarios, sensors, QC recalibration, cycle-time changes, buffer changes, labels, or ML metrics were used.",
        "",
        "## Aggregate results",
        "",
        "| Headway | Max rho | Headroom <65% | Moderate 65–75% | Sensitive 75–95% | Runs blocked | Mean blocked s | Max-buffer p95 queue | Event p95 queue | Steady throughput/h | Headway CV |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregates:
        lines.append(
            f"| {row['headway_seconds']:.1f} | {row['physical_rho_max']:.3f} | "
            f"{int(row['physical_headroom_station_count_lt_65pct'])} | "
            f"{int(row['physical_moderate_station_count_65_75pct'])} | "
            f"{int(row['physical_sensitive_station_count_75_95pct'])} | "
            f"{int(row['healthy_runs_with_any_blocking'])}/{int(row['run_count'])} | "
            f"{row['mean_total_blocked_seconds']:.1f} | "
            f"{row['mean_max_single_buffer_p95_occupancy_ratio_time_weighted']:.3f} | "
            f"{row['mean_p95_buffer_occupancy_ratio_at_state_changes']:.3f} | "
            f"{row['mean_throughput_vehicles_per_hour_steady']:.2f} | "
            f"{row['mean_completion_headway_cv_steady']:.3f} |"
        )

    stable = [
        row for row in aggregates
        if row["healthy_runs_with_any_blocking"] == 0
        and row["physical_overloaded_station_count_ge_95pct"] == 0
    ]
    preferred_shape = [
        row for row in stable
        if 6 <= row["physical_sensitive_station_count_75_95pct"] <= 10
        and 10 <= row["physical_moderate_station_count_65_75pct"] <= 12
    ]
    lines.extend(["", "## Decision", ""])
    if preferred_shape:
        selected = min(preferred_shape, key=lambda row: row["headway_seconds"])
        lines.append(
            f"Selected `{selected['headway_seconds']:.1f}` seconds: it is healthy-stable and meets the declared load-shape criteria."
        )
    else:
        best = max(stable, key=lambda row: row["physical_sensitive_station_count_75_95pct"], default=None)
        if best is None:
            lines.append("No candidate passed the healthy-stability gate. No headway is selected.")
        else:
            lines.append(
                f"No candidate produces the preferred 6–10 sensitive and 10–12 moderate stations without further design work. "
                f"The strongest stable candidate is `{best['headway_seconds']:.1f}` seconds, with "
                f"{int(best['physical_sensitive_station_count_75_95pct'])} sensitive and "
                f"{int(best['physical_moderate_station_count_65_75pct'])} moderate stations. "
                "It is retained as the reference for a small, selective, process-realistic cycle-time review; it is not yet frozen as the final nominal operating point."
            )
    lines.extend([
        "",
        "The decision is based only on line physics and healthy-run stability. No label prevalence or model result was available or consulted.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    config = load_factory_config(ROOT / "configs" / "station_types.yaml", ROOT / "configs" / "full_line.yaml")
    run_rows = []
    for headway in HEADWAYS:
        for seed in SEEDS:
            result = run_simulation(
                config,
                n_vehicles=N_VEHICLES,
                seed=seed,
                mean_interarrival_seconds=headway,
                std_interarrival_seconds=INTERARRIVAL_STD_SECONDS,
            )
            row = measure_healthy_run(result, config, headway_seconds=headway, seed=seed)
            run_rows.append(row)
            print(
                f"headway={headway:5.1f}s seed={seed} blocked={row['blocked_episode_count']:4d} "
                f"p95q={row['p95_buffer_occupancy_ratio_time_weighted']:.2f} "
                f"steady_tp={row['throughput_vehicles_per_hour_steady']:.2f}/h"
            )

    aggregates = aggregate_runs(run_rows)
    all_rows = run_rows + aggregates
    fieldnames = []
    for row in all_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "headway_sweep.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    (OUT_DIR / "headway_selection.md").write_text(_render_selection(aggregates), encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'headway_sweep.csv'}")
    print(f"Wrote {OUT_DIR / 'headway_selection.md'}")


if __name__ == "__main__":
    main()
