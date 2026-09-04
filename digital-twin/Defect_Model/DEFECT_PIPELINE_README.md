# Finalized V5 Defect Runtime Pipeline

This bundle mirrors the architecture of the bottleneck runtime pipeline, but it is
built specifically for the finalized defect model and contains **no Dark Zone**.

## Frozen model

The pipeline expects the existing finalized V5 artifacts:

- `saved_models/defect_v5_models.joblib`
- `saved_models/defect_v5_config.json`
- `saved_models/defect_v5_calibrator.joblib`
- `src/feature_schema.py`

It does not retrain or retune anything.

## Runtime flow

```text
stations.csv + units.csv
        |
        +------------------------------+
        |                              |
station_events                  sensor_readings
        |                              |
        |                     assign to active
        |                     processing interval
        |                              |
        +----------+-------------------+
                   |
              manual_checks
                   |
                   v
       DefectRuntimeFeatureBuilder
                   |
        exact V5 30 causal features
                   |
                   v
          DefectModelRuntime
                   |
          frozen CatBoost V5
                   |
                   v
           DefectPrediction
                   |
                   v
             dashboard/API
```

## What is deliberately excluded

- Dark Zone
- corridor reconstruction
- particle filters
- bottleneck features
- `inspection_results.csv` during inference
- any future target information
- retraining
- calibration fitting
- threshold selection

## Prediction trigger

A prediction is emitted on `UNIT_ARRIVED` at each station up to and including the
final INSPECTION station.

The operational `warning` field is emitted only before the final inspection
station, matching the pre-final warning rule used when V5's threshold was selected.
The final-station probability is still returned.

## V5 sensor causality

`sensor_readings.csv` does not identify the unit. Runtime therefore tracks
`PROCESSING_STARTED` / `PROCESSING_COMPLETED` intervals.

A sensor reading:

1. is attached to the unit being processed at that station;
2. remains buffered while processing is active;
3. becomes available to future predictions only after `PROCESSING_COMPLETED`.

This is the same corrected unit-specific sensor meaning used by V5 training.

## Files

Copy these into the root of your cleaned defect project:

```text
defect_main.py

runtime/
    __init__.py
    defect_feature_runtime.py
    defect_pipeline.py

ml/
    __init__.py
    defect_model_runtime.py

output/
    __init__.py
    defect_prediction_output.py
```

Your existing `src/`, `saved_models/`, `generated_features_v5/`, and `results/`
folders stay untouched.

## Live integration contract

Each input record must contain a `stream` field.

Station event:

```json
{
  "stream": "station_event",
  "event_id": "E1",
  "timestamp_ms": 1000,
  "event_type": "UNIT_ARRIVED",
  "station_id": "S10",
  "unit_id": "U123",
  "queue_length_after": 2,
  "cycle_time_ms": null
}
```

Sensor reading:

```json
{
  "stream": "sensor_reading",
  "timestamp_ms": 1010,
  "station_id": "S10",
  "sensor_type": "TORQUE",
  "value": 43.8
}
```

Manual check:

```json
{
  "stream": "manual_check",
  "timestamp_ms": 1200,
  "station_id": "S10",
  "unit_id": "U123",
  "result": "PASS"
}
```

The three live streams must be supplied in nondecreasing timestamp order.

## Integration entry point

```python
from defect_main import build_pipeline

pipeline = build_pipeline(
    stations_csv="stations.csv",
    units_csv="units.csv",
)

predictions = pipeline.process_record(record)
```

Do not use `inspection_results.csv` in the runtime path.
