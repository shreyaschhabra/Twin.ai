"""
End-to-end determinism test for the enriched-scheduler generation path
(Section 23: "two regenerations must be value-identical"). Uses a small
ad-hoc plan (not the locked 100-shift plan, which build_flow_enrichment_plan
refuses for any other shift count) so this runs fast as a unit test.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.config.loader import load_factory_config
from backend.historical.flow_enrichment import EnrichmentOpportunity, build_shift_schedule_enriched, plan_by_shift
from backend.historical.generator import generate_and_write_dataset_streaming
from backend.simulation.material_batches import load_batch_relevant_stations
from backend.simulation.qc import QCParameters
from backend.simulation.sensors import load_sensor_models

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
MASTER_SEED = 20240002


def _small_plan():
    return [
        EnrichmentOpportunity(
            shift_id="SHIFT002", partition="train", kind="known_flow_enrichment",
            family="MANUAL_VARIATION", station_id="S22", severity_stratum="SEVERE",
            severity=0.8, start_time_fraction=0.3, duration_fraction=0.3,
        ),
        EnrichmentOpportunity(
            shift_id="SHIFT004", partition="train", kind="known_flow_enrichment",
            family="VEHICLE_MIX_OVERLOAD", station_id=None, severity_stratum="MODERATE",
            severity=0.5, start_time_fraction=0.2, duration_fraction=0.25,
        ),
    ]


def _generate(out_dir: Path):
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")
    batch_relevant_stations = load_batch_relevant_stations(CONFIG_DIR / "material_batches_full.yaml")
    schedule_fn = functools.partial(build_shift_schedule_enriched, plan_by_shift=plan_by_shift(_small_plan()))

    shift_metadata, stats = generate_and_write_dataset_streaming(
        config, sensor_models, batch_relevant_stations,
        n_shifts=6, dataset_master_seed=MASTER_SEED,
        observable_dir=out_dir / "observable", latent_dir=out_dir / "latent",
        qc_params=QCParameters(), batch_size=2, schedule_fn=schedule_fn,
    )
    return shift_metadata, stats


def test_enriched_generation_is_reproducible(tmp_path):
    meta_a, stats_a = _generate(tmp_path / "run_a")
    meta_b, stats_b = _generate(tmp_path / "run_b")

    assert meta_a == meta_b
    assert stats_a == stats_b

    events_a = pd.read_parquet(tmp_path / "run_a" / "observable" / "events.parquet")
    events_b = pd.read_parquet(tmp_path / "run_b" / "observable" / "events.parquet")
    pd.testing.assert_frame_equal(
        events_a.sort_values(["shift_id", "event_id"]).reset_index(drop=True),
        events_b.sort_values(["shift_id", "event_id"]).reset_index(drop=True),
        check_dtype=False,
    )

    scenario_a = pd.read_parquet(tmp_path / "run_a" / "latent" / "scenario_truth.parquet")
    scenario_b = pd.read_parquet(tmp_path / "run_b" / "latent" / "scenario_truth.parquet")
    pd.testing.assert_frame_equal(
        scenario_a.sort_values(["shift_id", "scenario_id"]).reset_index(drop=True),
        scenario_b.sort_values(["shift_id", "scenario_id"]).reset_index(drop=True),
        check_dtype=False,
    )


def test_enriched_generation_injects_the_planned_scenario(tmp_path):
    _generate(tmp_path / "run")
    scenario_truth = pd.read_parquet(tmp_path / "run" / "latent" / "scenario_truth.parquet")

    shift2 = scenario_truth[scenario_truth.shift_id == "SHIFT002"]
    assert (shift2.family == "MANUAL_VARIATION").any()
    manual_var_rows = shift2[shift2.family == "MANUAL_VARIATION"]
    assert any("S22" in json.loads(ids) for ids in manual_var_rows.station_ids)

    shift4 = scenario_truth[scenario_truth.shift_id == "SHIFT004"]
    assert (shift4.family == "VEHICLE_MIX_OVERLOAD").any()
