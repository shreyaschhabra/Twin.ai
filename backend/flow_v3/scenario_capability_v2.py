"""Physics-only capability matrix for implemented Flow-v3 scenarios."""

from __future__ import annotations

from backend.config.schemas import FactoryConfig
from backend.flow_v3.capacity_audit import DEFAULT_VARIANT_MIX, build_capacity_audit, variant_service_time
from backend.flow_v3.scenario_physics import (
    ARRIVAL_DURATION_MINUTES,
    ARRIVAL_HEADWAY_MULTIPLIER,
    ARRIVAL_PROFILES,
    DEGRADATION_DURATION_MINUTES,
    DEGRADATION_PROFILES,
    MANUAL_CANDIDATES,
    MANUAL_DURATION_MINUTES,
    MANUAL_PROFILES,
    MICRO_STOP_CANDIDATES,
    MICRO_STOP_DURATION_MINUTES,
    MICRO_STOP_PARAMETERS,
    MICRO_STOP_PROFILES,
    PROVISIONAL_HEADWAY_SECONDS,
    SEVERITY_ORDER,
    manual_cycle_multiplier,
)
from backend.historical.shift_scheduler import FAMILY_STATION_POOLS
from backend.simulation.engine import DEFAULT_ENTRY_BUFFER_CAPACITY
from backend.simulation.scenarios.config import ScenarioFamily

PROFILE_AVERAGE_FRACTION = {
    "STEP": 1.0,
    "GRADUAL": 0.75,
    "RECOVERING": 0.70,
    "STEP_BURST": 1.0,
    "RAMP_BURST": 0.875,
    "ACCELERATING": 1.0 / 3.0,
    "INTERMITTENT": 0.5,
    "SUSTAINED_MIX": 1.0,
}
SEVERITY_VALUE = {"MILD": 0.25, "MODERATE": 0.55, "SEVERE": 0.90}
MIX_SHIFT_INTENSITY = {"MILD": 0.25, "MODERATE": 0.60, "SEVERE": 0.90}
MIX_DURATION_MINUTES = {"MILD": 30.0, "MODERATE": 45.0, "SEVERE": 60.0}


def _inbound_capacity(config: FactoryConfig, station_id: str) -> int:
    capacities = [buffer.capacity for buffer in config.buffers.values() if buffer.downstream_station == station_id]
    return min(capacities) if capacities else DEFAULT_ENTRY_BUFFER_CAPACITY


def _classification(expected_rho: float, peak_rho: float) -> str:
    if peak_rho < 0.90:
        return "INCAPABLE"
    if peak_rho < 1.0:
        return "HARD_NEGATIVE"
    if expected_rho < 1.05:
        return "BORDERLINE"
    return "POSITIVE_CAPABLE"


def _base_row(audit: dict, mechanism: str, severity: str, profile: str, duration_minutes: float, buffer_capacity: int) -> dict:
    return {
        "station_id": audit["station_id"],
        "station_name": audit["station_name"],
        "zone": audit["zone"],
        "station_type": audit["station_type"],
        "mechanism": mechanism,
        "supervision_role": "UNSEEN_ONLY" if mechanism == "EQUIPMENT_DEGRADATION" else (
            "HARD_NEGATIVE" if mechanism == "VEHICLE_MIX_OVERLOAD" else "SUPERVISED"
        ),
        "severity": severity,
        "severity_value": SEVERITY_VALUE[severity],
        "profile": profile,
        "baseline_rho": audit["nominal_utilization_rho"],
        "scenario_duration_minutes": duration_minutes,
        "scenario_duration_station_cycles": duration_minutes * 60.0 / audit["mix_weighted_service_time_seconds"],
        "buffer_capacity": buffer_capacity,
        "buffer_used_to_determine_capability": False,
    }


def _finish(row: dict, expected_service: float, expected_arrival_rate: float, peak_rho: float) -> dict:
    service_capacity = 3600.0 / expected_service
    deficit = expected_arrival_rate - service_capacity
    row.update({
        "expected_effective_service_time_seconds": expected_service,
        "expected_arrival_rate_vehicles_per_hour": expected_arrival_rate,
        "expected_service_capacity_vehicles_per_hour": service_capacity,
        "effective_rho": expected_arrival_rate / service_capacity,
        "peak_effective_rho": peak_rho,
        "expected_demand_service_deficit_vehicles_per_hour": deficit,
        "theoretical_time_to_fill_minutes_if_deficit_persists": (
            row["buffer_capacity"] / deficit * 60.0 if deficit > 0 else None
        ),
    })
    row["classification"] = _classification(row["effective_rho"], peak_rho)
    return row


def _mix_values(config: FactoryConfig, audit: dict, severity: str) -> tuple[float, float, float, str]:
    station_id = audit["station_id"]
    services = {
        variant_id: variant_service_time(config, station_id, variant_id)
        for variant_id in config.vehicle_variants
    }
    visiting = {variant_id: value for variant_id, value in services.items() if value is not None}
    highest = max(visiting, key=visiting.get)
    intensity = MIX_SHIFT_INTENSITY[severity]
    mix = {
        variant_id: (1 - intensity) * DEFAULT_VARIANT_MIX[variant_id]
        + intensity * (1.0 if variant_id == highest else 0.0)
        for variant_id in services
    }
    visit_probability = sum(mix[v] for v, service in services.items() if service is not None)
    workload = sum(mix[v] * (services[v] or 0.0) for v in services)
    expected_service = workload / visit_probability
    arrival_rate = 3600.0 / PROVISIONAL_HEADWAY_SECONDS * visit_probability
    rho = workload / PROVISIONAL_HEADWAY_SECONDS
    return expected_service, arrival_rate, rho, highest


