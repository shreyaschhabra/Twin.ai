# Dark Zone -> Bottleneck ML Bridge (accuracy-calibrated final package)

## Purpose

This package keeps the existing Dark Zone estimation engine intact and fixes only the handoff into the bottleneck ML model.

**Do not replace the engine with this code.** The intended flow is:

```text
stations.csv + station_events.csv + units.csv + processing-cycle history
                    + optional corridor-residence calibration
                    + optional checkpoint / manual evidence
                                  |
                                  v
        existing DarkZoneOrchestrator / MultiStationParticleFilter
                                  |
                     current posterior state
                                  |
                                  v
                 dark_zone_ml_bridge.py
                                  |
                     station-level causal history
                                  |
                                  v
            dark_zone_feature_reconstructor.py
                                  |
                   frozen 28 model features
                                  |
                                  v
        bottleneck_model_bundle.joblib (optional inference step)
```

The estimator mathematics are frozen. Three core files remain byte-for-byte unchanged; `multi_station_tracker.py` has a behavior-preserving performance optimization:

- `orchestrator.py`
- `dark_zone_tracker.py`
- `multi_station_tracker.py`
- `persistence.py`

`dark_zone_bridge_audit.json` writes their SHA-256 hashes on every replay.

## What was fixed

### 1. Single-station state is no longer reimplemented

Every `STATION_ENTRY`, `TICK`, RFID/BLE checkpoint, power-draw event, Andon/manual check, and `STATION_EXIT` goes through the **existing `DarkZoneOrchestrator.route_event()`**. The bridge reads the resulting PF posterior; it never calls the single-station PF's `predict()` or `update()` directly.

This preserves the existing gating, physical-consistency spawn guard, evidence fusion, and—when the bridge is attached to your live orchestrator—the existing persistence/crash-recovery path.

The supplied CLI is an **offline replay harness**, so it creates an orchestrator with persistence disabled. In production, instantiate `SingleStationMLBridge` with the already-running persisted orchestrator instance instead.

### 2. Queue history is station-level, not vehicle-level

The old v2 history reset for each vehicle. This was wrong for features such as `queue_mean_10m`, `queue_delta_10m`, and `queue_slope_10m`.

The bridge now keeps one rolling 20-minute causal history **per station**. A later vehicle inherits the station's previous queue/rate/cycle context exactly as the Light-Zone feature builder does.

### 3. Light-Zone formulas and units are matched

The model-facing semantics now match the frozen Light-Zone builder:

- recent window: `[t-10m, t]`
- previous window: `[t-20m, t-10m)`
- sample standard deviation: `ddof=1`
- `UNIT_ARRIVED` = arrival event
- `PROCESSING_COMPLETED` = service event
- `flow_pressure_10m = arrivals10 - services10` **(count difference, not a ratio)**
- `net_flow_rate_10m = (arrivals10 - services10) / 10`
- `queue_slope_10m` uses milliseconds as the regression time base
- `queue_delta_10m = recent_queue_mean - previous_queue_mean`
- `station_index = numeric station number - 1`
- `line_fraction = station_index / (number_of_stations - 1)`

Use the **full line `stations.csv`**, not only the dark subset, so `line_fraction` stays in the same coordinate system used during training.

### 4. The three uncertainty features no longer mix incompatible quantities

A serious old mismatch was fixed. The trained bottleneck feature `eta_std` means uncertainty in **station time-to-capacity**, in milliseconds. The old Dark-Zone package put **vehicle time-to-exit uncertainty in seconds** into that same column.

The model-facing fields are now:

- `state_confidence`: reliability of the reconstructed queue state
- `progress_std`: queue-occupancy uncertainty, in queue units
- `eta_std`: Light-Zone delta-method propagation of queue/slope uncertainty, in milliseconds

Vehicle-local PF uncertainty is still preserved separately in `dark_zone_dashboard_state.csv` as dashboard information (`progress_std`, `eta_std`, `state_confidence`) plus explicit `model_*` fields so the two meanings cannot be confused.

