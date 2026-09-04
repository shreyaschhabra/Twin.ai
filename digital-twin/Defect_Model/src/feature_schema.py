RECENT_MS = 600_000  # exactly 10 minutes

DEFECT_FEATURES = [
    'torque_delta_recent_vs_history',
    'manual_fail_count_cum',
    'prediction_station_index',
    'torque_mean_history',
    'line_fraction',
    'last_manual_fail',
    'manual_check_count_cum',
    'torque_mean_recent',
    'queue_history_mean',
    'current_mean_recent',
    'current_missing_recent',
    'vibration_delta_recent_vs_history',
    'current_mean_history',
    'torque_max_recent',
    'temperature_mean_history',
    'torque_max_history',
    'supplier_batch',
    'current_max_history',
    'cycle_history_max',
    'temperature_max_recent',
    'vibration_mean_history',
    'temperature_max_history',
    'stations_since_last_manual_fail',
    'vehicle_model',
    'vibration_max_history',
    'vibration_max_recent',
    'temperature_mean_recent',
    'torque_std_history',
    'queue_history_std',
    'cycle_history_std',
]

CATEGORICAL_FEATURES = ['supplier_batch', 'vehicle_model']
TARGET_COLUMN = 'y_defect'

META_COLUMNS = [
    'split',
    'run_id',
    'unit_id',
    'prediction_station',
    'prediction_time',
    'prediction_event_sequence',
    'label_completeness_status',
    'final_station_index',
]

assert len(DEFECT_FEATURES) == 30, f'Expected 30 features, got {len(DEFECT_FEATURES)}'
assert len(set(DEFECT_FEATURES)) == 30, 'Duplicate feature names detected'
assert TARGET_COLUMN not in DEFECT_FEATURES
assert all(c in DEFECT_FEATURES for c in CATEGORICAL_FEATURES)
