# API Contract for Integration

This document outlines the expected inputs and outputs for the intelligence layer services. 

## TrustService
**Method**: `TrustService.assess(...)`
**Inputs**:
- `station_id` (str)
- `sensor_name` (str)
- `station_type` (str)
- `has_direct_reading` (bool)
- `evidence_age_seconds` (float)
- `recent_readings_by_station` (Dict[Tuple[str, str], list])
- `recent_readings_by_type` (Dict[Tuple[str, str], list])

**Returns**: Dict containing `data_state` ("LIVE", "INFERRED", "UNKNOWN"), `trust_level` ("HIGH", "MEDIUM", "LOW"), `trust_reasons` (List[str]), `estimated_value` (float or None), `inference_method` (str or None).

## FlowService (queue_projection)
**Method**: `project_queue_risk(...)`
**Inputs**:
- `current_occupancy` (int)
- `buffer_capacity` (int)
- `arrival_rate_vph` (float)
- `predicted_service_rate_vph` (float) - This must be the *hybrid* predicted rate from `backend.intelligence.flow_v3_service`.
- `service_rate_std_vph` (float)
- `seed` (int)

**Returns**: `QueueRiskProjection` object with attributes like `risk_level` ("NORMAL", "WATCH", "HIGH", "CRITICAL"), `projected_blocking_probability`, `time_to_blocking_seconds`.

## QualityService
**Method**: `QualityService.score_vehicle(features_dict)`
**Inputs**: A dictionary of aggregated historical features for a vehicle passing through a checkpoint station.
**Returns**: Dict containing `quality_risk` (float 0-1) and `top_contributors` (List[Dict]).

## AnomalyService
**Method**: `AnomalyService.score_station(features_dict)`
**Inputs**: A dictionary of station features (matching those used for flow training).
**Returns**: Dict containing `anomaly_score` (float), `is_anomalous` (bool), and `top_contributors` (List[Dict]).
