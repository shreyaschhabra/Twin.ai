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
  (`capacity: 1`, the schema default added in Step 2). The schema/engine
  already support a `capacity` field for a future multi-slot station, but
  the engine currently raises `NotImplementedError` if any configured
  capacity != 1, since multi-slot state semantics (what does "BLOCKED"
  mean for one of several slots?) are unneeded scope for this config and
  were not built.
- **S06 (paint cure oven) is an effective-service/headway abstraction, not
  a physical dwell-time model** (patched after Step 2 review). A real cure
  oven is a continuous-flow tunnel holding many vehicles in transit at
  once; its physical residence time could plausibly be 10-20+ minutes,
  but that number is irrelevant to a capacity=1, single-server discrete-
  event abstraction, which only cares about the rate vehicles exit
  (headway), not how long any one vehicle physically dwells inside.
  `baseline_cycle_time_seconds` for every station in this config
  represents that effective service/headway, not residence time — S06 is
  just the one station where the two would differ enough in reality to be
  worth calling out explicitly. An earlier draft set S06 to 180s (implicitly
  treating dwell time as if it were headway), which made it a structural
  bottleneck by construction (~87.5% nominal utilization) before any Step-3
  scenario ever ran. Corrected to **65s**, chosen by matching the pace of
  its immediate line neighbors — S05 Paint (60s) upstream and S07 Marriage
  (70s) downstream — not reverse-engineered from a target utilization
  number. This is an illustrative simulation abstraction, not a claim about
  real automotive paint-cure engineering.
- **Arrival pacing (nominal run)**: mean inter-arrival time is 200s
  (Normal(200, 20), floored at 60s). This was never the source of the S06
  problem and is unchanged. With S06 corrected, the highest-utilization
  station is now S09 (wiring, ~90s baseline) at ~45% nominal utilization —
  comfortably under the 75-80% target, with no station near-permanent
  saturation, leaving clear headroom for Step 3 scenarios to create
  bottlenecks intentionally rather than fighting a structural one.
  Blocking/starvation mechanics are proven separately by dedicated
  controlled-configuration tests (`tests/test_simulation_controlled.py`),
  not relied upon to emerge from nominal randomness.
- **RNG stream isolation** (patched after Step 2 review): a single shared
  `random.Random(seed)` was replaced with `RNGStreamFactory`
  (`backend/simulation/rng.py`), which derives one independent
  `random.Random` instance per named concern (`vehicle_interarrival`,
  `vehicle_variant_selection`, `processing_time::{station_id}` — one per
  station) by hashing `(master_seed, stream_name)` with SHA-256, never
  Python's built-in `hash()` (which is randomized per-process unless
  `PYTHONHASHSEED` is fixed, and would silently break cross-process/
  cross-machine reproducibility). Each stream is a fully independent state
  machine, so consuming values from one can never perturb another —
  proven by test, including the specific case of draining one station's
  stream and an end-to-end engine run where a hypothetical Step-3 stream
  (`sensor_noise::S01`) is drained before running and the resulting event
  stream is still byte-identical. This is what lets Step 3 add sensor
  noise, scenario occurrence/severity, and defect background noise as new
  named streams without touching any Step 2 timing.
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

## Step 3 — sensor and scenario assumptions

- **Sensor sampling cadence**: one observable summary reading per (vehicle,
  station, sensor) at processing-completion time — not high-frequency
  telemetry. The time-series structure anomaly detection needs later comes
  from comparing many visits to the same station over time (e.g. a slow
  drift across dozens of visits), not from sampling faster within any one
  15-180s visit. `cycle_time` is never emitted as a sensor reading since
  it would duplicate `STATION_PROCESSING_COMPLETED`.
- **Sensor model values** (`configs/sensor_models.yaml`): baseline/noise/
  valid-range per (station, sensor) are illustrative, anchored loosely to
  each station's existing `process_parameters` where one exists (e.g. S01
  weld_current baseline 9200A matches its configured
  `target_weld_current_amps`), not sourced from real equipment specs.
- **Micro-stop placement**: a triggered micro-stop is logged as its own
  `MICRO_STOP_OCCURRED` event and modeled as a discrete `DOWN`-state delay
  inserted between `VEHICLE_ENTERED_STATION` and
  `STATION_PROCESSING_STARTED` — meaning genealogy's `waiting_time` field
  (start − entry) absorbs the stoppage, while `processing_time` stays a
  clean measure of pure service time. This was a deliberate choice over
  folding the stoppage into the processing-time number, since it keeps
  "how long was this vehicle actually being worked on" separable from
  "how long was it delayed," while total elapsed time between entry and
  exit still correctly reflects the full real-world delay either way.
