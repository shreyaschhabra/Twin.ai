"""Pre-pilot Flow-v3 scenario physics at the provisional 102.5s headway."""

from __future__ import annotations

from backend.config.schemas import FactoryConfig
from backend.flow_v3.capacity_audit import build_capacity_audit
from backend.simulation.scenarios.config import ScenarioDefinition, ScenarioFamily

PROVISIONAL_HEADWAY_SECONDS = 102.5
MANUAL_CANDIDATES = ("S11", "S21", "S22", "S24", "S33", "S34", "S38")
MICRO_STOP_CANDIDATES = ("S20", "S26")

SEVERITY_ORDER = ("MILD", "MODERATE", "SEVERE")
MANUAL_PROFILES = ("STEP", "GRADUAL", "RECOVERING")
MICRO_STOP_PROFILES = ("STEP", "GRADUAL", "RECOVERING")
ARRIVAL_PROFILES = ("STEP_BURST", "RAMP_BURST")
DEGRADATION_PROFILES = ("GRADUAL", "ACCELERATING", "STEP", "INTERMITTENT")

MANUAL_DURATION_MINUTES = {"MILD": 25.0, "MODERATE": 40.0, "SEVERE": 60.0}
MICRO_STOP_DURATION_MINUTES = {"MILD": 20.0, "MODERATE": 35.0, "SEVERE": 60.0}
ARRIVAL_DURATION_MINUTES = {"MILD": 15.0, "MODERATE": 25.0, "SEVERE": 40.0}
DEGRADATION_DURATION_MINUTES = {"MILD": 30.0, "MODERATE": 60.0, "SEVERE": 90.0}

MICRO_STOP_PARAMETERS = {
    "MILD": {"rate_per_processing_minute": 0.20, "min_duration_seconds": 3.0, "max_duration_seconds": 9.0},
    "MODERATE": {"rate_per_processing_minute": 1.25, "min_duration_seconds": 8.0, "max_duration_seconds": 24.0},
    "SEVERE": {"rate_per_processing_minute": 1.80, "min_duration_seconds": 10.0, "max_duration_seconds": 30.0},
}
ARRIVAL_HEADWAY_MULTIPLIER = {"MILD": 0.90, "MODERATE": 0.75, "SEVERE": 0.60}


def _validate_severity(severity: str) -> str:
    value = severity.upper()
    if value not in SEVERITY_ORDER:
        raise ValueError(f"unsupported severity {severity!r}")
    return value


def _baseline_rho(config: FactoryConfig, station_id: str, headway: float) -> float:
    rows = build_capacity_audit(config, headway)
    return next(row["nominal_utilization_rho"] for row in rows if row["station_id"] == station_id)


def manual_cycle_multiplier(config: FactoryConfig, station_id: str, severity: str, headway: float = PROVISIONAL_HEADWAY_SECONDS) -> float:
    severity = _validate_severity(severity)
    rho = _baseline_rho(config, station_id, headway)
    if severity == "MILD":
        return min(1.12, max(1.02, min(0.92, rho + 0.10) / rho))
    if severity == "MODERATE":
        # Slightly above theoretical breakeven: short stochastic runs may
        # or may not fill the real buffer, producing the intended mixed case.
        return min(1.45, 1.02 / rho)
    return min(1.65, 1.12 / rho)


def build_manual_variation(
    config: FactoryConfig,
    *,
    scenario_id: str,
    station_id: str,
    severity: str,
    profile: str,
    start_time: float,
    headway: float = PROVISIONAL_HEADWAY_SECONDS,
) -> ScenarioDefinition:
    severity = _validate_severity(severity)
    profile = profile.upper()
    if station_id not in MANUAL_CANDIDATES:
        raise ValueError(f"{station_id} is not an approved manual-variation candidate")
    if profile not in MANUAL_PROFILES:
        raise ValueError(f"unsupported manual profile {profile}")
    variability = {"MILD": 1.15, "MODERATE": 1.40, "SEVERE": 1.80}[severity]
    return ScenarioDefinition(
        scenario_id=scenario_id,
        family=ScenarioFamily.MANUAL_VARIATION,
        station_ids=[station_id],
        start_time=start_time,
        duration=MANUAL_DURATION_MINUTES[severity] * 60.0,
        severity={"MILD": 0.25, "MODERATE": 0.55, "SEVERE": 0.90}[severity],
        temporal_profile=profile,
        params={
            "cycle_time_multiplier": manual_cycle_multiplier(config, station_id, severity, headway),
            "variability_multiplier": variability,
        },
    )


