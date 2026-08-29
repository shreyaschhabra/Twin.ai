"""
Step 4: generate the 20-30 shift DEVELOPMENT historical dataset on the
full 45-station line. Not the final 100-shift dataset (explicitly out of
scope for Step 4).

Usage:
    python scripts/generate_development_dataset.py
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.loader import load_factory_config
from backend.simulation.material_batches import load_batch_relevant_stations
from backend.simulation.qc import QCParameters
from backend.simulation.sensors import load_sensor_models
from backend.historical.generator import (
    DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    DEFAULT_STD_INTERARRIVAL_SECONDS,
    DEFAULT_VARIANT_MIX,
    DEFAULT_VEHICLES_PER_SHIFT,
    generate_development_dataset,
    write_dataset,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
OBSERVABLE_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "development_45" / "observable"
LATENT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "development_45" / "latent"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "generated" / "development_45" / "manifest.json"

N_SHIFTS = 24
# 20240001 was the first choice, but its scenario schedule happened to
# draw zero SENSOR_DROPOUT instances (24 draws across 7 equally-likely
# families, ~2.8% chance of any one family being skipped entirely) —
# leaving no missingness evidence for the Section Z sensor EDA. 20240002
# lands in the target defect-rate band AND draws all 7 non-background
# families at least once; picked for that reason, not cherry-picked for
# defect rate alone.
DATASET_MASTER_SEED = 20240002
GENERATOR_VERSION = "step4-v1"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main():
    config_path = CONFIG_DIR / "full_line.yaml"
    station_types_path = CONFIG_DIR / "station_types.yaml"
    sensor_models_path = CONFIG_DIR / "sensor_models_full.yaml"
    batches_path = CONFIG_DIR / "material_batches_full.yaml"

    config = load_factory_config(station_types_path, config_path)
    sensor_models = load_sensor_models(sensor_models_path)
    batch_relevant_stations = load_batch_relevant_stations(batches_path)
    qc_params = QCParameters()

    t0 = time.time()
    shift_results = generate_development_dataset(
        config, sensor_models, batch_relevant_stations,
        n_shifts=N_SHIFTS, dataset_master_seed=DATASET_MASTER_SEED,
        vehicles_per_shift=DEFAULT_VEHICLES_PER_SHIFT, qc_params=qc_params,
    )
    generation_seconds = time.time() - t0

    t1 = time.time()
    stats = write_dataset(shift_results, OBSERVABLE_DIR, LATENT_DIR)
    write_seconds = time.time() - t1

    total_qc = [r.qc_result for sr in shift_results for r in sr.result.latent_truth.qc_generation]
    defect_rate = total_qc.count("DEFECT") / len(total_qc)
    n_abnormal = sum(1 for s in shift_results if s.is_abnormal)

    try:
        parent_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent.parent
        ).decode().strip()
    except Exception:
        parent_commit = "unknown"

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "git_parent_commit": parent_commit,
        "note": "git_parent_commit is HEAD at generation time, i.e. the commit BEFORE the "
                "freeze commit that adds this manifest file (a commit cannot contain its own "
                "hash) — see the Step 4 completion report for the actual freeze commit hash.",
        "dataset_master_seed": DATASET_MASTER_SEED,
        "n_shifts": N_SHIFTS,
        "vehicles_per_shift": DEFAULT_VEHICLES_PER_SHIFT,
        "total_vehicles": len(total_qc),
        "n_abnormal_shifts": n_abnormal,
        "shift_seeds": {sr.shift_id: sr.shift_seed for sr in shift_results},
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
        "overall_defect_rate": defect_rate,
        "generation_seconds": generation_seconds,
        "write_seconds": write_seconds,
        "output_stats": stats,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {N_SHIFTS} shifts, {len(total_qc)} vehicles in {generation_seconds:.1f}s")
    print(f"Wrote dataset in {write_seconds:.1f}s -> {OBSERVABLE_DIR.parent}")
    print(f"Abnormal shifts: {n_abnormal}/{N_SHIFTS}")
    print(f"Overall defect rate: {defect_rate*100:.3f}%")
    print(f"Output stats: {stats}")
    print(f"Manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
