"""
Step 3 development demonstrations: one healthy baseline plus one run per
scenario family (isolated), all same seed/config for direct comparability.

Observable data (events, genealogy) and latent data (scenario truth,
quality exposure) are written to physically separate directories —
data/generated/scenario_demos/ vs data/generated/latent/ — and the latent
files are never meant to be treated as an ML feature source; they exist
for debugging/evaluation only.

Usage:
    python scripts/run_scenario_demos.py
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.simulation.engine import run_simulation
from backend.simulation.scenarios.config import load_scenarios
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
OBSERVABLE_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "scenario_demos"
LATENT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "latent"

SEED = 42
N_VEHICLES = 60

RUNS = [
    ("01_healthy_baseline", None),
    ("02_equipment_degradation", "equipment_degradation_demo"),
    ("03_micro_stops", "micro_stops_demo"),
    ("04_vehicle_mix_overload", "vehicle_mix_overload_demo"),
    ("05_bad_batch", "bad_batch_demo"),
    ("06_environmental_drift", "environmental_drift_demo"),
    ("07_sensor_dropout", "sensor_dropout_demo"),
    ("08_manual_variation", "manual_variation_demo"),
    ("09_random_quality_event", "random_quality_event_demo"),
]


def main():
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml")
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models.yaml")
    all_scenarios = {s.scenario_id: s for s in load_scenarios(CONFIG_DIR / "development_scenarios.yaml")}

    OBSERVABLE_DIR.mkdir(parents=True, exist_ok=True)
    LATENT_DIR.mkdir(parents=True, exist_ok=True)

    baseline_summary = None
    for name, scenario_id in RUNS:
        scenarios = [all_scenarios[scenario_id]] if scenario_id else []
        result = run_simulation(
            config, n_vehicles=N_VEHICLES, seed=SEED,
            sensor_models=sensor_models, scenarios=scenarios,
        )

        events_df = pd.DataFrame([e.__dict__ for e in result.events])
        events_df.to_parquet(OBSERVABLE_DIR / f"{name}_events.parquet", index=False)

        genealogy_rows = []
        for vehicle_id, visits in result.genealogy.items():
            vehicle = result.vehicles[vehicle_id]
            for visit in visits:
                genealogy_rows.append({"vehicle_id": vehicle_id, "variant_id": vehicle.variant_id, **asdict(visit)})
        pd.DataFrame(genealogy_rows).to_parquet(OBSERVABLE_DIR / f"{name}_genealogy.parquet", index=False)

        scenario_truth_rows = []
        for r in result.latent_truth.scenario_truth:
            row = asdict(r)
            row["params"] = json.dumps(row["params"])  # struct-of-dict is not portable to parquet
            row["station_ids"] = json.dumps(row["station_ids"])
            scenario_truth_rows.append(row)
        scenario_truth_df = pd.DataFrame(scenario_truth_rows)
        scenario_truth_df.to_parquet(LATENT_DIR / f"{name}_scenario_truth.parquet", index=False)
        exposure_df = pd.DataFrame([asdict(r) for r in result.latent_truth.quality_exposure])
        exposure_df.to_parquet(LATENT_DIR / f"{name}_quality_exposure.parquet", index=False)

        sensor_count = sum(1 for e in result.events if e.event_type == "SENSOR_READING")
        total_exposure = sum(result.latent_truth.total_exposure_by_vehicle().values())
        print(f"{name:<28} events={len(result.events):>5}  sensors={sensor_count:>5}  "
              f"completed={result.summary['vehicles_completed']:>3}/{result.summary['vehicles_generated']:<3}  "
              f"total_latent_exposure={total_exposure:.3f}")

        if scenario_id is None:
            baseline_summary = result.summary

    print("\nBaseline throughput:", f"{baseline_summary['throughput_vehicles_per_hour']:.2f} veh/hr")
    print(f"Observable data -> {OBSERVABLE_DIR}")
    print(f"Latent data (never an ML feature source) -> {LATENT_DIR}")


if __name__ == "__main__":
    main()