def build_micro_stops(
    *, scenario_id: str, station_id: str, severity: str, profile: str, start_time: float
) -> ScenarioDefinition:
    severity = _validate_severity(severity)
    profile = profile.upper()
    if station_id not in MICRO_STOP_CANDIDATES:
        raise ValueError(f"{station_id} is not an approved micro-stop candidate")
    if profile not in MICRO_STOP_PROFILES:
        raise ValueError(f"unsupported micro-stop profile {profile}")
    return ScenarioDefinition(
        scenario_id=scenario_id,
        family=ScenarioFamily.MICRO_STOPS,
        station_ids=[station_id],
        start_time=start_time,
        duration=MICRO_STOP_DURATION_MINUTES[severity] * 60.0,
        severity={"MILD": 0.25, "MODERATE": 0.55, "SEVERE": 0.90}[severity],
        temporal_profile=profile,
        params=dict(MICRO_STOP_PARAMETERS[severity]),
    )


def build_arrival_burst(
    *, scenario_id: str, severity: str, profile: str, start_time: float
) -> ScenarioDefinition:
    severity = _validate_severity(severity)
    profile = profile.upper()
    if profile not in ARRIVAL_PROFILES:
        raise ValueError(f"unsupported arrival profile {profile}")
    return ScenarioDefinition(
        scenario_id=scenario_id,
        family=ScenarioFamily.ARRIVAL_BURST,
        start_time=start_time,
        duration=ARRIVAL_DURATION_MINUTES[severity] * 60.0,
        severity={"MILD": 0.25, "MODERATE": 0.55, "SEVERE": 0.90}[severity],
        temporal_profile=profile,
        params={"headway_multiplier": ARRIVAL_HEADWAY_MULTIPLIER[severity]},
    )


def build_equipment_degradation(
    *, scenario_id: str, station_id: str, severity: str, profile: str, start_time: float
) -> ScenarioDefinition:
    severity = _validate_severity(severity)
    profile = profile.upper()
    if profile not in DEGRADATION_PROFILES:
        raise ValueError(f"unsupported degradation profile {profile}")
    multiplier = {"MILD": 1.25, "MODERATE": 1.50, "SEVERE": 1.85}[severity]
    return ScenarioDefinition(
        scenario_id=scenario_id,
        family=ScenarioFamily.EQUIPMENT_DEGRADATION,
        station_ids=[station_id],
        start_time=start_time,
        duration=DEGRADATION_DURATION_MINUTES[severity] * 60.0,
        severity={"MILD": 0.25, "MODERATE": 0.55, "SEVERE": 0.90}[severity],
        temporal_profile=profile,
        params={
            "max_cycle_time_multiplier": multiplier,
            "max_noise_multiplier": {"MILD": 1.25, "MODERATE": 1.75, "SEVERE": 2.50}[severity],
            "intermittent_period_seconds": 600.0,
            "intermittent_duty_cycle": 0.5,
        },
    )


def expected_micro_stop_service_seconds(base_service_seconds: float, severity: str) -> float:
    severity = _validate_severity(severity)
    params = MICRO_STOP_PARAMETERS[severity]
    mean_duration = (params["min_duration_seconds"] + params["max_duration_seconds"]) / 2.0
    return base_service_seconds * (
        1.0 + params["rate_per_processing_minute"] * mean_duration / 60.0
    )