def build_scenario_capability_matrix_v2(config: FactoryConfig) -> list[dict]:
    audits = {row["station_id"]: row for row in build_capacity_audit(config, PROVISIONAL_HEADWAY_SECONDS)}
    rows: list[dict] = []

    for station_id in MANUAL_CANDIDATES:
        audit = audits[station_id]
        for severity in SEVERITY_ORDER:
            maximum = manual_cycle_multiplier(config, station_id, severity)
            for profile in MANUAL_PROFILES:
                fraction = PROFILE_AVERAGE_FRACTION[profile]
                expected_multiplier = 1.0 + fraction * (maximum - 1.0)
                row = _base_row(audit, "MANUAL_VARIATION", severity, profile, MANUAL_DURATION_MINUTES[severity], _inbound_capacity(config, station_id))
                row["physical_parameter"] = f"peak_cycle_multiplier={maximum:.4f}; profile_average_fraction={fraction:.4f}"
                rows.append(_finish(
                    row,
                    audit["mix_weighted_service_time_seconds"] * expected_multiplier,
                    audit["nominal_station_arrival_rate_vehicles_per_hour"],
                    audit["nominal_utilization_rho"] * maximum,
                ))

    for station_id in MICRO_STOP_CANDIDATES:
        audit = audits[station_id]
        for severity in SEVERITY_ORDER:
            params = MICRO_STOP_PARAMETERS[severity]
            mean_duration = (params["min_duration_seconds"] + params["max_duration_seconds"]) / 2.0
            peak_multiplier = 1.0 + params["rate_per_processing_minute"] * mean_duration / 60.0
            for profile in MICRO_STOP_PROFILES:
                fraction = PROFILE_AVERAGE_FRACTION[profile]
                expected_multiplier = 1.0 + fraction * (peak_multiplier - 1.0)
                row = _base_row(audit, "MICRO_STOPS", severity, profile, MICRO_STOP_DURATION_MINUTES[severity], _inbound_capacity(config, station_id))
                row["physical_parameter"] = (
                    f"rate_per_work_minute={params['rate_per_processing_minute']:.3f}; "
                    f"duration_uniform={params['min_duration_seconds']:.1f}-{params['max_duration_seconds']:.1f}s; "
                    f"profile_average_fraction={fraction:.4f}"
                )
                rows.append(_finish(
                    row,
                    audit["mix_weighted_service_time_seconds"] * expected_multiplier,
                    audit["nominal_station_arrival_rate_vehicles_per_hour"],
                    audit["nominal_utilization_rho"] * peak_multiplier,
                ))

    for audit in audits.values():
        for severity in SEVERITY_ORDER:
            target = ARRIVAL_HEADWAY_MULTIPLIER[severity]
            for profile in ARRIVAL_PROFILES:
                fraction = PROFILE_AVERAGE_FRACTION[profile]
                expected_headway_multiplier = 1.0 - fraction * (1.0 - target)
                arrival_rate = audit["nominal_station_arrival_rate_vehicles_per_hour"] / expected_headway_multiplier
                row = _base_row(audit, "ARRIVAL_BURST", severity, profile, ARRIVAL_DURATION_MINUTES[severity], _inbound_capacity(config, audit["station_id"]))
                row["physical_parameter"] = f"peak_headway_multiplier={target:.3f}; expected_headway_multiplier={expected_headway_multiplier:.3f}"
                rows.append(_finish(
                    row,
                    audit["mix_weighted_service_time_seconds"],
                    arrival_rate,
                    audit["nominal_utilization_rho"] / target,
                ))

            expected_service, arrival_rate, rho, highest = _mix_values(config, audit, severity)
            row = _base_row(audit, "VEHICLE_MIX_OVERLOAD", severity, "SUSTAINED_MIX", MIX_DURATION_MINUTES[severity], _inbound_capacity(config, audit["station_id"]))
            row["physical_parameter"] = f"shift_to_actual_highest_workload_variant={MIX_SHIFT_INTENSITY[severity]:.2f}; variant={highest}"
            rows.append(_finish(row, expected_service, arrival_rate, rho))

    for station_id in FAMILY_STATION_POOLS[ScenarioFamily.EQUIPMENT_DEGRADATION]:
        audit = audits[station_id]
        for severity in SEVERITY_ORDER:
            maximum = {"MILD": 1.25, "MODERATE": 1.50, "SEVERE": 1.85}[severity]
            for profile in DEGRADATION_PROFILES:
                fraction = PROFILE_AVERAGE_FRACTION[profile]
                expected_multiplier = 1.0 + fraction * (maximum - 1.0)
                row = _base_row(audit, "EQUIPMENT_DEGRADATION", severity, profile, DEGRADATION_DURATION_MINUTES[severity], _inbound_capacity(config, station_id))
                row["physical_parameter"] = f"peak_cycle_multiplier={maximum:.3f}; profile_average_fraction={fraction:.4f}"
                rows.append(_finish(
                    row,
                    audit["mix_weighted_service_time_seconds"] * expected_multiplier,
                    audit["nominal_station_arrival_rate_vehicles_per_hour"],
                    audit["nominal_utilization_rho"] * maximum,
                ))

    return rows
