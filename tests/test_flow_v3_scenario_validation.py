from backend.flow_v3.scenario_validation import aggregate_scenario_runs


def test_aggregate_classification_is_seed_based_and_recovery_is_counted():
    rows = []
    for seed, positive in enumerate((False, True, True), 1):
        rows.append({
            "mechanism": "MICRO_STOPS", "target_station_id": "S20",
            "severity": "MODERATE", "profile": "STEP", "seed": seed,
            "real_congestion": positive, "blocked_seconds": 5.0 if positive else 0.0,
            "time_scenario_start_to_congestion_seconds": 100.0 if positive else None,
            "max_relevant_buffer_occupancy_ratio": 1.0 if positive else 0.5,
            "observable_precursor_before_congestion": positive,
            "recovered_after_scenario": True if positive else None,
        })
    aggregate = aggregate_scenario_runs(rows)[0]
    assert aggregate["outcome_class"] == "MIXED"
    assert aggregate["runs_with_real_congestion"] == 2
    assert aggregate["positive_runs_recovered"] == 2
