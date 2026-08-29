"""
Step 3, Section S: enabling the scenario/sensor framework must not change
the healthy (no-scenario) run's core mechanics. tests/fixtures/
step2_reference_events.json was captured from the engine as committed at
57e71f3 (Step 2, before any Step 3 code existed) for this exact config,
seed, and vehicle count — the only faithful way to prove "unchanged" is to
diff against what the mechanics actually were, not re-derive a new
"expected" value from the same (now-modified) code.
"""

import json
from pathlib import Path

from backend.config.loader import load_factory_config
from backend.simulation.engine import run_simulation

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "step2_reference_events.json"

CORE_EVENT_TYPES = {
    "VEHICLE_CREATED", "VEHICLE_ENTERED_BUFFER", "VEHICLE_LEFT_BUFFER",
    "VEHICLE_ENTERED_STATION", "STATION_PROCESSING_STARTED",
    "STATION_PROCESSING_COMPLETED", "STATION_STATE_CHANGED", "VEHICLE_COMPLETED_LINE",
}


def test_no_scenario_run_matches_step2_reference_core_events():
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml")
    result = run_simulation(config, n_vehicles=20, seed=42, mean_interarrival_seconds=200.0, std_interarrival_seconds=20.0)

    rows = [
        [e.event_type, e.simulation_time, e.vehicle_id, e.vehicle_variant, e.station_id,
         e.buffer_id, e.route_position, e.from_state, e.to_state, e.value, e.occupancy]
        for e in result.events if e.event_type in CORE_EVENT_TYPES
    ]

    with FIXTURE_PATH.open() as f:
        reference = json.load(f)

    assert rows == reference


def test_no_scenario_run_produces_no_sensor_or_scenario_events():
    config = load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml")
    # deliberately no sensor_models, no scenarios passed
    result = run_simulation(config, n_vehicles=20, seed=42)
    event_types = {e.event_type for e in result.events}
    assert event_types <= CORE_EVENT_TYPES
    assert result.latent_truth.scenario_truth == []
    assert result.latent_truth.quality_exposure == []