- **Scenario parameter values** (`configs/development_scenarios.yaml`):
  ramp durations, severities, magnitudes, and probabilities are
  illustrative choices picked to make each family's effect clearly
  demonstrable within a short development run, not calibrated against any
  real failure-mode data.
- **Scenario composition rule**: when multiple scenarios target the same
  station, their numeric effects (cycle-time multiplier, noise multiplier)
  multiply together in `self.scenarios` list order — a simple, predictable,
  documented rule, not a negotiated conflict-resolution system. Two
  scenarios on different stations are fully independent, proven by test
  (composing an S02 degradation with an S04 sensor dropout leaves S01
  byte-identical to a true no-scenario baseline).
- **Latent quality exposure is unitless and relative**, not a probability.
  It accumulates additively across a vehicle's chronological visits and is
  explicitly NOT converted into a defect probability/label in Step 3 — the
  PRD defers that conversion to Step 4's historical-data stage.
- **RNG streams added this step**: `vehicle_variant_selection` (already
  existed), plus new isolated streams — `sensor_noise::{station}::{sensor}`
  (one per station+sensor pair), `micro_stop::{station}`, and
  `background_quality_disturbance`. None of these existed in Step 2, so a
  no-scenario, no-sensor-model run touches none of them and reproduces
  Step 2's core event stream exactly (verified against a fixture captured
  from commit `57e71f3`, before any Step 3 code existed).

## Step 3 post-review patches

- **Micro-stop chronology corrected**: an earlier draft ran the micro-stop
  detour BEFORE `STATION_PROCESSING_STARTED`, which made the delay show up
  as upstream queue `waiting_time` in genealogy — wrong, since a micro-stop
  is a machine interruption while actively occupied, not a queueing delay.
  Corrected order: `STATION_PROCESSING_STARTED` → (possible `PROCESSING`→
  `DOWN`→`MICRO_STOP_OCCURRED`→`DOWN`→`PROCESSING`) → `STATION_PROCESSING_COMPLETED`.
  `STATION_PROCESSING_COMPLETED.value` (and therefore genealogy's
  `processing_time`) now equals the normal service draw plus the
  micro-stop duration when one fires, keeping `processing_completion_time
  - processing_start_time` consistent with the `value` field. Verified by
  test: `waiting_time` is now identical between a matched baseline and a
  micro-stop run for the same vehicle, while the processing span grows by
  exactly the injected duration.
- **Baseline material-batch schedule** (`configs/material_batches.yaml`,
  `backend/simulation/material_batches.py`): every vehicle at a configured
  batch-relevant station now receives a neutral, observable `batch_id`
  from a deterministic, per-station rotating schedule (`B1001, B1002, ...`,
  numbered independently per station since two stations track different
  material streams) — regardless of whether any scenario is configured.
  An earlier draft only assigned a `batch_id`/emitted
  `MATERIAL_BATCH_ASSIGNED` for scenario-affected vehicles, which would
  have made the mere *presence* of batch data a synthetic tell
  distinguishing healthy from bad-batch runs. `ScenarioManager` no longer
  assigns batches at all — it only has `check_batch_exposure()`, which
  looks at an already-assigned batch_id and decides, purely latently,
  whether it happens to be the one a `BAD_BATCH` scenario declared
  degraded. Verified by test: the same seed + same batch-relevant-station
  config produces a byte-identical observable batch-id sequence whether or
  not a `BAD_BATCH` scenario is present; only latent exposure differs.
- **Same-station composition semantics documented** in
  `backend/simulation/scenarios/manager.py`: cycle-time/variability
  multipliers multiply across scenarios on the same station; sensor mean
  shifts sum; sensor noise multipliers multiply; sensor dropout is NOT
  composed (last-in-list wins for a given sensor, a deliberate
  simplification); latent exposure contributions from different scenarios
  simply sum. A safety clamp (`_MAX_MULTIPLIER = 5.0`, illustrative, not a
  physical claim) prevents stacked multiplicative effects from producing
  an unbounded cycle time. Verified by test: `EQUIPMENT_DEGRADATION` +
  `SENSOR_DROPOUT` targeting the same sensor at the same station — cycle
  time still degrades and latent exposure still accumulates even though
  the degraded sensor reading itself is fully hidden by the dropout.

## Step 4 — full 45-station line, historical dataset, QC generation

- **Station-type assignment**: all 45 stations reuse the same ~10 Step-1
  templates — no new template was needed. Zone-level instrumentation
  follows the same operational logic as the dev line: automated
  body/paint/torque/inspection stations default rich, legacy manual
  finishing/trim/wiring stations (S11, S21, S22, S24, S33, S38) are poor,
  and a deliberate mix of older-but-automated equipment (adhesive/sealing,
  glass, some torque/fluid stations, plus two manual stations retrofitted
  with one extra justified sensor each — S29 position_sensor, S34
  functional_test_suite) are partial. Exactly 29/10/6, verified by test.
