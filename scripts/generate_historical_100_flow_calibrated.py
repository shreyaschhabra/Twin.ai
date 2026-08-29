"""
Step 5 continuation (Decision 37): generate Dataset C, the mechanistically
calibrated 100-shift Flow-modeling candidate corpus. Same frozen factory,
same MANUAL_VARIATION/EQUIPMENT_DEGRADATION effect equations, same QC
mapping, same master seed (20240002) as Datasets A and B. The ONLY
changes from Dataset B are (1) the revised, capacity-audit-justified
station eligibility list, (2) a locally-scoped MICRO_STOPS recalibration
used only by this enrichment path, and (3) increased opportunity-coverage
targets -- see backend/historical/flow_enrichment.py's module docstring
for the full capacity-margin audit this is based on. Datasets A and B are
left untouched.

Usage:
    python scripts/generate_historical_100_flow_calibrated.py
"""

import functools
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.loader import load_factory_config
from backend.historical.flow_enrichment import (
    BOTTLENECK_CAPABLE_FAMILIES,
    DEGRADATION_OPPORTUNITY_COUNT,
    FLOW_OPPORTUNITY_RANGE,
    MICRO_STOPS_CALIBRATION,
    REJECTED_CANDIDATES,
    SEVERITY_STRATA,
    STATION_CANDIDATES,
    build_flow_enrichment_plan,
    build_shift_schedule_enriched,
    plan_by_shift,
    save_plan,
)
from backend.historical.generator import (
    DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    DEFAULT_STD_INTERARRIVAL_SECONDS,
    DEFAULT_VARIANT_MIX,
    DEFAULT_VEHICLES_PER_SHIFT,
    generate_and_write_dataset_streaming,
)
from backend.simulation.material_batches import load_batch_relevant_stations
from backend.simulation.qc import QCParameters
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
OUT_BASE = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100_flow_calibrated"
OBSERVABLE_DIR = OUT_BASE / "observable"
LATENT_DIR = OUT_BASE / "latent"
SCHEDULE_PLAN_PATH = OUT_BASE / "flow_calibrated_schedule.json"
MANIFEST_PATH = OUT_BASE / "manifest.json"

N_SHIFTS = 100
DATASET_MASTER_SEED = 20240002  # same master seed as Datasets A and B; not re-chosen
GENERATOR_VERSION = "step4-v1"  # causal generator unchanged


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _git_state(repo_root: Path):
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root).decode().strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root).decode()
        dirty_files = [line[3:] for line in status.splitlines() if line.strip()]
        return commit, bool(dirty_files), dirty_files
    except Exception:
        return "unknown", True, ["<git unavailable>"]


