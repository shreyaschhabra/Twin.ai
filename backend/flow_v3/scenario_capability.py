"""Pre-pilot physical scenario-capability matrix for the rebalanced line.

No labels or simulation outcomes are used.  EQUIPMENT_DEGRADATION remains
marked as unseen, and ARRIVAL_BURST is explicitly a provisional Phase-D
equation that has not yet been added to the simulator.
"""

from __future__ import annotations

from backend.config.schemas import FactoryConfig
from backend.flow_v3.capacity_audit import DEFAULT_VARIANT_MIX, build_capacity_audit, variant_service_time

SEVERITIES = {"mild": 0.25, "moderate": 0.50, "severe": 0.80}
MECHANISMS = (
    "MANUAL_VARIATION",
    "MICRO_STOPS",
    "VEHICLE_MIX_OVERLOAD",
    "ARRIVAL_BURST",
    "EQUIPMENT_DEGRADATION_UNSEEN",
)


def _micro_extra(severity: float) -> float:
    probability = 0.20 + 0.65 * severity
    maximum = 15.0 + 75.0 * severity
    return probability * (8.0 + maximum) / 2.0


def _applicable(station_type: str, mechanism: str) -> bool:
    is_manual = station_type == "MANUAL_ASSEMBLY"
    if mechanism == "MANUAL_VARIATION":
        return is_manual
    if mechanism in {"MICRO_STOPS", "EQUIPMENT_DEGRADATION_UNSEEN"}:
        return not is_manual
    return True


def _classify(applicable: bool, severe_rho: float) -> str:
    if not applicable or severe_rho < 0.90:
        return "INCAPABLE"
    if severe_rho < 1.0:
        return "HARD_NEGATIVE"
    if severe_rho < 1.05:
        return "BORDERLINE"
    return "POSITIVE-CAPABLE"


def _parameter_description(mechanism: str, label: str, severity: float) -> str:
    if mechanism == "MANUAL_VARIATION":
        return f"cycle_multiplier={1.15 + 0.5 * severity:.4f}"
    if mechanism == "MICRO_STOPS":
        return f"expected_extra_seconds_per_visit={_micro_extra(severity):.4f}"
    if mechanism == "VEHICLE_MIX_OVERLOAD":
        return f"shift_toward_actual_slowest_variant={ {'mild': 0.25, 'moderate': 0.60, 'severe': 1.0}[label]:.2f}"
    if mechanism == "ARRIVAL_BURST":
        return f"arrival_headway_multiplier={ {'mild': 0.95, 'moderate': 0.88, 'severe': 0.78}[label]:.2f}"
    return f"cycle_multiplier={1.2 + 0.8 * severity:.4f}"


def _mix_rho(config: FactoryConfig, station_id: str, headway: float, intensity: float) -> tuple[float, str]:
    station = config.stations[station_id]
    services = {
        variant_id: variant_service_time(config, station_id, variant_id)
        for variant_id in config.vehicle_variants
    }
    visiting = {variant_id: value for variant_id, value in services.items() if value is not None}
    highest = max(visiting, key=visiting.get)
    shifted = {
        variant_id: (1.0 - intensity) * DEFAULT_VARIANT_MIX[variant_id]
        + intensity * (1.0 if variant_id == highest else 0.0)
        for variant_id in config.vehicle_variants
    }
    workload = sum(shifted[variant_id] * (services[variant_id] or 0.0) for variant_id in services)
    return workload / (headway * station.capacity), highest


def build_scenario_capability_matrix(config: FactoryConfig, headways=(100.0, 102.5, 105.0)) -> list[dict]:
    rows: list[dict] = []
    for headway in headways:
        capacity = {row["station_id"]: row for row in build_capacity_audit(config, headway)}
        for station_id, station in sorted(config.stations.items()):
            baseline = capacity[station_id]["nominal_utilization_rho"]
            service = capacity[station_id]["mix_weighted_service_time_seconds"]
            visit_probability = capacity[station_id]["station_visit_probability"]
            for mechanism in MECHANISMS:
                applicable = _applicable(station.station_type, mechanism)
                rhos = {}
                highest_variant = ""
                for label, severity in SEVERITIES.items():
                    if mechanism == "MANUAL_VARIATION":
                        rhos[label] = baseline * (1.15 + 0.5 * severity)
                    elif mechanism == "MICRO_STOPS":
                        rhos[label] = (
                            baseline
                            + visit_probability * _micro_extra(severity) / (headway * station.capacity)
                        )
                    elif mechanism == "VEHICLE_MIX_OVERLOAD":
                        intensity = {"mild": 0.25, "moderate": 0.60, "severe": 1.0}[label]
                        rhos[label], highest_variant = _mix_rho(config, station_id, headway, intensity)
                    elif mechanism == "ARRIVAL_BURST":
                        headway_multiplier = {"mild": 0.95, "moderate": 0.88, "severe": 0.78}[label]
                        rhos[label] = baseline / headway_multiplier
                    else:
                        rhos[label] = baseline * (1.2 + 0.8 * severity)
                if not applicable:
                    rhos = {label: baseline for label in rhos}
                rows.append({
                    "headway_seconds": headway,
                    "station_id": station_id,
                    "station_name": station.station_name,
                    "zone": capacity[station_id]["zone"],
                    "station_type": station.station_type,
                    "mechanism": mechanism,
                    "applicable": applicable,
                    "baseline_rho": baseline,
                    "mild_severity_value": SEVERITIES["mild"],
                    "mild_physical_parameter": _parameter_description(mechanism, "mild", SEVERITIES["mild"]),
                    "mild_effective_rho": rhos["mild"],
                    "moderate_severity_value": SEVERITIES["moderate"],
                    "moderate_physical_parameter": _parameter_description(mechanism, "moderate", SEVERITIES["moderate"]),
                    "moderate_effective_rho": rhos["moderate"],
                    "severe_severity_value": SEVERITIES["severe"],
                    "severe_physical_parameter": _parameter_description(mechanism, "severe", SEVERITIES["severe"]),
                    "severe_effective_rho": rhos["severe"],
                    "classification": _classify(applicable, rhos["severe"]),
                    "highest_workload_variant": highest_variant,
                    "equation_source": (
                        "provisional Phase-D demand-side design; not yet implemented"
                        if mechanism == "ARRIVAL_BURST"
                        else "current Flow-v2 physical equation"
                    ),
                    "buffer_capacity_used_in_classification": False,
                    "notes": (
                        "UNSEEN robustness only; excluded from supervised development"
                        if mechanism == "EQUIPMENT_DEGRADATION_UNSEEN"
                        else "capacity classification uses service/demand deficit only"
                    ),
                })
    return rows
