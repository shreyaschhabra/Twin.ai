# Corridor feature-accuracy probe

This is an engineering accuracy probe, not a claim that Dark-Zone inference equals Light-Zone sensor truth.

## Method

- Core Dark Zone engine unchanged.
- Internal S12-S15 station events hidden from the bridge.
- Only corridor boundaries plus available RFID/manual evidence were supplied.
- Corridor residence calibration was learned only from earlier runs.
- The bridge selected residence priors using the causal number of vehicles already inside the corridor at entry.
- Reconstructed 28-feature rows were compared against full-visibility Light-Zone feature truth at the same station/time.
- Benchmark used 200 corridor particles for speed; production default remains 3000.

## Held-out results

| Run | Vehicles | current_occupancy MAE | Spearman | Within ±1 | queue_mean MAE | queue_mean Spearman |
|---|---:|---:|---:|---:|---:|---:|
| train_196_multi_mixed | 150 | 0.598 | 0.873 | 78.7% | 0.402 | 0.864 |
| train_197_multi_mixed | 100 | 0.494 | 0.863 | 86.7% | 0.264 | 0.813 |
| train_198_multi_hard | 100 | 0.603 | 0.899 | 75.7% | 0.441 | 0.841 |

Other useful held-out behavior:

- `queue_max_10m` Spearman: ~0.91-0.92 on the tested later runs.
- recent arrival-rate MAE: ~0.04 events/min.
- recent service-rate MAE: ~0.06-0.07 events/min on runs 197-198.
- processing-cycle mean error: ~1.8-2.0 seconds with ~0.81-0.84 Spearman.

## Confidence is intentionally not made artificially high

On the 196 probe, model-facing `state_confidence` averaged about 0.39. Confidence combines posterior queue spread with historical calibration quality. A missing or coarse corridor-residence calibration receives an explicit penalty rather than pretending the inferred queue is directly observed.

## Remaining limitations

- S15 can still receive small false downstream WIP when particles spread across the final boundary.
- Service-rate correlation is weaker than queue occupancy because internal completion times are inferred rather than directly observed.
- `eta_std` can become large when queue slope is positive but very close to zero; this follows the frozen Light-Zone delta-method semantics and should be monitored against the training distribution.
- Accuracy depends on historical calibration covering operating loads and variants seen in deployment.
