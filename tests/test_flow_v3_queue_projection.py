"""Section 21: the queue/digital-twin projection layer. This is the ONLY
Flow-v3 layer allowed to read occupancy/capacity -- these tests exercise
its deterministic queueing arithmetic and risk-level thresholds directly."""

from __future__ import annotations

from backend.flow_v3.queue_projection import project_queue_risk


def test_service_meets_or_exceeds_demand_is_normal_with_no_onset():
    result = project_queue_risk(
        current_occupancy=1, buffer_capacity=4, arrival_rate_vph=30.0, predicted_service_rate_vph=35.0,
    )
    assert result.risk_level == "NORMAL"
    assert result.service_deficit_vph < 0
    assert result.time_to_blocking_minutes is None
    assert result.predicted_onset_min is None and result.predicted_onset_max is None


def test_already_full_is_critical_regardless_of_deficit_sign():
    result = project_queue_risk(
        current_occupancy=4, buffer_capacity=4, arrival_rate_vph=20.0, predicted_service_rate_vph=25.0,
    )
    assert result.risk_level == "CRITICAL"


def test_large_deficit_with_low_headroom_is_critical_or_high():
    result = project_queue_risk(
        current_occupancy=3, buffer_capacity=4, arrival_rate_vph=60.0, predicted_service_rate_vph=20.0,
    )
    assert result.risk_level in {"HIGH", "CRITICAL"}
    assert result.time_to_blocking_minutes is not None
    assert result.time_to_blocking_minutes >= 0


def test_deterministic_projection_without_variability_gives_degenerate_interval():
    result = project_queue_risk(
        current_occupancy=2, buffer_capacity=4, arrival_rate_vph=50.0, predicted_service_rate_vph=30.0,
    )
    assert result.predicted_onset_min == result.predicted_onset_max == result.time_to_blocking_minutes


def test_stochastic_projection_produces_an_interval_not_a_point():
    result = project_queue_risk(
        current_occupancy=2, buffer_capacity=4, arrival_rate_vph=50.0, predicted_service_rate_vph=30.0,
        service_rate_std_vph=8.0, seed=42,
    )
    assert result.predicted_onset_min is not None and result.predicted_onset_max is not None
    assert result.predicted_onset_min <= result.predicted_onset_max


def test_result_serializes_with_expected_frontend_keys():
    result = project_queue_risk(
        current_occupancy=2, buffer_capacity=4, arrival_rate_vph=50.0, predicted_service_rate_vph=30.0,
    )
    payload = result.as_dict()
    for key in ("riskLevel", "arrivalRate", "predictedServiceRate", "serviceDeficit",
                "predictedOnsetMin", "predictedOnsetMax", "bufferOccupancy", "bufferCapacity"):
        assert key in payload
