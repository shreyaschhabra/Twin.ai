"""
Cross-checks the independently-coded bottleneck-event/label re-derivation
(backend/flow/independent_check.py) against the production implementation
(backend/flow/bottleneck_events.py, backend/flow/labels.py) -- borrowed
from the reference project's causal_validation.py idea: verify by full
independent re-derivation, not only by a synthetic future-mutation probe.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from backend.config.loader import load_factory_config
from backend.flow.bottleneck_events import detect_bottleneck_events
from backend.flow.independent_check import detect_impact_intervals_independent, label_rows_independent
from backend.flow.labels import label_rows
from backend.flow.pipeline import build_station_minute_grid

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "observable" / "events.parquet"


@pytest.fixture(scope="module")
def config():
    return load_factory_config(CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "full_line.yaml")


def _events_for_shifts(shift_ids):
    events = pd.read_parquet(DATA_PATH)
    return events[events.shift_id.isin(shift_ids)]


def test_independent_event_detection_matches_production_on_busy_shift(config):
    events = _events_for_shifts(["SHIFT004"])  # known busy shift, many BLOCKED episodes
    production = detect_bottleneck_events(events, config)
    independent = detect_impact_intervals_independent(events, config)

    prod_keys = set(zip(production.shift_id, production.blocked_station_id,
                         production.onset_time.round(6), production.end_time.round(6)))
    indep_keys = set(zip(independent.shift_id, independent.blocked_station_id,
                          independent.onset_time.round(6), independent.end_time.round(6)))
    assert prod_keys == indep_keys, (
        f"mismatch: in production not independent={prod_keys - indep_keys}, "
        f"in independent not production={indep_keys - prod_keys}"
    )
    assert len(production) == len(independent) > 0


def test_independent_impact_station_attribution_matches(config):
    events = _events_for_shifts(["SHIFT004"])
    production = detect_bottleneck_events(events, config)
    independent = detect_impact_intervals_independent(events, config)

    prod_map = {(r.shift_id, r.blocked_station_id, round(r.onset_time, 6)): r.impact_station_id
                for r in production.itertuples()}
    for r in independent.itertuples():
        key = (r.shift_id, r.blocked_station_id, round(r.onset_time, 6))
        assert prod_map.get(key) == r.impact_station_id


def test_independent_labels_match_production_on_busy_shift(config):
    events = _events_for_shifts(["SHIFT004"])
    production_impacts = detect_bottleneck_events(events, config)
    station_ids = sorted(config.stations.keys())
    grid = build_station_minute_grid(events, station_ids)

    production_labeled = label_rows(grid, production_impacts)

    independent_impacts = detect_impact_intervals_independent(events, config)
    independent_labeled = label_rows_independent(grid, independent_impacts)

    merged = production_labeled[["shift_id", "station_id", "window_end_time", "label"]].merge(
        independent_labeled[["shift_id", "station_id", "window_end_time", "label"]],
        on=["shift_id", "station_id", "window_end_time"], suffixes=("_prod", "_indep"),
    )
    mismatches = merged[merged.label_prod != merged.label_indep]
    assert len(mismatches) == 0, f"{len(mismatches)} label mismatches:\n{mismatches.head(20)}"
    assert len(merged) == len(production_labeled)


def test_independent_check_handles_no_events(config):
    empty = pd.DataFrame(columns=["shift_id", "event_type", "station_id", "buffer_id",
                                   "from_state", "to_state", "simulation_time", "event_id"])
    result = detect_impact_intervals_independent(empty, config)
    assert len(result) == 0