### 5. Corridor queue reconstruction is line-level

The existing `MultiStationParticleFilter` mathematics are preserved. Its particle-to-station projection is vectorized/cached for performance. For each station, each active vehicle contributes its posterior probability of occupying that station. The bridge computes the Poisson-binomial WIP distribution and transforms it into waiting queue `max(WIP - 1, 0)`, giving both an expected queue and queue uncertainty.

Before a corridor snapshot, all active corridor filters are advanced to the same causal timestamp. This avoids mixing stale beliefs from different vehicles.

Corridor checkpoint/manual evidence uses the existing `update_checkpoint()` hook. No future real exit is used before it occurs.

### 6. Corridor residence is calibrated separately from processing cycle time

This is the main corridor-accuracy fix. A vehicle can spend much longer at a station than its processing cycle because it is waiting in that station's queue. The multi-station PF therefore receives an optional **residence-time prior** that includes waiting + processing, while `cycle_mean_10m`, `cycle_std_10m`, and `cycle_max_10m` continue to use processing-cycle history. The two quantities are never mixed.

The residence prior is selected causally from the number of vehicles already inside the corridor at entry. The load bins are historical calibration only; the live bridge uses only the currently observed corridor boundary registry to select a bin. No hidden current-run Light-Zone queue or future exit is used.

If no corridor-residence calibration is supplied, the bridge falls back to the ordinary processing dwell prior and deliberately lowers model-facing confidence.

### 7. Missing dwell calibration no longer blocks a corridor

Historical station/variant fits remain preferred. If a dark station has no usable historical fit, the runner creates an **explicit low-quality configuration prior** using only `base_cycle_time_ms` and `cycle_time_std_ms` from `stations.csv`.

It never learns that fallback from the future of the replay being evaluated. All fallback station IDs are reported in `dark_zone_feature_quality.json`.

### 8. The bridge can now run the saved XGBoost bundle directly

`dark_zone_model_adapter.py` loads the saved `bottleneck_model_bundle.joblib` and uses its own stored:

- feature list/order
- categorical feature list
- category levels
- selected decision threshold

Unknown categories become missing, matching training behavior. The adapter fails loudly if the model's saved feature contract is not exactly the bridge's 28-feature contract.

## Inputs

Required:

- `stations.csv` — full station configuration
- `station_events.csv` — causal boundary/event stream
- `units.csv` — `unit_id -> vehicle_model`
- `historical_dwell.csv` — earlier **processing-cycle** calibration with `station_id, variant, entry_ts, exit_ts`

Optional but strongly recommended when available:

- `corridor_residence_calibration.csv` — historical occupancy residence (`waiting + processing`) with `corridor_load`; strongly recommended for multi-station dark corridors
- `manual_checks.csv`
- `checkpoint_events.csv`
- `station_checkpoints.csv`

For the single-station queue, `UNIT_ARRIVED` is the strongest available way to reproduce the Light-Zone queue ledger. If it is unavailable, the bridge falls back to an active-registry estimate and explicitly lowers queue confidence rather than pretending it is exact.

## Step 0 — Build corridor residence calibration (recommended for multi-station corridors)

Use **prior fully observed runs only**. Do not include the run you are evaluating or any future deployment data.

```bash
python build_corridor_residence_calibration.py \
  --historical-root path/to/prior_runs \
  --sequence S12,S13,S14,S15 \
  --output corridor_residence_calibration.csv
```

The builder uses `PROCESSING_STARTED -> PROCESSING_COMPLETED` for the corridor entry station and `UNIT_ARRIVED -> PROCESSING_COMPLETED` for internal stations. It also records the causal number of vehicles already inside the corridor at entry. This makes the residence prior load-sensitive without using any hidden current-run queue measurement.

## Step 1 — Build the 28 Dark-Zone features

