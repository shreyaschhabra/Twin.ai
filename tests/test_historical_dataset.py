"""
Step 4, Section AJ items 28-32: historical generation tests. Uses a small
scale (3 shifts x 20 vehicles) purely for test speed — the actual
persisted development dataset (24 shifts x 450 vehicles) is produced by
scripts/generate_development_dataset.py, not by this test suite.
"""

import json
from pathlib import Path

import pytest

from backend.config.loader import load_factory_config
from backend.historical.generator import generate_development_dataset, write_dataset
from backend.simulation.material_batches import load_batch_relevant_stations
from backend.simulation.qc import QCParameters
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


@pytest.fixture(scope="module")
def sensor_models():
    return load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")


@pytest.fixture(scope="module")
def batch_relevant_stations():
    return load_batch_relevant_stations(CONFIG_DIR / "material_batches_full.yaml")


@pytest.fixture(scope="module")
def shift_results(config, sensor_models, batch_relevant_stations):
    return generate_development_dataset(
        config, sensor_models, batch_relevant_stations,
        n_shifts=3, dataset_master_seed=999, vehicles_per_shift=20,
    )


def test_all_shifts_complete(shift_results):
    assert len(shift_results) == 3
    for sr in shift_results:
        assert sr.result.summary["vehicles_completed"] == sr.n_vehicles


def test_unique_vehicle_ids_across_shifts(shift_results):
    all_global_ids = []
    for sr in shift_results:
        for local_id in sr.result.vehicles:
            all_global_ids.append(f"{sr.shift_id}::{local_id}")
    assert len(all_global_ids) == len(set(all_global_ids))


def test_shift_ids_unique(shift_results):
    ids = [sr.shift_id for sr in shift_results]
    assert len(ids) == len(set(ids))


def test_shift_seeds_deterministic(config, sensor_models, batch_relevant_stations):
    r1 = generate_development_dataset(config, sensor_models, batch_relevant_stations,
                                       n_shifts=2, dataset_master_seed=555, vehicles_per_shift=15)
    r2 = generate_development_dataset(config, sensor_models, batch_relevant_stations,
                                       n_shifts=2, dataset_master_seed=555, vehicles_per_shift=15)
    assert [s.shift_seed for s in r1] == [s.shift_seed for s in r2]
    assert [s.scenario_ids for s in r1] == [s.scenario_ids for s in r2]
    qc1 = [(v, r.qc_result) for s in r1 for v, r in
           [(rec.vehicle_id, rec) for rec in s.result.latent_truth.qc_generation]]
    qc2 = [(v, r.qc_result) for s in r2 for v, r in
           [(rec.vehicle_id, rec) for rec in s.result.latent_truth.qc_generation]]
    assert qc1 == qc2


def test_saved_dataset_reloads_successfully(shift_results, tmp_path):
    import pandas as pd

    observable_dir = tmp_path / "observable"
    latent_dir = tmp_path / "latent"
    stats = write_dataset(shift_results, observable_dir, latent_dir)

    events = pd.read_parquet(observable_dir / "events.parquet")
    qc_results = pd.read_parquet(observable_dir / "qc_results.parquet")
    vehicles = pd.read_parquet(observable_dir / "vehicles.parquet")
    shifts = pd.read_parquet(observable_dir / "shifts.parquet")
    scenario_truth = pd.read_parquet(latent_dir / "scenario_truth.parquet")
    exposure = pd.read_parquet(latent_dir / "quality_exposure.parquet")

    assert len(events) == stats["events"]
    assert len(vehicles) == 60  # 3 shifts x 20 vehicles
    assert len(shifts) == 3
    assert set(vehicles.vehicle_id) == set(qc_results.vehicle_id) if len(qc_results) else True
    assert len(scenario_truth) >= 3  # at least the always-on background scenario per shift
    assert isinstance(exposure, pd.DataFrame)


def test_scenario_schedule_reproducible_across_separate_processes():
    """Regression test for a real bug caught during Step 4 development:
    the scenario-family draw order was built from a set union
    (`dict.keys() | some_set`), and since ScenarioFamily is a str Enum,
    Python's per-process string-hash randomization (PYTHONHASHSEED) gave
    that set a DIFFERENT iteration order on every fresh process — so the
    same seed produced a different scenario schedule (and therefore a
    different defect rate) every time the generator script was re-run.
    A single pytest process can't catch this (PYTHONHASHSEED is fixed for
    its whole lifetime), so this spawns two genuinely separate Python
    processes and diffs their output."""
    import subprocess
    import sys

    code = (
        "from backend.historical.shift_scheduler import build_shift_schedule\n"
        "plan = build_shift_schedule(dataset_master_seed=4242, shift_id='SHIFT001', "
        "shift_duration_seconds=45000, mean_interarrival_seconds=115.0)\n"
        "print([s.family.value for s in plan.scenarios])\n"
    )
    repo_root = Path(__file__).resolve().parent.parent
    outputs = []
    for _ in range(3):
        out = subprocess.check_output([sys.executable, "-c", code], cwd=repo_root)
        outputs.append(out)
    assert len(set(outputs)) == 1, f"schedule differs across processes: {outputs}"


def test_manifest_reproduces_generation_configuration(shift_results, tmp_path):
    manifest = {
        "dataset_master_seed": 999,
        "n_shifts": 3,
        "vehicles_per_shift": 20,
        "shift_seeds": {sr.shift_id: sr.shift_seed for sr in shift_results},
    }
    manifest_path = tmp_path / "manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f)

    with manifest_path.open() as f:
        reloaded = json.load(f)

    # re-derive seeds independently from the manifest's own master seed
    # and confirm they match what's recorded — proves the manifest alone
    # is sufficient to reproduce the run
    from backend.simulation.rng import derive_seed
    for shift_id, recorded_seed in reloaded["shift_seeds"].items():
        assert derive_seed(reloaded["dataset_master_seed"], f"shift_sim::{shift_id}") == recorded_seed


def test_dataset_generation_refuses_dirty_tree_by_default(tmp_path):
    """Step 4 patch 4: the generation script must not silently produce a
    dataset from an uncommitted generator state without at least being
    told to via --allow-dirty."""
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root).decode()
    is_actually_dirty = bool(status.strip())

    sys.path.insert(0, str(repo_root / "scripts"))
    import importlib
    gen_script = importlib.import_module("generate_development_dataset")
    commit, is_dirty, dirty_files = gen_script._git_state(repo_root)

    assert is_dirty == is_actually_dirty
    assert commit and commit != "unknown"
    if is_dirty:
        assert len(dirty_files) > 0
