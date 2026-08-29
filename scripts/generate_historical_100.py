"""
Step 5 continuation: generate the final 100-shift historical dataset from
the frozen generator (commit 5c63026), same master seed (20240002) as the
approved 24-shift development dataset. SHIFT001-024 must reproduce that
dataset exactly (verified by a dedicated test, not just assumed) since
per-shift seeds and scenario schedules are each derived independently
from (master_seed, shift_id) — extending shift count changes nothing
about shifts that already existed.

Does NOT overwrite data/generated/development_45/ — writes to a separate
data/generated/historical_100/ directory instead.

Usage:
    python scripts/generate_historical_100.py
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
    generate_and_write_dataset_streaming,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
OBSERVABLE_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "observable"
LATENT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "latent"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "manifest.json"

N_SHIFTS = 100
DATASET_MASTER_SEED = 20240002  # same approved seed as the 24-shift set; not re-chosen
GENERATOR_VERSION = "step4-v1"  # unchanged — generator causality was not touched


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
        batch_size=10,
    )
    generation_seconds = time.time() - t0
    write_seconds = 0.0  # generation and writing are interleaved in the streaming path

    import pandas as pd
    qc_df = pd.read_parquet(OBSERVABLE_DIR / "qc_results.parquet")
    defect_rate = (qc_df.qc_result == "DEFECT").mean()
    n_abnormal = sum(1 for m in shift_metadata if m["is_abnormal"])

    manifest = {
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
        "overall_defect_rate": defect_rate,
        "generation_seconds": generation_seconds,
        "write_seconds": write_seconds,
        "output_stats": stats,
        "note": "SHIFT001-024 must be identical to data/generated/development_45/ "
                "(same master seed, same per-shift derivation) — verified by "
                "tests/test_historical_100.py::test_first_24_shifts_match_development_dataset.",
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {N_SHIFTS} shifts, {len(qc_df)} vehicles in {generation_seconds:.1f}s (streaming)")
    print(f"Output -> {OBSERVABLE_DIR.parent}")
    print(f"Abnormal shifts: {n_abnormal}/{N_SHIFTS}")
    print(f"Overall defect rate: {defect_rate*100:.3f}%")
    print(f"Output stats: {stats}")
    print(f"Manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