```bash
python run_dark_zone_feature_reconstruction.py \
  --stations path/to/stations.csv \
  --station-events path/to/station_events.csv \
  --units path/to/units.csv \
  --historical-dwell path/to/historical_dwell.csv \
  --corridor-residence path/to/corridor_residence_calibration.csv \
  --manual-checks path/to/manual_checks.csv \
  --checkpoint-events path/to/checkpoint_events.csv \
  --station-checkpoints path/to/station_checkpoints.csv \
  --output-dir dark_zone_outputs \
  --run-id RUN_ID
```

The corridor-residence argument is optional, but for a multi-station blind corridor it is strongly recommended. If omitted, the bridge stays runnable with a lower-confidence processing-dwell fallback. The optional evidence arguments can be omitted if those files do not exist. `checkpoint-events` and `station-checkpoints` must be supplied together.

## Step 2 — Run the trained bottleneck model

```bash
python run_dark_zone_model.py \
  --features dark_zone_outputs/dark_zone_bottleneck_features_28.csv \
  --model-bundle path/to/bottleneck_model_bundle.joblib \
  --output dark_zone_outputs/dark_zone_bottleneck_predictions.csv \
  --audit dark_zone_outputs/dark_zone_model_inference_audit.json
```

## Outputs

- `dark_zone_bottleneck_features_28.csv` — canonical model input: identifiers + frozen 28 features
- `dark_zone_bottleneck_features.csv` — compatibility alias
- `dark_zone_feature_events_debug.csv` — every trigger before same-station/same-time de-duplication
- `dark_zone_dashboard_state.csv` — vehicle/PF UI state, separate from model features
- `dark_zone_feature_provenance.csv` — source/method for every feature row
- `dark_zone_feature_quality.json` — missingness, infinities, fallback calibration stations
- `dark_zone_bridge_audit.json` — evidence counts, rejection counts, core-engine hashes
- `dark_zone_bottleneck_predictions.csv` — produced by the optional model step
- `dark_zone_model_inference_audit.json` — model contract/threshold/category audit

## Important: what is observed vs inferred

This bridge makes Dark-Zone features **compatible**, not magically identical to Light-Zone sensor truth.

Static configuration and visible boundary events are observed. Single-station queue is reconstructable when `UNIT_ARRIVED` + processing boundaries exist. Corridor internal queue/rates are posterior expectations. Corridor location uses historical load-conditioned **residence** priors when supplied, while cycle features use observed completed cycles when available or the separate processing-cycle prior otherwise. Provenance records these distinctions instead of hiding them.

## Tests

```bash
python test_reconstructor.py
python test_ml_bridge.py
```

These test:

- exact 28-feature order
- Light-Zone queue windows/sample std/slope units
- event-count rate formulas
- model-facing uncertainty units
- Layer 3/5 evidence routing through the existing orchestrator
- corridor checkpoint evidence
- load-conditioned corridor residence selection and separation from processing-cycle priors
- no predictions after confirmed vehicle exit
- no infinite model features
- frozen estimator file hashes match the validated optimized package

A separate serialized-XGBoost inference smoke test is also supported through `run_dark_zone_model.py` once your actual `bottleneck_model_bundle.joblib` is placed beside the project or passed by path.

## Production attachment pattern

For live use, do **not** run a second Dark Zone engine. Attach the bridge to the engine instance already consuming your event bus:

```python
bridge = SingleStationMLBridge(
    orchestrator=existing_orchestrator,
    stations=stations_df,
    dwell_models=existing_orchestrator.dwell_models,
    run_id=current_run_id,
)

# If UNIT_ARRIVED is on your event bus, feed it only to the feature ledger:
bridge.observe_unit_arrived(station_id, timestamp_ms)

# Every DarkZoneEvent still goes through the existing orchestrator exactly once:
bridge.observe_engine_event(event)
```

The offline CLI follows the same rule internally; it exists only to replay CSV files end-to-end.


## Performance regression

See `../PERFORMANCE_REGRESSION.md` for the behavior-equivalence checks, 3000-particle stress benchmarks, XGBoost smoke test, and the new frozen optimized tracker hash.
