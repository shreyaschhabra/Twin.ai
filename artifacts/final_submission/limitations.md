# TrustTwin.ai — known limitations

This is a synthetic prototype validating an intelligence architecture, not a
plant-calibrated or customer-validated system. Plant-specific calibration
would be required before any production use.

## Flow-v3

- **Flow uses controlled stress-development runs**, not the naturalistic
  corpus Quality uses. 109 predeclared runs (mechanism x station x
  severity x profile x seed), because rare, physically-capable congestion
  conditions are far too sparse in naturalistic operation to train or
  evaluate on directly.
- **Flow ML does not use direct queue occupancy.** Occupancy, buffer
  capacity, and arrival rate are used only in the separate queue-projection
  physics layer, never as ML model inputs — asserted at every feature-row
  build.
- The frozen TEST partition's congestion regimes all happen to come from a
  single ARRIVAL_BURST run (an arrival-pressure mechanism, not a
  service-capability one) — see `flow_metrics.json` for the full honest
  breakdown of why this makes the ML-only recall number on TEST
  uninformative in isolation, and what VALIDATION (service-capability
  mechanisms) shows instead.
- Regression fit is real but modest: LightGBM TEST MAE ~5 vph, R² ~0.48.
  This is a genuinely harder problem than a classifier trained directly on
  occupancy — by design.
- Most positive-capable stations are POOR sensor maturity in this factory
  configuration, meaning exact process duration, state transitions, and
  micro-stop mechanics are not observable there at all; the precursor
  signal at those stations is necessarily weaker than at RICH stations.
- **Inspection/EOL supervised Flow diversity limitation**: no
  Inspection/EOL station is a supervised Flow-positive-capable candidate
  in this configuration. This was not forced for diversity's sake.
- Flow-v1/v2 (occupancy-driven classifiers) are retained only as a
  documented historical comparison, not for further development.

## Quality

- Synthetic validation against a simulated final-QC outcome, not customer
  production validation.
- Early-detection "time remaining" is approximated to the vehicle's own
  S44 (pre-EOL) snapshot, not the exact S45 timestamp.
- Modest PR-AUC (~0.27-0.29 per checkpoint) — flags roughly half of
  eventually-defective vehicles before final QC, with real false-alert
  cost; not a substitute for physical inspection.

## Anomaly

- Detects statistical deviation from genuinely undisturbed operation; it
  does not itself claim a Flow or Quality outcome.
- EQUIPMENT_DEGRADATION unseen-holdout detection is evaluated only on the
  station actually being degraded in each run, restricted to the active
  disturbance window — see `trust_metrics.json`/`quality_metrics.json`
  siblings for the exact numbers this run produced.

## Trust

- **UNKNOWN is a valid, intentional answer** — it is never forced into
  INFERRED when no reliable fallback basis exists. A configured
  operational baseline is retained only as an internal prior and is never
  surfaced as a current-measurement estimate.
- This factory's sensor topology has well-populated same-station-type
  pools for the sensors tested, so a contiguous outage in the validation
  script never actually falls through to UNKNOWN in that specific
  scenario — a property of this instrumentation layout, not evidence the
  UNKNOWN path is unreachable in general.
- Trust level (HIGH/MEDIUM/LOW) is a deterministic rule, never a
  calibrated probability, and is orthogonal to risk.

## General

- Synthetic prototype: all cycle times, sensor availability, buffer
  capacities, and process parameters are illustrative simulation
  assumptions (see `ASSUMPTIONS.md`), not sourced from a real plant.
  Plant-specific calibration is required before any production use.
- No FastAPI/frontend integration exists yet; these layers expose plain
  Python objects and JSON artifacts.
