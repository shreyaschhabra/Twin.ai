# Observability policy

## Boundary

The simulator's canonical event log is internal truth. Deployable consumers must use this path:

```text
INTERNAL SIMULATOR TRUTH
        ↓
build_public_event_stream (observability policy)
        ↓
PUBLIC / DEPLOYABLE EVENT STREAM
        ↓
Flow / Quality / Anomaly / Trust
```

Flow, Quality, Anomaly, and Trust code must not accept `RunResult`, `latent_truth`, or raw `RunResult.events` when building deployable features. They must accept `PublicEvent` objects, and time-indexed features must first use `public_events_as_of`.

The simulator is intentionally unchanged as the source of mechanics, targets, evaluation truth, and debugging evidence.

## Classes

- `PUBLIC_DIRECT`: a direct MES, PLC/SCADA, sensor, or QMS observation.
- `PUBLIC_DERIVED`: a deterministic coarsening of deployable evidence, such as a partial station's coarse state.
- `CONDITIONALLY_OBSERVABLE`: evidence available only through configured or lower-confidence instrumentation/checkpoints.
- `INTERNAL_ONLY`: required for simulation or evaluation but omitted from the public stream.

Public events carry their evidence source and confidence. Internal event IDs are never exposed; public IDs are contiguous so gaps cannot reveal suppressed events.

## Event policy

| Internal event | Rich | Partial | Poor |
|---|---|---|---|
| `VEHICLE_CREATED` | MES identity/variant/time | same | same |
| `VEHICLE_ENTERED_BUFFER`, `VEHICLE_LEFT_BUFFER` | PLC event with exact occupancy | movement indication, occupancy absent | internal only |
| `VEHICLE_ENTERED_STATION` | MES checkpoint | MES checkpoint, reduced confidence | sparse/manual checkpoint |
| `STATION_PROCESSING_STARTED` | PLC start timestamp | conditional start pulse | internal only |
| `STATION_PROCESSING_COMPLETED` | PLC completion and measured duration | completion timestamp, exact duration absent | MES/manual exit checkpoint, exact duration absent |
| `STATION_STATE_CHANGED` | exact PLC state and blocked-buffer context | coarse derived state (`RUNNING`, `WAITING`, `FLOW_STOP`, `EQUIPMENT_STOP`) | internal only |
| `MICRO_STOP_OCCURRED` | PLC interruption with duration | alarm/pulse without exact duration | internal only; downstream checkpoint evidence remains |
| `SENSOR_READING` | configured direct sensor | configured reduced telemetry | only configured sparse/manual evidence such as checklist completion |
| `MATERIAL_BATCH_ASSIGNED` | direct MES/scan | conditional scan | sparse/manual scan when present |
| `QC_RESULT_RECORDED` | QMS result at completed inspection time | same | same |
| `VEHICLE_COMPLETED_LINE` | MES completion | same | same |

The `value` attached internally to `STATION_PROCESSING_STARTED` is the simulator's already-sampled future work duration. It is `INTERNAL_ONLY` at every maturity. A rich station exposes actual duration only at completion.

## Field audit

| Field/truth | Classification | Public behavior |
|---|---|---|
| event timestamp | `PUBLIC_DIRECT` or conditional | retained for emitted events |
| vehicle ID, variant, route position | `PUBLIC_DIRECT` MES | retained when present |
| station ID | direct/conditional | retained for emitted station evidence |
| buffer ID | direct at rich | absent from partial coarse state and poor evidence |
| exact occupancy | direct at rich | absent at partial/poor |
| exact station state | direct at rich | coarsened at partial; absent at poor |
| measured completion duration | direct at rich | absent at partial/poor |
| sampled future processing duration at start | `INTERNAL_ONLY` | always absent |
| configured sensor reading/status | maturity-dependent | retained only when that configured evidence exists |
| batch scan/key | direct or conditional | retained when scan evidence exists |
| completed QC result | `PUBLIC_DIRECT` QMS | emitted only when QMS event occurs |
| internal event ID | `INTERNAL_ONLY` | replaced with contiguous public ID |
| scenario ID/family/parameters/severity | `INTERNAL_ONLY` | never part of `PublicEvent` |
| hidden degradation state | `INTERNAL_ONLY` | never part of `PublicEvent` |
| latent quality exposure/probability | `INTERNAL_ONLY` | never part of `PublicEvent` |
| future bottleneck/impact time | `INTERNAL_ONLY` | never part of `PublicEvent` |
| future QC or station readings | `INTERNAL_ONLY` until occurrence | excluded by `public_events_as_of` |

## Brownfield maturity assumptions

Rich means connected PLC/SCADA plus configured telemetry; it does not mean internal future truth is public. Partial means basic PLC/MES pulses and selected sensors are present, but exact buffer levels, process durations, and fine state are not assumed. Poor means the station still has vehicle entry/exit checkpoints and configured sparse/manual evidence, but it does not publish exact internal states, buffer occupancy, or micro-stop mechanics.

This preserves Flow feasibility without inventing instrumentation. S20 and S26 provide rich Flow-sensitive telemetry; S34 provides partial/coarse evidence. Poor candidates such as S11, S21, S22, S24, and S38 contribute sparse MES/manual timing and downstream evidence, which intentionally yields lower availability and trust.

## Virtual-sensor semantics

The hierarchy is:

1. fresh direct measurement → `LIVE`;
2. validated same-station recent estimate → `INFERRED`;
3. validated same-type transfer → `INFERRED` with reduced trust;
4. static configured operational baseline only → `UNKNOWN` for the current measurement.

The configured baseline may remain an internal prior, but it is marked unreliable and is not exposed by `TrustService` as a current estimated value.

## Determinism and dropout

Projection is deterministic, order-preserving, and contains no RNG. A configured sensor dropout remains observable only through its emitted measurement status/value; the hidden scenario that caused it remains internal. Cutoff filtering excludes every event after the feature timestamp.