def main():
    repo_root = Path(__file__).resolve().parent.parent
    allow_dirty = "--allow-dirty" in sys.argv

    commit, is_dirty, dirty_files = _git_state(repo_root)
    if is_dirty and not allow_dirty:
        print("REFUSING to generate a frozen dataset from a dirty working tree.")
        for f in dirty_files:
            print(f"  {f}")
        print("\nCommit first, or pass --allow-dirty.")
        sys.exit(1)

    plan = build_flow_enrichment_plan(DATASET_MASTER_SEED, n_shifts=N_SHIFTS)
    save_plan(plan, SCHEDULE_PLAN_PATH)
    by_shift = plan_by_shift(plan)
    schedule_fn = functools.partial(build_shift_schedule_enriched, plan_by_shift=by_shift)

    known = [o for o in plan if o.kind == "known_flow_enrichment"]
    degradation = [o for o in plan if o.kind == "unseen_degradation_opportunity"]
    plan_summary = {
        "total_known_flow_opportunities": len(known),
        "total_degradation_opportunities": len(degradation),
        "known_by_partition": dict(Counter(o.partition for o in known)),
        "known_by_family": dict(Counter(o.family for o in known)),
        "known_by_severity_stratum": dict(Counter(o.severity_stratum for o in known)),
        "known_by_bottleneck_capable": {str(k): v for k, v in Counter(o.expected_bottleneck_capable for o in known).items()},
        "known_by_partition_family": {
            p: dict(Counter(o.family for o in known if o.partition == p))
            for p in ["train", "validation", "test"]
        },
        "known_by_partition_capable": {
            p: {str(k): v for k, v in Counter(o.expected_bottleneck_capable for o in known if o.partition == p).items()}
            for p in ["train", "validation", "test"]
        },
        "known_station_usage": dict(Counter(o.station_id for o in known if o.station_id)),
        "degradation_by_partition": dict(Counter(o.partition for o in degradation)),
        "degradation_station_usage": dict(Counter(o.station_id for o in degradation)),
    }

    config_path = CONFIG_DIR / "full_line.yaml"
    station_types_path = CONFIG_DIR / "station_types.yaml"
    sensor_models_path = CONFIG_DIR / "sensor_models_full.yaml"
    batches_path = CONFIG_DIR / "material_batches_full.yaml"

    config = load_factory_config(station_types_path, config_path)
    sensor_models = load_sensor_models(sensor_models_path)
    batch_relevant_stations = load_batch_relevant_stations(batches_path)
    qc_params = QCParameters()

    t0 = time.time()
    shift_metadata, stats = generate_and_write_dataset_streaming(
        config, sensor_models, batch_relevant_stations,
        n_shifts=N_SHIFTS, dataset_master_seed=DATASET_MASTER_SEED,
        observable_dir=OBSERVABLE_DIR, latent_dir=LATENT_DIR,
        vehicles_per_shift=DEFAULT_VEHICLES_PER_SHIFT, qc_params=qc_params,
        batch_size=10, schedule_fn=schedule_fn,
    )
    generation_seconds = time.time() - t0

    import pandas as pd
    qc_df = pd.read_parquet(OBSERVABLE_DIR / "qc_results.parquet")
    defect_rate = (qc_df.qc_result == "DEFECT").mean()
    n_abnormal = sum(1 for m in shift_metadata if m["is_abnormal"])

    manifest = {
        "dataset_role": "Dataset C -- mechanistically calibrated Flow-modeling candidate corpus "
                        "(Decision 37). Datasets A (naturalistic) and B (first coverage experiment) "
                        "remain separate references; see backend/historical/flow_enrichment.py for "
                        "the capacity-margin audit this dataset's scheduling policy is based on.",
        "generator_version": GENERATOR_VERSION,
        "git_commit": commit,
        "git_dirty": is_dirty,
        "git_dirty_files": dirty_files if is_dirty else [],
        "dataset_master_seed": DATASET_MASTER_SEED,
        "n_shifts": N_SHIFTS,
        "vehicles_per_shift": DEFAULT_VEHICLES_PER_SHIFT,
        "total_vehicles": len(qc_df),
        "n_abnormal_shifts": n_abnormal,
        "shift_seeds": {m["shift_id"]: m["shift_seed"] for m in shift_metadata},
        "mean_interarrival_seconds": DEFAULT_MEAN_INTERARRIVAL_SECONDS,
        "std_interarrival_seconds": DEFAULT_STD_INTERARRIVAL_SECONDS,
        "variant_mix": DEFAULT_VARIANT_MIX,
        "qc_parameters": qc_params.__dict__,
        "config_file_hashes": {
            "full_line.yaml": _file_hash(config_path),
            "station_types.yaml": _file_hash(station_types_path),
            "sensor_models_full.yaml": _file_hash(sensor_models_path),
            "material_batches_full.yaml": _file_hash(batches_path),
        },
        "station_candidates": {sid: info["family"].value for sid, info in STATION_CANDIDATES.items()},
        "rejected_candidates": REJECTED_CANDIDATES,
        "micro_stops_calibration": MICRO_STOPS_CALIBRATION,
        "bottleneck_capable_families": [f.value for f in BOTTLENECK_CAPABLE_FAMILIES],
        "severity_strata": SEVERITY_STRATA,
        "flow_opportunity_range": FLOW_OPPORTUNITY_RANGE,
        "degradation_opportunity_count": DEGRADATION_OPPORTUNITY_COUNT,
        "schedule_plan_path": str(SCHEDULE_PLAN_PATH),
        "schedule_plan_hash": _file_hash(SCHEDULE_PLAN_PATH),
        "schedule_plan_summary": plan_summary,
        "overall_defect_rate": defect_rate,
        "generation_seconds": generation_seconds,
        "output_stats": stats,
        "note": "The enrichment plan (flow_calibrated_schedule.json) was built and written to "
                "disk BEFORE this simulation ran, using only static config-derived station "
                "eligibility -- never any Dataset-C outcome.",
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {N_SHIFTS} shifts, {len(qc_df)} vehicles in {generation_seconds:.1f}s (streaming, calibrated schedule)")
    print(f"Output -> {OUT_BASE}")
    print(f"Abnormal shifts: {n_abnormal}/{N_SHIFTS}")
    print(f"Overall defect rate: {defect_rate*100:.3f}%")
    print(f"Plan summary: {json.dumps(plan_summary, indent=2)}")
    print(f"Manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
