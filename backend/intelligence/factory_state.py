"""
Canonical intelligence output objects (Sections 37-39). No HTTP -- these
are plain Python dicts, directly JSON-serializable, meant to be consumed
later by an API/frontend developer.
"""

from __future__ import annotations

from typing import Dict, List, Optional


def build_station_object(
    station_id: str,
    operation: str,
    zone: str,
    bottleneck_risk: float,
    status: str,
    predicted_onset_min: Optional[float],
    predicted_onset_max: Optional[float],
    cycle_time: Optional[float],
    baseline_cycle_time: float,
    buffer_occupancy: Optional[float],
    buffer_capacity: Optional[float],
    arrivals_per_min: Optional[float],
    departures_per_min: Optional[float],
    data_state: str,
    trust_level: str,
    evidence: List[Dict],
) -> Dict:
    return {
        "station_id": station_id,
        "operation": operation,
        "zone": zone,
        "status": status,
        "bottleneck_risk": round(bottleneck_risk, 4) if bottleneck_risk is not None else None,
        "predicted_onset_min": predicted_onset_min,
        "predicted_onset_max": predicted_onset_max,
        "cycle_time": cycle_time,
        "baseline_cycle_time": baseline_cycle_time,
        "buffer_occupancy": buffer_occupancy,
        "buffer_capacity": buffer_capacity,
        "arrivals_per_min": arrivals_per_min,
        "departures_per_min": departures_per_min,
        "data_state": data_state,
        "trust_level": trust_level,
        "evidence": evidence,
    }


def build_vehicle_object(
    vehicle_id: str,
    variant: str,
    current_station: Optional[str],
    quality_risk: float,
    risk_level: str,
    data_state: str,
    trust_level: str,
    evidence: List[Dict],
    final_qc: Optional[str] = None,
) -> Dict:
    return {
        "vehicle_id": vehicle_id,
        "variant": variant,
        "current_station": current_station,
        "quality_risk": round(quality_risk, 4) if quality_risk is not None else None,
        "risk_level": risk_level,
        "data_state": data_state,
        "trust_level": trust_level,
        "evidence": evidence,
        "final_qc": final_qc,
    }


ALERT_TYPES = {"FLOW", "QUALITY", "DATA"}


def build_alert(
    alert_type: str,
    severity: str,
    station_id: Optional[str],
    title: str,
    description: str,
    risk: Optional[float],
    trust_level: str,
    data_state: str,
) -> Dict:
    assert alert_type in ALERT_TYPES, f"unsupported alert type {alert_type}"
    return {
        "type": alert_type,
        "severity": severity,
        "station_id": station_id,
        "title": title,
        "description": description,
        "risk": round(risk, 4) if risk is not None else None,
        "trust_level": trust_level,
        "data_state": data_state,
    }
