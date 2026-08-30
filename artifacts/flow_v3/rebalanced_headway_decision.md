# Flow-v3 rebalanced healthy-line decision

## Finalist comparison

Ten independent healthy seeds and 600 vehicles per seed were run after both cycle-time and buffer changes.

| Headway | Runs blocked | Mean blocked s | Max rho/station | Mean occupancy | Busiest-buffer p95 | Mean max occupancy | Starved fraction | Steady throughput/h | Throughput std | Mean WIP |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 100.0 | 0/10 | 0.0 | 0.906/S22 | 0.0038 | 0.375 | 0.692 | 0.551 | 36.12 | 0.18 | 20.83 |
| 102.5 | 0/10 | 0.0 | 0.884/S22 | 0.0030 | 0.283 | 0.642 | 0.562 | 35.24 | 0.17 | 20.22 |
| 105.0 | 0/10 | 0.0 | 0.863/S22 | 0.0024 | 0.258 | 0.558 | 0.572 | 34.40 | 0.17 | 19.67 |

## Selected nominal headway

Selected `102.5` seconds. It is the fastest finalist with zero blocking in all comparison seeds, zero structural overload, and max nominal rho <=0.90. This keeps unchanged S22 below the aggressive upper edge while retaining stronger cross-zone disturbance sensitivity than 105s.

## Longer healthy stability gate

Three additional independent runs of 2000 vehicles each were executed at the selected headway.

- Runs with blocking: 0/3
- Mean blocked seconds: 0.0
- Mean steady throughput: 35.10 vehicles/hour
- Throughput run-to-run standard deviation: 0.13
- Mean busiest-buffer p95 occupancy ratio: 0.250
- Mean maximum observed buffer occupancy ratio: 0.722
- Mean starved fraction of station-time: 0.553
- Mean line WIP: 20.64
- Physical throughput constraint: S22 at rho=0.884

No scenario pilot has been generated. This nominal-line decision is paused for review as required.
