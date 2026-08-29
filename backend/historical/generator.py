"""
Development historical dataset generator (Step 4, Sections M, N, W, X).

Orchestrates many independent shift-level simulations on the full
45-station line, each with its own deterministic scenario schedule and
its own deterministic simulation seed (both derived from one dataset
master seed via the same isolated-stream mechanism as everything else —
see backend/simulation/rng.py), and assembles the results into a small
set of observable and latent tables, physically separated on disk.

The simulation engine itself has no notion of "shifts" — that concept
lives entirely here, one layer up, which is why vehicle IDs are
re-namespaced per shift only at export time (SHIFT_ID::V00001), not
inside the engine.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from backend.config.schemas import FactoryConfig
from backend.simulation.engine import RunResult, run_simulation
from backend.simulation.qc import QCParameters
from backend.simulation.rng import derive_seed
from backend.simulation.scenarios.config import ScenarioFamily
from backend.simulation.sensors import SensorModelRegistry
from backend.historical.shift_scheduler import build_shift_schedule

DEFAULT_VEHICLES_PER_SHIFT = 450
DEFAULT_MEAN_INTERARRIVAL_SECONDS = 115.0
DEFAULT_STD_INTERARRIVAL_SECONDS = 15.0
DEFAULT_VARIANT_MIX = {"ICE_SEDAN": 0.45, "ICE_SUV": 0.35, "EV": 0.20}
QC_STATION_ID = "S45"


@dataclass
class ShiftResult:
    shift_id: str
    shift_seed: int
    n_vehicles: int
    is_abnormal: bool
    scenario_ids: List[str]
    result: RunResult


def generate_development_dataset(
    config: FactoryConfig,
    sensor_models: SensorModelRegistry,
    batch_relevant_stations: Dict[str, int],
    n_shifts: int,
    dataset_master_seed: int,
    vehicles_per_shift: int = DEFAULT_VEHICLES_PER_SHIFT,
    mean_interarrival_seconds: float = DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    std_interarrival_seconds: float = DEFAULT_STD_INTERARRIVAL_SECONDS,
    variant_mix: Optional[Dict[str, float]] = None,
    qc_params: Optional[QCParameters] = None,
    held_out_family: Optional[ScenarioFamily] = None,
) -> List[ShiftResult]:
    variant_mix = variant_mix or DEFAULT_VARIANT_MIX
    qc_params = qc_params or QCParameters()
    shift_duration_estimate = vehicles_per_shift * mean_interarrival_seconds

    shift_results: List[ShiftResult] = []
    for i in range(1, n_shifts + 1):
        shift_id = f"SHIFT{i:03d}"
        shift_seed = derive_seed(dataset_master_seed, f"shift_sim::{shift_id}")

        plan = build_shift_schedule(
            dataset_master_seed=dataset_master_seed,
            shift_id=shift_id,
            shift_duration_seconds=shift_duration_estimate,
            mean_interarrival_seconds=mean_interarrival_seconds,
            held_out_family=held_out_family,
        )
        is_abnormal = any(s.family != ScenarioFamily.RANDOM_QUALITY_EVENT for s in plan.scenarios)

        result = run_simulation(
            config,
            n_vehicles=vehicles_per_shift,
            seed=shift_seed,
            mean_interarrival_seconds=mean_interarrival_seconds,
            std_interarrival_seconds=std_interarrival_seconds,
            variant_mix=variant_mix,
            sensor_models=sensor_models,
            scenarios=plan.scenarios,
            batch_relevant_stations=batch_relevant_stations,
            qc_station_id=QC_STATION_ID,
            qc_params=qc_params,
        )

        shift_results.append(ShiftResult(
            shift_id=shift_id,
            shift_seed=shift_seed,
            n_vehicles=vehicles_per_shift,
            is_abnormal=is_abnormal,
            scenario_ids=[s.scenario_id for s in plan.scenarios],
            result=result,
        ))

    return shift_results


def _global_vehicle_id(shift_id: str, local_vehicle_id: str) -> str:
    return f"{shift_id}::{local_vehicle_id}"


def write_dataset(
    shift_results: List[ShiftResult],
    observable_dir: Path,
    latent_dir: Path,
) -> Dict[str, int]:
    import pandas as pd

    observable_dir.mkdir(parents=True, exist_ok=True)
    latent_dir.mkdir(parents=True, exist_ok=True)

    event_rows, genealogy_rows, vehicle_rows, shift_rows = [], [], [], []
    scenario_truth_rows, exposure_rows, qc_generation_rows = [], [], []

    for sr in shift_results:
        result = sr.result
        for e in result.events:
            row = dict(e.__dict__)
            if row.get("vehicle_id"):
                row["vehicle_id"] = _global_vehicle_id(sr.shift_id, row["vehicle_id"])
            row["shift_id"] = sr.shift_id
            event_rows.append(row)

        for local_vid, visits in result.genealogy.items():
            gvid = _global_vehicle_id(sr.shift_id, local_vid)
            vehicle = result.vehicles[local_vid]
            for visit in visits:
                genealogy_rows.append({
                    "vehicle_id": gvid, "shift_id": sr.shift_id,
                    "variant_id": vehicle.variant_id, **asdict(visit),
                })

        for local_vid, vehicle in result.vehicles.items():
            vehicle_rows.append({
                "vehicle_id": _global_vehicle_id(sr.shift_id, local_vid),
                "shift_id": sr.shift_id,
                "variant_id": vehicle.variant_id,
                "created_at": vehicle.created_at,
                "completed": vehicle.completed,
                "completed_at": vehicle.completed_at,
            })

        shift_rows.append({
            "shift_id": sr.shift_id, "shift_seed": sr.shift_seed,
            "n_vehicles": sr.n_vehicles, "is_abnormal": sr.is_abnormal,
            "scenario_ids": json.dumps(sr.scenario_ids),
            "vehicles_completed": result.summary["vehicles_completed"],
            "throughput_vehicles_per_hour": result.summary["throughput_vehicles_per_hour"],
        })

        for rec in result.latent_truth.scenario_truth:
            row = asdict(rec)
            row["params"] = json.dumps(row["params"])
            row["station_ids"] = json.dumps(row["station_ids"])
            row["shift_id"] = sr.shift_id
            scenario_truth_rows.append(row)

        for rec in result.latent_truth.quality_exposure:
            row = asdict(rec)
            row["vehicle_id"] = _global_vehicle_id(sr.shift_id, row["vehicle_id"])
            row["shift_id"] = sr.shift_id
            exposure_rows.append(row)

        for rec in result.latent_truth.qc_generation:
            row = asdict(rec)
            row["vehicle_id"] = _global_vehicle_id(sr.shift_id, row["vehicle_id"])
            row["shift_id"] = sr.shift_id
            qc_generation_rows.append(row)

    events_df = pd.DataFrame(event_rows)
    events_df.to_parquet(observable_dir / "events.parquet", index=False)
    events_df[events_df.event_type == "SENSOR_READING"].to_parquet(
        observable_dir / "sensor_readings.parquet", index=False
    )
    events_df[events_df.event_type == "QC_RESULT_RECORDED"][
        ["vehicle_id", "shift_id", "vehicle_variant", "simulation_time", "qc_result"]
    ].to_parquet(observable_dir / "qc_results.parquet", index=False)

    pd.DataFrame(genealogy_rows).to_parquet(observable_dir / "genealogy.parquet", index=False)
    pd.DataFrame(vehicle_rows).to_parquet(observable_dir / "vehicles.parquet", index=False)
    pd.DataFrame(shift_rows).to_parquet(observable_dir / "shifts.parquet", index=False)

    pd.DataFrame(scenario_truth_rows).to_parquet(latent_dir / "scenario_truth.parquet", index=False)
    pd.DataFrame(exposure_rows).to_parquet(latent_dir / "quality_exposure.parquet", index=False)
    pd.DataFrame(qc_generation_rows).to_parquet(latent_dir / "generator_truth.parquet", index=False)

    return {
        "events": len(event_rows),
        "sensor_readings": int((events_df.event_type == "SENSOR_READING").sum()),
        "genealogy_rows": len(genealogy_rows),
        "vehicles": len(vehicle_rows),
        "shifts": len(shift_rows),
        "scenario_truth_rows": len(scenario_truth_rows),
        "exposure_rows": len(exposure_rows),
        "qc_generation_rows": len(qc_generation_rows),
    }
