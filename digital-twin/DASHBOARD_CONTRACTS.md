# Dashboard Contracts — Bottleneck + Defect Streams

The backend intentionally publishes **two separate prediction streams**. Do not merge them into one backend record. The dashboard should consume both against the same simulator clock.

## 1. Files / streams

- `bottleneck_predictions.jsonl` — station bottleneck risk from the selected XGBoost model.
- `defect_predictions.jsonl` — per-vehicle defect risk from the selected CatBoost model.
- `system_health.json` — dual-runtime health and synchronization status.
- `system_run_manifest.json` — immutable summary of a completed coordinated run.

The coordinated launcher writes these under the chosen `--output-dir`.

## 2. Synchronization rule

Both prediction streams share:

- `run_id`
- `timestamp_ms` on the simulator clock
- `station_id`
- vehicle identity (`vehicle_id` for bottlenecks, `unit_id` for defects)

**Do not require a one-to-one timestamp join.** The two models have different prediction triggers. Maintain each stream independently and, for a dashboard panel, display the latest valid prediction at or before the displayed simulator time. Use unit/station identity when the UI is scoped to a specific vehicle or station.

A practical state store is:

- bottleneck: latest prediction by `(run_id, station_id)` and optionally `(run_id, vehicle_id, station_id)`
- defect: latest prediction by `(run_id, unit_id)` and `(run_id, unit_id, station_id)`

Never combine records from different `run_id` values.

## 3. Bottleneck prediction contract

Schema: `bottleneck-prediction-v1`.

Core display fields:

- `run_id`
- `timestamp_ms`
- `station_id`
- `vehicle_id`
- `zone` — `LIGHT` or `DARK`
- `route` — normally `LIGHT`, `DARK_SINGLE`, or `DARK_CORRIDOR`
- `prediction_trigger`
- `bottleneck_probability` — 0..1
- `bottleneck_risk_percent` — probability × 100
- `warning`
- `decision_threshold`
- `decision_threshold_percent`
- `state_confidence` — direct LIGHT state is normally 1.0; DARK state may be lower because it is reconstructed

Action semantics:

`warning == (bottleneck_probability >= decision_threshold)`.

Explanation is nested under `explanation`:

- `top_drivers[]`
  - `feature`
  - `value`
  - `shap_log_odds`
  - `direction` (`increases_risk` / `decreases_risk`)
- `base_margin`
- `explained_probability`
- `probability_additivity_error`
- `best_iteration_explained`

`diagnostics.unknown_categories` must be empty in a valid production prediction.

## 4. Defect prediction contract

Schema: `defect-prediction-v2`.

Core display fields:

- `run_id`
- `timestamp_ms`
- `unit_id`
- `station_id`
- `station_index`
- `final_inspection_station`
- `route` — `LIGHT` or `DARK_INFERRED`
- `prediction_trigger`
- `data_source`
- `state_confidence`
- `defect_probability` — reported probability, 0..1
- `defect_risk_percent` — probability × 100
- `raw_defect_probability`
- `alert_policy`
- `alert_policy_score`
- `decision_threshold`
- `threshold_crossed`
- `warning`

### Important defect warning semantics

`threshold_crossed` means the frozen alert-policy score crossed the model's decision threshold.

`warning` is the **actionable runtime alert**. It is intentionally suppressed when the vehicle has already reached the final inspection station. Therefore a final-inspection record can legally have:

- high `defect_probability`
- `threshold_crossed = true`
- `warning = false`

For dashboard status/badges, use **`warning`**. Show `threshold_crossed` only as a diagnostic/model state if useful.

If the frozen alert policy is an EMA or multi-observation policy, `alert_policy_score` may differ from the single-row probability. Do not recompute the alert yourself; use `warning` and the supplied policy fields.

Defect explanation fields are top-level:

- `explanation_available`
- `explanation_method`
- `shap_value_space`
- `shap_base_value_raw`
- `shap_reconstructed_probability`
- `shap_probability_reconstruction_error`
- `top_risk_drivers[]`
- `top_protective_drivers[]`

Each driver includes a feature name, human-readable label, feature value, SHAP value, absolute SHAP magnitude, and effect direction.

## 5. DARK-zone interpretation

DARK membership comes from the simulator/factory DARK-zone contract (`dz.csv`), **not** from `sensor_coverage`.

- Bottlenecks reconstruct hidden station state through the validated DARK particle-filter path.
- Defects independently reconstruct vehicle station progression and causally associate observable sensor/manual evidence.
- RFID and POWER_DRAW remain observable when allowed by the DARK-zone contract.
- Hidden internal DARK `UNIT_ARRIVED`, `PROCESSING_STARTED`, and `PROCESSING_COMPLETED` truth is not exposed to either model.

For the UI, label a low `state_confidence` clearly rather than treating a DARK estimate as direct telemetry.

## 6. System health contract

`system_health.json` is the source for a top-level backend health indicator. Key concepts:

- `overall_status`
- simulator status / input clock summary
- bottleneck process status
- defect process status
- selected bottleneck model
- selected defect model
- validation summary for both output streams
- synchronization checks

Only show the coordinated system as healthy when `overall_status == "PASS"`.

## 7. Recommended dashboard behavior

For each station card:

- latest bottleneck risk/status/confidence and top drivers
- number of vehicles currently associated with that station if the simulator UI supplies it

For each vehicle card:

- latest defect risk/status/confidence and top drivers
- current/last inferred station
- optionally the bottleneck risk of that station as a separate station-level signal

Keep the labels distinct: **bottleneck risk is a station/flow risk; defect risk is a vehicle-quality risk.** Do not average or combine the two probabilities.


## 9. Degraded-mode health and DARK transition timing

Live dual operation defaults to fault isolation. `system_health.json` may report
`overall_status = DEGRADED` with one subsystem marked `FAILED_ISOLATED`. The dashboard
should keep rendering the healthy prediction stream and show the failed subsystem as
unavailable/stale; it must not fabricate missing predictions. The simulator remains
independent and continues running.

For `DARK_INFERRED` defect predictions, the timing compatibility fields remain in the
schema:

- `timestamp_ms`: online event time used by the feature runtime.
- `estimated_transition_time_ms`: PF transition estimate for an emitted causal event.
- `transition_confirmation_lag_ms`: compatibility/diagnostic field; accepted prototype
  events normally have zero lag.

Prototype stale-event rule: if later RFID/POWER/SENSOR evidence makes the PF revise a
transition into the already-processed past, that retrospective transition is **not
emitted as a prediction event**. The evidence may still update the PF's current state.
This keeps the online feature stream monotonic without replaying or rewriting history.
