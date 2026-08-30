"""Trust intelligence service (Part F): wraps data-state classification,
virtual-sensor fallback, and trust-level computation into one call."""

from __future__ import annotations

from typing import Dict, Optional

from backend.trust.data_state import classify_data_state
from backend.trust.trust_level import compute_trust_level
from backend.trust.virtual_sensor import estimate_virtual_sensor_value


class TrustService:
    def __init__(self, sensor_models: Dict):
        self.sensor_models = sensor_models

    def assess(
        self,
        station_id: str,
        sensor_name: str,
        station_type: str,
        has_direct_reading: bool,
        evidence_age_seconds: Optional[float],
        recent_readings_by_station: Dict,
        recent_readings_by_type: Dict,
        n_supporting_signals: int = 1,
    ) -> Dict:
        est_value, method, reliable = (None, None, False)
        if not has_direct_reading:
            est_value, method, reliable = estimate_virtual_sensor_value(
                station_id, sensor_name, station_type,
                recent_readings_by_station, recent_readings_by_type, self.sensor_models,
            )

        state = classify_data_state(
            has_direct_reading=has_direct_reading, evidence_age_seconds=evidence_age_seconds,
            inference_available=est_value is not None, inference_method=method, inference_reliable=reliable,
        )

        live_fraction = 1.0 if state.data_state == "LIVE" else 0.0
        inferred_fraction = 1.0 if state.data_state == "INFERRED" else 0.0
        unknown_fraction = 1.0 if state.data_state == "UNKNOWN" else 0.0

        trust = compute_trust_level(
            live_fraction=live_fraction, inferred_fraction=inferred_fraction, unknown_fraction=unknown_fraction,
            freshness_seconds=evidence_age_seconds, n_supporting_signals=n_supporting_signals,
        )

        return {
            "data_state": state.data_state,
            "inference_method": state.inference_method,
            # A static operational baseline may remain an internal prior, but
            # UNKNOWN must not expose it as a current measurement estimate.
            "estimated_value": est_value if state.data_state != "UNKNOWN" else None,
            "trust_level": trust.trust_level,
            "trust_reasons": trust.reasons,
        }
