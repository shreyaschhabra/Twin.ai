# Illustrative Simulation Assumptions

Everything below is an **illustrative assumption made for this prototype**,
not a value sourced from a real automotive plant. This document exists so
the submission never implicitly overstates the realism of the numbers used.
It will grow as later steps (simulation, defect generation, ROI calculator)
add more assumed parameters.

## Station-level (`configs/development_line.yaml`)

- **Baseline cycle times** (e.g. 48s for underbody weld, 180s for the paint
  cure oven) are directionally realistic relative to each other (weld <
  torque < paint cure) but are round illustrative numbers, not measured
  values. The paint cure oven time in particular is compressed far below a
  real oven's dwell time purely for simulation tractability.
- **Cycle-time variability** (a coefficient-of-variation-style fraction,
  e.g. 0.06 for a robotic weld cell vs. 0.25 for a manual station) reflects
  the general principle that automated stations are more consistent than
  manual ones, not a measured statistical distribution.
- **Process target parameters** (e.g. `target_weld_current_amps: 9200`,
  `target_torque_nm: 45`) are plausible-order-of-magnitude illustrative
  values, not specifications from any real vehicle program.
- **Buffer capacities** (4-6 vehicles) are small illustrative numbers
  chosen to make bottleneck propagation demonstrable within a short
  simulated shift, not derived from real conveyor/buffer sizing.

## Sensor maturity (`configs/development_line.yaml`)

- The 8 rich / 3 partial / 1 poor split for the 12-station development line
  was derived by reasoning about each station's realistic instrumentation
  (e.g. vision/laser inspection cells and paint booths are typically
  well-instrumented for compliance reasons; legacy manual stations
  typically are not), then checking the resulting ratio (66.7% / 25.0% /
  8.3%) against the PRD's target final-line ratio (64.4% / 22.2% / 13.3%)
  for rough proportionality. It was not forced to hit those percentages
  exactly, and it should not be read as a validated real-world statistic.

## Vehicle variants (`configs/development_line.yaml`)

- The **EV skipping the fuel-fill station (S11)** is a logically justified
  route difference (no fuel system on an EV), not an arbitrary branch added
  for graph complexity.
- The **ICE SUV and EV processing-time modifiers** (e.g. 1.08x, 1.20x) are
  illustrative multipliers representing "heavier body" or "more complex
  sub-assembly," not measured differences between real vehicle programs.

## Post-review corrections (Step 1 patch)

- **Assembly sequence**: an earlier draft placed powertrain/battery marriage
  (now S07) after seat/wheel fastening and wiring. That is backwards from
  real assembly practice (chassis marriage happens first; fastening,
  wiring, and wheels follow). Reordered so marriage precedes them.
- **S03 naming**: renamed from "Seam Sealant Application" to "Structural
  Adhesive / Body Bonding" — deliberately generic language so the
  illustrative station doesn't read as a precise claim about real
  sealant/paint sequencing.
- **Variant-specific station semantics**: S07 (marriage) is the same
  physical station for all three variants, but ICE variants perform
  `powertrain_marriage` while EV performs `battery_pack_marriage` — a
  genuinely different operation, not just a slower one. The schema now
  supports this via `StationInstance.variant_overrides`, which can carry an
  `operation_profile` string per variant plus an optional
  `cycle_time_multiplier` that takes precedence over the variant-level
  `processing_time_modifiers` for that station. Stations that only need a
  plain speed difference (no distinct operation) keep using the simpler
  variant-level modifier instead, so there's exactly one place that defines
  any given station+variant's multiplier.

## Step 2 — simulation assumptions

- **Station capacity**: every station is modeled as a single serving slot
  (`capacity: 1`, the schema default added in Step 2). This matters most for
  S06, the paint cure oven: a real oven is a continuous-flow tunnel holding
  many vehicles at once, not a single-slot server. Modeling it as capacity=1
  with a 180s baseline makes it the line's clear throughput bottleneck,
  which is a deliberate simplification, not an oversight — see the
  "arrival pacing" note below. The schema/engine already support a
  `capacity` field for a future multi-slot station, but the engine
  currently raises `NotImplementedError` if any configured capacity != 1,
  since multi-slot state semantics (what does "BLOCKED" mean for one of
  several slots?) are unneeded scope for this config and were not built.
- **Arrival pacing (nominal run)**: mean inter-arrival time is 200s
  (Normal(200, 20), floored at 60s), deliberately set slightly *above*
  S06's ~180s mean cycle time. This is standard line-balancing practice,
  not a tuning hack: pacing arrivals faster than the slowest station's rate
  guarantees permanent saturation regardless of simulator correctness, for
  any line, real or simulated. Blocking/starvation mechanics are proven
  separately by dedicated controlled-configuration tests
  (`tests/test_simulation_controlled.py`), not relied upon to emerge from
  nominal randomness.
- **Entry buffer capacity**: 20 (a vehicle-generator-side staging queue in
  front of each entry station). Not part of the Step 1 buffer config since
  it isn't a real inter-station buffer; exists so a fully backed-up line
  would eventually throttle new arrivals too, rather than queuing them
  invisibly forever.
- **Vehicle mix**: ICE Sedan 45% / ICE SUV 35% / EV 20% — an illustrative
  mix (ICE still dominant, EV a meaningful minority), not sourced from any
  real production plan.
- **Processing-time stochastic method**: truncated-normal-with-floor —
  `Normal(mean, mean * cycle_time_variability)`, floored at `0.3 * mean` to
  keep every draw comfortably positive. Chosen deliberately as the simplest
  bounded method that satisfies "processing time must always remain
  positive," per instructions to avoid a more sophisticated distribution
  without a demonstrated need for one. The same method is reused for
  vehicle inter-arrival times.
- **Random-state management**: one `random.Random(seed)` instance is
  created per simulation run and threaded explicitly through the vehicle
  generator and every station's processing-time draw — no global `random`
  state is touched, so two runs with the same seed and config are bit-for-
  bit reproducible in event order and timing (verified by test).

## What is NOT yet assumed

Defect rates, degradation/anomaly injection parameters, ML model
hyperparameters, alert thresholds, and ROI figures do not exist yet — they
will be added (and documented here) in later implementation steps.
