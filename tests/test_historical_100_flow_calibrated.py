"""
End-to-end determinism test for the Decision-37 recalibrated MICRO_STOPS
enrichment path specifically (Dataset B's determinism test already covers
MANUAL_VARIATION/VEHICLE_MIX_OVERLOAD injection through the same
schedule_fn plumbing; this test exercises the NEW
_build_recalibrated_micro_stops code path).
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
            shift_id="SHIFT003", partition="train", kind="known_flow_enrichment",
            family="MICRO_STOPS", station_id="S26", severity_stratum="SEVERE",
            severity=0.9, start_time_fraction=0.3, duration_fraction=0.3,
            expected_bottleneck_capable=True,
        ),
    ]


def _generate(out_dir: Path):
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")
    sensor_models = load_sensor_models(CONFIG_DIR / "sensor_models_full.yaml")
    batch_relevant_stations = load_batch_relevant_stations(CONFIG_DIR / "material_batches_full.yaml")
    schedule_fn = functools.partial(build_shift_schedule_enriched, plan_by_shift=plan_by_shift(_small_plan()))

    return generate_and_write_dataset_streaming(
        config, sensor_models, batch_relevant_stations,
        n_shifts=4, dataset_master_seed=MASTER_SEED,
        observable_dir=out_dir / "observable", latent_dir=out_dir / "latent",
        qc_params=QCParameters(), batch_size=2, schedule_fn=schedule_fn,
    )


def test_recalibrated_micro_stops_generation_is_reproducible(tmp_path):
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


def test_recalibrated_micro_stops_uses_new_params_not_old():
    """The injected MICRO_STOPS scenario_truth record must carry the NEW
    stop_probability formula (0.20+0.65*severity), not the old
    (0.15+0.45*severity) used by the unchanged background scheduler."""
    out_dir = Path("/tmp/_flow_calibrated_test_scratch")
    import shutil
    shutil.rmtree(out_dir, ignore_errors=True)
    _generate(out_dir)
    scenario_truth = pd.read_parquet(out_dir / "latent" / "scenario_truth.parquet")
    shift3 = scenario_truth[scenario_truth.shift_id == "SHIFT003"]
    micro_stops_rows = shift3[shift3.family == "MICRO_STOPS"]
    assert len(micro_stops_rows) >= 1
    row = micro_stops_rows.iloc[-1]  # the appended enrichment scenario, last in list order
    severity = row.severity
    expected_prob = 0.20 + 0.65 * severity
    params = json.loads(row.params) if isinstance(row.params, str) else row.params
    assert abs(params["stop_probability"] - expected_prob) < 1e-9
    shutil.rmtree(out_dir, ignore_errors=True)
