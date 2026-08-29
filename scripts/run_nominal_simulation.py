"""
Step 2 nominal development run: a small, healthy mixed-model shift on the
12-station development line, used to sanity-check the simulator (not to
generate the eventual training dataset — that's a later step).

Usage:
    python scripts/run_nominal_simulation.py
"""

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.simulation.engine import run_simulation

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated"

N_VEHICLES = 80
SEED = 42
MEAN_INTERARRIVAL_SECONDS = 200.0
STD_INTERARRIVAL_SECONDS = 20.0
VARIANT_MIX = {"ICE_SEDAN": 0.45, "ICE_SUV": 0.35, "EV": 0.20}


def main():
    config = load_factory_config(
        CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml"
    )
    result = run_simulation(
        config,
        n_vehicles=N_VEHICLES,
        seed=SEED,
        mean_interarrival_seconds=MEAN_INTERARRIVAL_SECONDS,
        std_interarrival_seconds=STD_INTERARRIVAL_SECONDS,
        variant_mix=VARIANT_MIX,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_df = pd.DataFrame([e.__dict__ for e in result.events])
    events_df.to_parquet(OUTPUT_DIR / "step2_nominal_events.parquet", index=False)

    genealogy_rows = []
    for vehicle_id, visits in result.genealogy.items():
        vehicle = result.vehicles[vehicle_id]
        for visit in visits:
            row = {"vehicle_id": vehicle_id, "variant_id": vehicle.variant_id, **asdict(visit)}
            genealogy_rows.append(row)
    genealogy_df = pd.DataFrame(genealogy_rows)
    genealogy_df.to_parquet(OUTPUT_DIR / "step2_nominal_genealogy.parquet", index=False)

    print(f"Wrote {len(events_df)} events -> {OUTPUT_DIR / 'step2_nominal_events.parquet'}")
    print(f"Wrote {len(genealogy_df)} genealogy rows -> {OUTPUT_DIR / 'step2_nominal_genealogy.parquet'}")
    print()
    print_summary(result.summary, config)


def print_summary(summary: dict, config):
    print("=== NOMINAL RUN SANITY SUMMARY (Step 2, not final KPIs) ===\n")
    print(f"Vehicles generated:  {summary['vehicles_generated']}")
    print(f"Vehicles completed:  {summary['vehicles_completed']}")
    print(f"By variant:          {summary['vehicles_by_variant']}")
    print(f"Simulated duration:  {summary['simulated_duration_seconds']:.1f}s "
          f"({summary['simulated_duration_seconds']/3600:.2f} hours)")
    print(f"Throughput:          {summary['throughput_vehicles_per_hour']:.2f} vehicles/hour")
    print(f"Avg time in system:  {summary['avg_time_in_system_seconds']:.1f}s")
    print()
    print(f"{'Station':<6} {'Util%':>7} {'Proc#':>6} {'AvgProcT':>10} {'Blocked':>9} {'Starved':>9}")
    for sid in sorted(config.stations.keys()):
        util = summary["station_utilization"][sid] * 100
        count = summary["processing_counts_per_station"][sid]
        avg_t = summary["avg_processing_time_per_station"][sid]
        blocked = summary["blocked_time_per_station"][sid]
        starved = summary["starved_time_per_station"][sid]
        print(f"{sid:<6} {util:>6.1f}% {count:>6} {avg_t:>9.1f}s {blocked:>8.1f}s {starved:>8.1f}s")
    print()
    print("Max buffer occupancy:")
    for bid in sorted(config.buffers.keys()):
        cap = config.buffers[bid].capacity
        occ = summary["max_buffer_occupancy"][bid]
        print(f"  {bid}: {occ}/{cap}")


if __name__ == "__main__":
    main()
