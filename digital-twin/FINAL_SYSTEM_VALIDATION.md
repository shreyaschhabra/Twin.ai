# Final System Validation

This report records the final validation of the streamlined simulator + bottleneck + defect system.

## Architecture validated

```text
C++ simulator
    -> one ordered public runtime_events.csv bus
        -> bottleneck consumer -> bottleneck_predictions.jsonl
        -> defect consumer     -> defect_predictions.jsonl
```

The two outputs intentionally remain separate. They are synchronized by `run_id`, simulator `timestamp_ms`, `station_id`, and unit/vehicle identity. A one-to-one prediction timestamp join is not required.

## Final regression suite

- Whole-repository Python tests: **66 passed**.
- Python compilation check: PASS.
- Current simulator core (`Simulation.cpp`, `Output.cpp`, `ObservationPolicy.cpp`) compiled directly with C++17: PASS.

The tests cover bottleneck/defect model contracts, LIGHT/DARK behavior, factory registries, training/runtime parity, causality, artifact integrity, shared live bus handling, dual-system health, synchronization, model selection, and deterministic DARK seeding.

## Fresh C++ simulator black-box run

A fresh run was generated from the **current simulator source**, not from a stored CSV fixture.

Configuration:

- 32 stations
- DARK corridor: S12-S15
- DARK sensor telemetry: enabled
- DARK manual checks: enabled
- DARK checkpoints: enabled
- identified RFID checkpoint
- anonymous POWER_DRAW checkpoint
- seed: 24680
- duration: 1,950,000 ms

Public bus output:

- records: **18,266**
  - STATION: 2,252
  - SENSOR: 15,858
  - MANUAL: 105
  - EVIDENCE: 51
- sequence: contiguous, 1-based
- timestamps: monotonically nondecreasing
- hidden S12-S15 `UNIT_ARRIVED` / `PROCESSING_STARTED` / `PROCESSING_COMPLETED` events leaked to public output: **0**
- inspection/ground-truth records leaked to public bus: **0**

## Final dual BASE-model run

The completed fresh C++ run was passed through `python cli.py system run prescribed` with both BASE models and **3,000 bottleneck corridor particles**.

Wall time for the coordinated inference/validation command: approximately **30.24 s** in this environment. Peak process-tree RSS reported by `/usr/bin/time`: approximately **261,688 KB**.

### Bottleneck result

- predictions: **2,360**
- LIGHT: 2,093
- DARK_CORRIDOR: 267
- actionable warnings: 169
- invalid probabilities: 0
- S01 model predictions: 0
- SHAP explanations: 2,360 / 2,360
- maximum SHAP probability additivity error: **2.693410975362909e-07**

### Defect result

- predictions: **782**
- LIGHT: 705
- DARK_INFERRED: 77
- actionable warnings: 2
- invalid probabilities: 0
- SHAP explanations: 782 / 782
- maximum CatBoost SHAP probability reconstruction error: **6.661338147750939e-16**

### Synchronization

- same `run_id`: PASS
- both outputs contained predictions within the same simulator clock window: PASS
- valid station/unit identifiers: PASS
- one-to-one timestamp join required: NO

## Deterministic replay

The same completed mixed LIGHT/DARK run was replayed twice with the same `run_id` and 3,000 particles.

- bottleneck output: **byte-for-byte identical** across runs
- defect output: **byte-for-byte identical** across runs

DARK PF mathematics was not changed. The launch/orchestration layer now supplies a stable seed derived from `run_id` when no explicit seed is provided. Factory training can still supply its own explicit seed.

## Factory-model validation

### Defect Factory A replay

A previously trained immutable defect `factory-a-final` artifact was selected for its matching completed factory run while bottlenecks used BASE.

- bottleneck: 52 predictions (28 LIGHT, 24 DARK_CORRIDOR), SHAP 52/52
- defect factory artifact: 28 predictions (12 LIGHT, 16 DARK_INFERRED), SHAP 28/28
- same run ID / simulator clock: PASS

### Safety guards

Validated protections include:

- BASE models remain protected and are the default when no pointer exists.
- Bottleneck and defect model stores/pointers are independent.
- `system models use <id>` preflights both stores before mutating both pointers.
- Runtime factory/static/DARK/checkpoint contracts are checked before inference.
- Topology mismatch causes coordinated failure rather than silent scoring.
- Artifact directory/requested ID must equal `artifact.json.model_id`; manually renamed/mislabelled artifacts are rejected.
- Defect factory training uses deployment-public replay for X and `inspection_results.csv` only for Y.
- Factory DARK calibration uses prior TRAIN runs only; validation/current runs cannot calibrate themselves.

A tiny synthetic defect Factory-A continuation test used during architecture validation is not intended as a production accuracy benchmark; real factory-specific models should be trained from sufficiently large representative factory histories.

## Defect dashboard alert semantics

`threshold_crossed` and `warning` intentionally differ at final inspection:

- `threshold_crossed`: frozen alert-policy score crossed the decision threshold.
- `warning`: actionable alert, only before final inspection.

Therefore a final-inspection prediction may have high defect probability and `threshold_crossed=true` but `warning=false`. Dashboard status should use `warning`.

## Repository cleanup

The final package removes reproducible/generated state that is not required for deployment:

- Python/pytest caches
- temporary defect `.runtime` copies
- temporary runtime-check datasets
- generated defect feature PKLs
- old prediction JSONL files
- generated simulator/CMake scratch directories
- non-production bottleneck ablation/cross-run/SHAP/calibration artifact directories
- large base `test_predictions.csv`

The production XGBoost/CatBoost assets, historical DARK calibration, training code, factory model code, tests, and compact historical validation reports remain.

## External CMake dependency limitation

The normal CMake configuration still fetches `nlohmann/json` from GitHub. This was intentionally left unchanged. The validation environment cannot perform that GitHub dependency fetch, so the current simulator core was compiled directly with C++17 for the final black-box run. No simulator logic failure was found.

## Final assessment

No known functional defect remained in the exercised production paths after the final hardening pass. This is a documented test and black-box validation result, not a mathematical guarantee that arbitrary non-trivial software can contain no undiscovered bugs.


## Post-accuracy hardening: DARK defect timestamp revisions and live fault isolation

A fresh black-box accuracy campaign exposed two defect DARK replays in which later
checkpoint evidence caused the PF to revise a station-transition estimate into the
already-processed past. The simulator public bus remained correctly ordered. For the
prototype, the DARK defect adapter now uses a deliberately simple stale-event rule:
**later evidence may update the PF's current belief, but any newly discovered transition
dated earlier than the observation that revealed it is dropped from the online defect
feature stream.** No historical prediction is replayed and the feature clock never
rewinds. A permanent regression test reproduces the original ordering shape and verifies
that the stale transition is ignored while subsequent processing remains valid.

Live dual operation now defaults to `--failure-policy isolate`. If one ML consumer
fails, the external simulator and the healthy ML consumer continue, system health is
marked `DEGRADED`, and the failed subsystem is marked `FAILED_ISOLATED`. CI and
strict validation retain fail-fast behavior. The complete regression suite is now
**68/68 PASS**. Protected model hashes remain unchanged.
