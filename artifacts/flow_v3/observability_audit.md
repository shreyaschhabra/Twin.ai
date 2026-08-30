# Flow-v3 observability audit

This audit validates the internal/public boundary on a deterministic 40-vehicle healthy run at 102.5s. It is not a Flow pilot and creates no features or labels.

## Projection counts

| Maturity | Internal events | Public events | Public share | Direct | Derived | Conditional |
|---|---:|---:|---:|---:|---:|---:|
| rich | 10766 | 10766 | 100.0% | 10766 | 0 | 0 |
| partial | 3240 | 3240 | 100.0% | 394 | 796 | 2050 |
| poor | 1838 | 720 | 39.2% | 0 | 0 | 720 |
| global | 40 | 40 | 100.0% | 40 | 0 | 0 |

## Event-type projection

| Event type | Internal | Public | Suppressed/reduced count |
|---|---:|---:|---:|
| VEHICLE_CREATED | 40 | 40 | 0 |
| VEHICLE_ENTERED_BUFFER | 1794 | 1554 | 240 |
| VEHICLE_LEFT_BUFFER | 1794 | 1554 | 240 |
| VEHICLE_ENTERED_STATION | 1794 | 1794 | 0 |
| STATION_PROCESSING_STARTED | 1794 | 1554 | 240 |
| STATION_PROCESSING_COMPLETED | 1794 | 1794 | 0 |
| STATION_STATE_CHANGED | 3520 | 3122 | 398 |
| VEHICLE_COMPLETED_LINE | 40 | 40 | 0 |
| SENSOR_READING | 3274 | 3274 | 0 |
| MICRO_STOP_OCCURRED | 0 | 0 | 0 |
| MATERIAL_BATCH_ASSIGNED | 0 | 0 | 0 |
| QC_RESULT_RECORDED | 40 | 40 | 0 |

## Leakage and parity checks

- PASS — public IDs are contiguous 1..14766 and projection is byte-for-byte deterministic at object level.
- PASS — rich measured completion-duration parity: 1160/1160 retained.
- PASS — partial/poor exact completion-duration leaks: 0.
- PASS — poor exact state/micro-stop leaks: 0.
- PASS — sampled future processing-duration leaks at start: 0.
- PASS — public schema excludes scenario truth, degradation severity, latent exposure, future impact/QC/readings, and source internal IDs.
- PASS — QMS results enter the public stream only at their completed QC event timestamp; cutoff filtering is tested separately.

## Maturity interpretation

Rich retains deployable PLC states, exact buffer occupancy, measured completion duration, configured sensors, and exact micro-stop duration. Partial retains reduced event pulses, coarse derived states, and configured telemetry but removes exact occupancy and duration. Poor retains sparse MES/manual station checkpoints and configured manual evidence while suppressing exact buffer, state, processing-start, and micro-stop mechanics.

## Virtual sensor

A configured operational baseline is now an unreliable internal prior. With no direct, same-station, or validated same-type evidence, public state is UNKNOWN and no current estimated value is exposed.

No pilot, feature dataset, precursor label, or model was generated.
