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

    shift_results: List[ShiftResult] = []
    for i in range(1, n_shifts + 1):
        shift_results.append(_run_one_shift(
            config, sensor_models, batch_relevant_stations, i, dataset_master_seed,
            vehicles_per_shift, mean_interarrival_seconds, std_interarrival_seconds,
            variant_mix, qc_params, held_out_family,
        ))

    return shift_results


def _global_vehicle_id(shift_id: str, local_vehicle_id: str) -> str:
    return f"{shift_id}::{local_vehicle_id}"


def _extract_rows(shift_results: List[ShiftResult]) -> Dict[str, list]:
    """Pure extraction: ShiftResult objects -> plain-dict rows per table.
    Shared by write_dataset() (batch, in-memory) and
    generate_and_write_dataset_streaming() (chunked) so both paths use
    IDENTICAL row-construction logic — the only difference between them
    is memory management, never the values produced."""
    tables: Dict[str, list] = {
        "events": [], "genealogy": [], "vehicles": [], "shifts": [],
        "scenario_truth": [], "exposure": [], "qc_generation": [],
    }
    for sr in shift_results:
        result = sr.result
        for e in result.events:
            row = dict(e.__dict__)
            if row.get("vehicle_id"):
                row["vehicle_id"] = _global_vehicle_id(sr.shift_id, row["vehicle_id"])
            row["shift_id"] = sr.shift_id
            tables["events"].append(row)

        for local_vid, visits in result.genealogy.items():
            gvid = _global_vehicle_id(sr.shift_id, local_vid)
            vehicle = result.vehicles[local_vid]
            for visit in visits:
                tables["genealogy"].append({
                    "vehicle_id": gvid, "shift_id": sr.shift_id,
                    "variant_id": vehicle.variant_id, **asdict(visit),
                })

        for local_vid, vehicle in result.vehicles.items():
            tables["vehicles"].append({
                "vehicle_id": _global_vehicle_id(sr.shift_id, local_vid),
                "shift_id": sr.shift_id,
                "variant_id": vehicle.variant_id,
                "created_at": vehicle.created_at,
                "completed": vehicle.completed,
                "completed_at": vehicle.completed_at,
            })

        tables["shifts"].append({
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
            tables["scenario_truth"].append(row)

        for rec in result.latent_truth.quality_exposure:
            row = asdict(rec)
            row["vehicle_id"] = _global_vehicle_id(sr.shift_id, row["vehicle_id"])
            row["shift_id"] = sr.shift_id
            tables["exposure"].append(row)

        for rec in result.latent_truth.qc_generation:
            row = asdict(rec)
            row["vehicle_id"] = _global_vehicle_id(sr.shift_id, row["vehicle_id"])
            row["shift_id"] = sr.shift_id
            tables["qc_generation"].append(row)

    return tables


def _run_one_shift(
    config, sensor_models, batch_relevant_stations, shift_index, dataset_master_seed,
    vehicles_per_shift, mean_interarrival_seconds, std_interarrival_seconds,
    variant_mix, qc_params, held_out_family,
) -> ShiftResult:
    """The exact per-shift logic factored out of generate_development_dataset
    so the streaming path below cannot silently drift from it."""
    shift_id = f"SHIFT{shift_index:03d}"
    shift_seed = derive_seed(dataset_master_seed, f"shift_sim::{shift_id}")
    shift_duration_estimate = vehicles_per_shift * mean_interarrival_seconds

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

    return ShiftResult(
        shift_id=shift_id, shift_seed=shift_seed, n_vehicles=vehicles_per_shift,
        is_abnormal=is_abnormal, scenario_ids=[s.scenario_id for s in plan.scenarios],
        result=result,
    )


def generate_and_write_dataset_streaming(
    config: FactoryConfig,
    sensor_models: SensorModelRegistry,
    batch_relevant_stations: Dict[str, int],
    n_shifts: int,
    dataset_master_seed: int,
    observable_dir: Path,
    latent_dir: Path,
    vehicles_per_shift: int = DEFAULT_VEHICLES_PER_SHIFT,
    mean_interarrival_seconds: float = DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    std_interarrival_seconds: float = DEFAULT_STD_INTERARRIVAL_SECONDS,
    variant_mix: Optional[Dict[str, float]] = None,
    qc_params: Optional[QCParameters] = None,
    held_out_family: Optional[ScenarioFamily] = None,
    batch_size: int = 10,
):
    """Memory-bounded variant of generate_development_dataset() +
    write_dataset(), for dataset sizes where holding every shift's full
    RunResult in memory simultaneously risks OOM (encountered in practice
    scaling from 24 to 100 shifts). Processes `batch_size` shifts at a
    time, writes each batch as a row-group via an incrementally-opened
    pyarrow.parquet.ParquetWriter, and discards each batch's RunResult
    objects before starting the next — so peak memory is O(batch_size
    shifts), not O(n_shifts).

    This is a pure orchestration/IO refactor: `_run_one_shift` and
    `_extract_rows` are the SAME per-shift simulation and row-extraction
    logic used by generate_development_dataset()/write_dataset() (shared,
    not reimplemented), so output is byte-identical — verified by
    tests/test_historical_100.py's prefix-identity test against the
    already-audited 24-shift dataset. No change to FactoryEngine,
    ScenarioManager, QCOutcomeGenerator, or any RNG/causal code path.

    Returns (shift_metadata: List[dict], output_stats: dict) — shift
    metadata (shift_id, shift_seed, is_abnormal, scenario_ids) for the
    manifest, deliberately NOT the full ShiftResult list (which would
    reintroduce the memory problem this function exists to avoid).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    variant_mix = variant_mix or DEFAULT_VARIANT_MIX
    qc_params = qc_params or QCParameters()

    observable_dir.mkdir(parents=True, exist_ok=True)
    latent_dir.mkdir(parents=True, exist_ok=True)

    table_paths = {
        "events": observable_dir / "events.parquet",
        "genealogy": observable_dir / "genealogy.parquet",
        "vehicles": observable_dir / "vehicles.parquet",
        "shifts": observable_dir / "shifts.parquet",
        "scenario_truth": latent_dir / "scenario_truth.parquet",
        "exposure": latent_dir / "quality_exposure.parquet",
        "qc_generation": latent_dir / "generator_truth.parquet",
    }
    writers: Dict[str, Optional[pq.ParquetWriter]] = {k: None for k in table_paths}
    counts = {k: 0 for k in table_paths}
    sensor_reading_count = 0
    qc_result_count = 0
    shift_metadata = []

    # Optional[str] fields that can legitimately be all-None within a
    # single batch (e.g. no BAD_BATCH scenario in these 10 shifts) —
    # pyarrow infers an all-null object column as its `null` type rather
    # than string, which then mismatches a sibling batch's real string
    # data. Forcing pandas' nullable "string" dtype up front makes every
    # batch's arrow schema identical regardless of content, so batches
    # can be written to the same incrementally-opened file in any order.
    # Every Optional[str] / Optional[float] / Optional[int] field across
    # the dataclasses these tables are built from (Event, ScenarioTruthRecord,
    # QualityExposureRecord, and the ad-hoc vehicle-row dict) — cast
    # explicitly so a batch where one happens to be all-None still infers
    # the same pyarrow type as a batch with real values, regardless of
    # which batch is written (or opens the file) first.
    NULLABLE_STRING_COLUMNS = {
        "events": ["vehicle_id", "vehicle_variant", "station_id", "buffer_id", "from_state",
                   "to_state", "sensor_name", "unit", "measurement_status", "batch_id",
                   "batch_key", "qc_result"],
        "scenario_truth": ["affected_batch_id"],
        "exposure": ["scenario_id", "station_id"],
    }
    NULLABLE_FLOAT_COLUMNS = {
        "events": ["route_position", "value", "occupancy"],
        "scenario_truth": ["end_time"],
        "vehicles": ["completed_at"],
    }

    def _flush_batch(batch_results: List[ShiftResult]):
        nonlocal sensor_reading_count, qc_result_count
        tables = _extract_rows(batch_results)
        for key, rows in tables.items():
            if not rows:
                continue
            import pandas as pd
            df = pd.DataFrame(rows)
            for col in NULLABLE_STRING_COLUMNS.get(key, []):
                if col in df.columns:
                    df[col] = df[col].astype("string")
            for col in NULLABLE_FLOAT_COLUMNS.get(key, []):
                if col in df.columns:
                    df[col] = df[col].astype("float64")
            arrow_table = pa.Table.from_pandas(df, preserve_index=False)
            if writers[key] is None:
                writers[key] = pq.ParquetWriter(table_paths[key], arrow_table.schema)
            writers[key].write_table(arrow_table)
            counts[key] += len(rows)
            if key == "events":
                sensor_reading_count += int((df.event_type == "SENSOR_READING").sum())
                qc_result_count += int((df.event_type == "QC_RESULT_RECORDED").sum())

    batch: List[ShiftResult] = []
    for i in range(1, n_shifts + 1):
        sr = _run_one_shift(
            config, sensor_models, batch_relevant_stations, i, dataset_master_seed,
            vehicles_per_shift, mean_interarrival_seconds, std_interarrival_seconds,
            variant_mix, qc_params, held_out_family,
        )
        shift_metadata.append({
            "shift_id": sr.shift_id, "shift_seed": sr.shift_seed,
            "is_abnormal": sr.is_abnormal, "scenario_ids": sr.scenario_ids,
        })
        batch.append(sr)
        if len(batch) >= batch_size:
            _flush_batch(batch)
            batch = []  # drop references; RunResult objects become garbage
    if batch:
        _flush_batch(batch)

    for w in writers.values():
        if w is not None:
            w.close()

    stats = {
        "events": counts["events"],
        "sensor_readings": sensor_reading_count,
        "genealogy_rows": counts["genealogy"],
        "vehicles": counts["vehicles"],
        "shifts": counts["shifts"],
        "scenario_truth_rows": counts["scenario_truth"],
        "exposure_rows": counts["exposure"],
        "qc_generation_rows": counts["qc_generation"],
    }

    # qc_results.parquet and sensor_readings.parquet are convenience
    # filtered views of events.parquet in the batch path (write_dataset);
    # reproduce them here too, streaming the already-written events file
    # back through in row-group chunks rather than loading it whole.
    import pandas as pd
    events_pf = pq.ParquetFile(table_paths["events"])
    sensor_writer = None
    qc_writer = None
    for batch_table in events_pf.iter_batches():
        chunk = batch_table.to_pandas()
        sensor_chunk = chunk[chunk.event_type == "SENSOR_READING"]
        if len(sensor_chunk):
            t = pa.Table.from_pandas(sensor_chunk, preserve_index=False)
            if sensor_writer is None:
                sensor_writer = pq.ParquetWriter(observable_dir / "sensor_readings.parquet", t.schema)
            sensor_writer.write_table(t)
        qc_chunk = chunk[chunk.event_type == "QC_RESULT_RECORDED"][
            ["vehicle_id", "shift_id", "vehicle_variant", "simulation_time", "qc_result"]
        ]
        if len(qc_chunk):
            t2 = pa.Table.from_pandas(qc_chunk, preserve_index=False)
            if qc_writer is None:
                qc_writer = pq.ParquetWriter(observable_dir / "qc_results.parquet", t2.schema)
            qc_writer.write_table(t2)
    if sensor_writer is not None:
        sensor_writer.close()
    if qc_writer is not None:
        qc_writer.close()

    return shift_metadata, stats


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
