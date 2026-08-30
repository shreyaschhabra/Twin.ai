# Flow-v3 nominal headway selection

## Sweep design

- Candidates: 115.0, 112.5, 110.0, 107.5, 105.0, 102.5, 100.0 seconds
- Healthy independent seeds per candidate: 5
- Vehicles per run: 450
- Inter-arrival standard deviation: 15.0 seconds
- No scenarios, sensors, QC recalibration, cycle-time changes, buffer changes, labels, or ML metrics were used.

## Aggregate results

| Headway | Max rho | Headroom <65% | Moderate 65–75% | Sensitive 75–95% | Runs blocked | Mean blocked s | Max-buffer p95 queue | Event p95 queue | Steady throughput/h | Headway CV |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 115.0 | 0.788 | 42 | 2 | 1 | 0/5 | 0.0 | 0.250 | 0.250 | 31.32 | 0.387 |
| 112.5 | 0.806 | 42 | 2 | 1 | 0/5 | 0.0 | 0.250 | 0.250 | 32.02 | 0.384 |
| 110.0 | 0.824 | 42 | 2 | 1 | 0/5 | 0.0 | 0.250 | 0.250 | 32.75 | 0.382 |
| 107.5 | 0.843 | 41 | 3 | 1 | 0/5 | 0.0 | 0.250 | 0.250 | 33.51 | 0.379 |
| 105.0 | 0.863 | 41 | 3 | 1 | 0/5 | 0.0 | 0.250 | 0.250 | 34.32 | 0.375 |
| 102.5 | 0.884 | 40 | 3 | 2 | 0/5 | 0.0 | 0.250 | 0.250 | 35.16 | 0.371 |
| 100.0 | 0.906 | 38 | 4 | 3 | 0/5 | 0.0 | 0.350 | 0.250 | 36.01 | 0.366 |

## Decision

No candidate produces the preferred 6–10 sensitive and 10–12 moderate stations without further design work. The strongest stable candidate is `100.0` seconds, with 3 sensitive and 4 moderate stations. It is retained as the reference for a small, selective, process-realistic cycle-time review; it is not yet frozen as the final nominal operating point.

The decision is based only on line physics and healthy-run stability. No label prevalence or model result was available or consulted.
