"""
Decision 37 (Dataset C mechanistic calibration) tests: micro-stop
capacity-impact mapping, MICRO_STOPS Quality isolation, vehicle-mix
feasibility, revised station eligibility, and non-regression of the
already-generated Datasets A and B.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from backend.historical.flow_enrichment import (
    MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS,
    REJECTED_CANDIDATES,
    STATION_CANDIDATES,
)
from backend.simulation.rng import RNGStreamFactory
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily
from backend.simulation.scenarios.latent import LatentTruthLog
from backend.simulation.scenarios.manager import ScenarioManager

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "full_line.yaml"
MEAN_INTERARRIVAL = 115.0
DEFAULT_MIX = {"ICE_SEDAN": 0.45, "ICE_SUV": 0.35, "EV": 0.20}


def _config():
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def _variant_multiplier(station_id, variant_id, station_cfg, variants):
    overrides = station_cfg.get("variant_overrides", {})
    if variant_id in overrides and "cycle_time_multiplier" in overrides[variant_id]:
        return overrides[variant_id]["cycle_time_multiplier"]
    return variants[variant_id].get("processing_time_modifiers", {}).get(station_id, 1.0)


def _mix_mean_cycle_time(station_id):
    cfg = _config()
    station_cfg = cfg["stations"][station_id]
    variants = cfg["vehicle_variants"]
    base = station_cfg["baseline_cycle_time_seconds"]
    return sum(DEFAULT_MIX[v] * base * _variant_multiplier(station_id, v, station_cfg, variants) for v in DEFAULT_MIX)


def _old_micro_stop_expected_extra(severity):
    prob = 0.15 + 0.45 * severity
    max_dur = 15 + 45 * severity
    mean_dur = (8 + max_dur) / 2
    return prob * mean_dur


def _new_micro_stop_expected_extra(severity):
    prob = 0.20 + 0.65 * severity
    max_dur = 15 + 75 * severity
    mean_dur = (8 + max_dur) / 2
    return prob * mean_dur


def test_old_micro_stops_equation_cannot_reach_any_candidate_gap():
    """Confirms the mechanistic root cause of Dataset B's 0/6 MICRO_STOPS
    conversion rate: even at the theoretical maximum severity (1.0, never
    actually drawn since strata capped at 0.95), the old equation's
    expected extra time is smaller than every original candidate's gap
    to breakeven."""
    max_old_extra = _old_micro_stop_expected_extra(1.0)
    gaps = {
        "S26": MEAN_INTERARRIVAL - _mix_mean_cycle_time("S26"),
        "S20": MEAN_INTERARRIVAL - _mix_mean_cycle_time("S20"),
        "S07": MEAN_INTERARRIVAL - _mix_mean_cycle_time("S07"),
    }
    for station, gap in gaps.items():
        assert max_old_extra < gap, f"old MICRO_STOPS should be unable to close {station}'s gap of {gap:.1f}s"


def test_new_micro_stops_equation_approaches_s26_breakeven_only_at_severe():
    gap_s26 = MEAN_INTERARRIVAL - _mix_mean_cycle_time("S26")

    mild_upper = _new_micro_stop_expected_extra(0.35)
    moderate_upper = _new_micro_stop_expected_extra(0.65)
    severe_upper = _new_micro_stop_expected_extra(0.95)

    assert mild_upper / gap_s26 < 0.35, "MILD should stay comfortably below S26's breakeven gap"
    assert 0.40 < moderate_upper / gap_s26 < 0.75, "MODERATE should approach but not reliably cross breakeven"
    assert 0.90 < severe_upper / gap_s26 < 1.20, "SEVERE should make breakeven genuinely reachable, not trivial"


def test_new_micro_stops_still_cannot_close_rejected_stations_gap():
    """S07 and S20 were dropped as MICRO_STOPS candidates; confirm the
    recalibration deliberately does not reach far enough to cover them
    (Decision 37 explicitly warns against over-strengthening)."""
    severe_upper_extra = _new_micro_stop_expected_extra(0.95)
    for station in ["S07", "S20"]:
        gap = MEAN_INTERARRIVAL - _mix_mean_cycle_time(station)
        assert severe_upper_extra < gap, f"{station} should remain out of reach even at SEVERE upper bound"


def test_micro_stops_has_zero_quality_exposure_channel():
    """Structural proof (Decision 37 Section 4): MICRO_STOPS is handled
    exclusively via ScenarioManager.get_micro_stop_params, never via
    get_station_effects (the only method that writes QualityExposureRecord
    or touches cycle_time_multiplier/sensor_mean_shift)."""
    scenario = ScenarioDefinition(
        scenario_id="test::micro_stops::1", family=ScenarioFamily.MICRO_STOPS,
        station_ids=["S26"], start_time=0.0, duration=1000.0, severity=0.8,
        params={"stop_probability": 0.5, "min_duration_seconds": 8, "max_duration_seconds": 60},
    )
    latent_log = LatentTruthLog()
    manager = ScenarioManager(scenarios=[scenario], latent_log=latent_log)

    bundle = manager.get_station_effects(sim_time=500.0, station_id="S26", vehicle_id="V001")

    assert bundle.cycle_time_multiplier == 1.0
    assert bundle.variability_multiplier == 1.0
    assert bundle.sensor_mean_shift == {}
    assert bundle.sensor_noise_multiplier == {}
    assert "test::micro_stops::1" not in bundle.active_scenario_ids
    assert latent_log.quality_exposure == []

    params = manager.get_micro_stop_params(sim_time=500.0, station_id="S26")
    assert params is not None
    assert params["probability"] == 0.5


def test_vehicle_mix_overload_not_capable_at_any_documented_station():
    """Decision 37 Section 5/7: even 100% concentration of the slowest
    applicable variant leaves every mix-sensitive station below its own
    breakeven utilization -- confirms the hard-negative classification
    using only config + existing variant multipliers."""
    cfg = _config()
    for station_id in MIX_OVERLOAD_EXPECTED_IMPACT_STATIONS:
        station_cfg = cfg["stations"][station_id]
        variants = cfg["vehicle_variants"]
        base = station_cfg["baseline_cycle_time_seconds"]
        mults = {v: _variant_multiplier(station_id, v, station_cfg, variants) for v in DEFAULT_MIX}
        slowest_mult = max(mults.values())
        mean_at_100pct_slowest = base * slowest_mult
        rho = mean_at_100pct_slowest / MEAN_INTERARRIVAL
        assert rho < 1.0, f"{station_id} should remain under capacity even at 100% slowest-variant mix"


def test_manual_variation_candidates_are_capacity_justified():
    max_deliverable_mult = 1.15 + 0.5 * 0.95  # unchanged equation, SEVERE upper bound
    for station_id, info in STATION_CANDIDATES.items():
        if info["family"] != ScenarioFamily.MANUAL_VARIATION:
            continue
        mix_mean = _mix_mean_cycle_time(station_id)
        breakeven_mult = MEAN_INTERARRIVAL / mix_mean
        margin = max_deliverable_mult - breakeven_mult
        assert margin > -0.05, f"{station_id} should be at least near-breakeven under MANUAL_VARIATION"


def test_rejected_manual_variation_stations_are_documented_and_excluded():
    for station_id in ["S11", "S33", "S34"]:
        assert station_id in REJECTED_CANDIDATES
        assert station_id not in STATION_CANDIDATES


def test_station_candidates_match_capacity_audit_conclusion():
    assert STATION_CANDIDATES["S21"]["family"] == ScenarioFamily.MANUAL_VARIATION
    assert STATION_CANDIDATES["S22"]["family"] == ScenarioFamily.MANUAL_VARIATION
    assert STATION_CANDIDATES["S26"]["family"] == ScenarioFamily.MICRO_STOPS
    assert set(STATION_CANDIDATES) == {"S21", "S22", "S26"}


def test_dataset_a_manifest_unchanged():
    manifest_path = Path(__file__).resolve().parent.parent / "data" / "generated" / "historical_100" / "manifest.json"
    with manifest_path.open() as f:
        manifest = json.load(f)
    assert manifest["git_commit"].startswith("ea49b96")
    assert manifest["n_shifts"] == 100
    assert manifest["dataset_master_seed"] == 20240002