- **S35/S36 routing** (Section G): interpreted "shared route → variant-
  specific operation profile → rejoin" literally — S36 has NO route skip,
  both ICE and EV pass through it with different `variant_overrides`
  (same mechanism as S26). The one actual route skip/bypass in the full
  line is at S35 (EV has no fuel system), directly carrying forward the
  dev-line's S11 precedent, and is what the branch/merge validation test
  exercises.
- **Line-balance pacing**: mean inter-arrival set to 115s (vs. the dev
  line's 200s) because the full line's slowest station (S22 Wiring
  Harness, 88s baseline) is much faster relative to line length than the
  dev line's old S06 problem — pacing 115s keeps max nominal utilization
  at ~71% (S22) with a healthy spread down to ~14-21% at the fastest
  stations, and zero blocked time in the 200-vehicle line-balance check.
  No station-cycle-time adjustment was needed this time (unlike the S06
  patch after Step 2) — the config as designed already balanced well.
- **Batch-relevant stations** (`configs/material_batches_full.yaml`):
  S05, S16, S25 (adhesive/sealing family) and S27, S32 (fastener family),
  cohort sizes 5-12, chosen for variety across the two material streams
  the bad-batch scenario family can target.
- **Scenario scheduling policy** (`backend/historical/shift_scheduler.py`):
  simulation design assumptions, not real occurrence-frequency claims —
  ~55% of shifts are "abnormal" (1-3 non-background scenario instances,
  weighted toward 1-2), every shift always carries a small always-on
  RANDOM_QUALITY_EVENT background scenario regardless of abnormal status,
  severities drawn uniform(0.3, 0.9), start times drawn within the first
  65% of the shift so effects have room to play out. Family/station pairs
  are restricted to operationally sensible combinations (e.g. degradation
  only on automated equipment) rather than "any family, any station."
- **QC probability mapping** (`backend/simulation/qc.py`): a logistic
  curve, `p = background + (max - background) * sigmoid(steepness *
  (exposure - midpoint))`. Calibrated in three rounds against the ACTUAL
  generated dataset (not a hand-built proxy scenario mix — round 1 was
  tuned against one and landed at 2.1% once run at the real shift-scheduler
  scale): final values `background=0.015, max=0.75, midpoint=0.062,
  steepness=70` realize 3.889% overall on the frozen 24-shift set, inside
  the 3.5-4.5% target band, with genuine probabilistic overlap (85%+ of
  exposed vehicles still pass; the most-exposed decile still passes
  ~33% of the time; some low-exposure vehicles still defect).
- **Dataset master seed**: 20240002, not the first seed tried (20240001).
  The first seed landed in-band on defect rate but happened to draw zero
  SENSOR_DROPOUT scenario instances across all 24 shifts (a ~2.8%-chance
  outcome of uniform random family selection over 24 draws), which would
  have left no missingness evidence for the sensor EDA. 20240002 was
  chosen because it both lands in-band AND draws all 7 non-background
  scenario families at least once — not cherry-picked for the defect rate
  alone.
- **Development shift count**: 24 (within the requested 20-30 range) — a
  round number giving 10,800 vehicles, enough for the shortcut/leakage
  audits to be statistically meaningful while keeping each full
  regeneration under 45 seconds for iterative calibration.

### Bug found and fixed during Step 4: scenario-family draw order was non-deterministic across processes

`build_shift_schedule` originally built its list of candidate scenario
families from `FAMILY_STATION_POOLS.keys() | LINE_LEVEL_FAMILIES` — a set
union. `ScenarioFamily` is a `str` Enum, and Python randomizes string
hashing per process (`PYTHONHASHSEED`) unless explicitly fixed, so that
set's iteration order (and therefore which family `schedule_rng.choice()`
picked for a given index) differed on every fresh process invocation,
even with an identical seed. Three consecutive runs of the generator
script with the same `dataset_master_seed` produced three different
defect rates (4.65%, 3.64%, 4.11%) before this was caught — caught by
literally re-running the script and noticing the number moved, not by
any test, since a single pytest process has one fixed hash seed for its
whole lifetime and can't see this. Fixed by replacing the set union with
`list(FAMILY_STATION_POOLS.keys()) + LINE_LEVEL_FAMILIES` (dict key order
is insertion-order-guaranteed in Python 3.7+, independent of hashing) and
added `tests/test_historical_dataset.py::test_scenario_schedule_reproducible_across_separate_processes`,
which spawns three genuinely separate Python subprocesses and diffs
their output — the only way to actually catch this class of bug.

## What is NOT yet assumed

Defect rates, degradation/anomaly injection parameters, ML model
hyperparameters, alert thresholds, and ROI figures do not exist yet — they
will be added (and documented here) in later implementation steps.
