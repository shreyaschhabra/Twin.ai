# Flow-v3 current capacity audit

## Provenance and baseline gate

- Starting commit: `02a01b4e663e32fe0316c7d1dbbba154016a5b38`
- Runtime line configuration: `configs/full_line.yaml` (45 stations)
- Nominal release headway: `115.0` seconds
- Variant mix: ICE Sedan 45%, ICE SUV 35%, EV 20%
- TrustTwin-owned baseline suite: `237 passed in 85.70s`
- Authoritative baseline command: `.venv/bin/python -m pytest tests -q`
- Environment note: an initial unscoped system-Python run collected the read-only reference project and stopped with 26 collection errors (missing `simpy`/reference-only `catboost` and reference import-path conflicts); it is not counted as a TrustTwin product-test failure.
- Reference repository: `digital_twin-main` inspected read-only and excluded from TrustTwin test counts

Important preserved artifacts: `artifacts/flow_v2/`, `data/processed/flow_v2/`, `data/generated/historical_100_flow_calibrated/`, `artifacts/quality/`, `artifacts/anomaly/`, and `artifacts/demo/`.

## Method

For each station, service time follows the exact runtime precedence: station+variant override, then vehicle processing modifier, then 1.0. Route skips are respected. The nominal utilization is:

`rho = sum(mix_share[v] * visits[v] * service_time[v]) / (line_headway * resource_capacity)`

The station-specific arrival headway is `line_headway / visit_probability`. Scenario columns are counterfactual values under the current equations at the applicable current upper severity (0.9 for the background scheduler; 0.95 for Flow-v2 enrichment) if that station were targeted. They are physics diagnostics, not scenario recommendations.

## Utilization distribution

| Band | Stations | Percentage |
|---|---:|---:|
| <50% | 35 | 77.8% |
| 50-65% | 7 | 15.6% |
| 65-75% | 2 | 4.4% |
| 75-85% | 1 | 2.2% |
| 85-95% | 0 | 0.0% |
| >=95% | 0 | 0.0% |

## Highest-load stations

| Station | Operation | Weighted service (s) | Arrival headway (s) | rho | Capacity veh/h | Breakeven slowdown |
|---|---|---:|---:|---:|---:|---:|
| S22 | Wiring Harness Installation | 90.64 | 115.00 | 0.788 | 39.72 | 1.269 |
| S26 | Powertrain / Battery Pack Marriage | 77.40 | 115.00 | 0.673 | 46.51 | 1.486 |
| S24 | HVAC / Interior Module Installation | 75.00 | 115.00 | 0.652 | 48.00 | 1.533 |
| S21 | Trim Preparation | 70.00 | 115.00 | 0.609 | 51.43 | 1.643 |
| S34 | Electrical Connection / System Check | 68.00 | 115.00 | 0.591 | 52.94 | 1.691 |
| S20 | Paint Cure + Paint Inspection | 66.00 | 115.00 | 0.574 | 54.55 | 1.742 |
| S11 | Body Finishing / Manual Inspection | 65.00 | 115.00 | 0.565 | 55.38 | 1.769 |
| S15 | E-Coat Cure | 62.00 | 115.00 | 0.539 | 58.06 | 1.855 |
| S38 | Final Trim / Manual Inspection | 60.00 | 115.00 | 0.522 | 60.00 | 1.917 |
| S33 | Door / Closure Finishing | 58.00 | 115.00 | 0.504 | 62.07 | 1.983 |
| S03 | Body Side Panel Joining | 56.54 | 115.00 | 0.492 | 63.67 | 2.034 |
| S14 | E-Coat Application | 55.00 | 115.00 | 0.478 | 65.45 | 2.091 |

## Current scenario-equation capacity crossings

These lists answer only whether the current maximum equation can cross mean capacity. Realized blocking also depends on duration, stochastic variation, buffers, upstream flow, and recovery.

- Manual variation among current target pools: S22, S24
- Flow-calibrated micro-stops among current Flow-v2 candidates: S26
- Equipment degradation among current target pool: S26
- 100% highest-workload variant mix: none

## Buffer and topology observations

- Configured inter-station buffer capacities remain homogeneous: min=4, max=5; the runtime entry buffer is 20.
- S36 correctly aggregates the two inbound branch buffers. S35 is visited only by ICE variants, so its station arrival headway is longer than the line release headway.
- No configuration, scenario, dataset, model, threshold, or Flow-v2 artifact was changed in Phase A.

## Phase-A conclusion

The current line is comfortable: the maximum nominal rho is 0.788 at S22, and 35 of 45 stations are below 50% utilization. The audit confirms that only a narrow subset of stations can cross capacity under the current supervised Flow mechanisms. This supports proceeding to a physics-only headway sweep before changing any cycle time.
