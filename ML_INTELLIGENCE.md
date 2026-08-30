# TrustTwin.ai — ML / Intelligence Layer

Documents the Flow, Quality, Anomaly, Trust, and Demo subsystems built on
top of the frozen 45-station simulation. Does **not** cover API/frontend
integration — that is a separate, later task; this layer exposes plain
Python objects and JSON artifacts only.

## Flow-v3 (service-capability precursor + queue projection)

Flow-v1/v2 (below, retained for historical comparison) trained a
classifier directly on current buffer occupancy, which meant "will the
queue become full" was largely solved by "is the queue already nearly
full" — closer to near-term queue forecasting than early precursor
detection. Flow-v3 replaces this with a two-layer architecture:

```
public process/service evidence -> PRECURSOR ML -> predicted future
service capability -> (+ current queue/arrival state) -> DIGITAL TWIN
QUEUE PROJECTION -> predicted time-to-impact -> FLOW ALERT
```

Direct occupancy/queue state is **excluded from the ML layer by
construction** (asserted at every feature-row build,
`backend/flow_v3/observations.py`) and lives only in the physics
projection (`backend/flow_v3/queue_projection.py`), which is the only
place allowed to read it.

**ML target**: `future_service_rate_vph = 3600 / mean(actual future
STATION_PROCESSING_COMPLETED durations in the next 5 minutes)` — a
continuous regression target over realized service time, not a raw
completions-per-hour count. A count-based rate was tried first and
rejected: it's confounded by arrival availability (a station starved of
arrivals looks "slow" even when perfectly healthy), which would silently
reintroduce the exact queue/arrival confound this redesign exists to
remove. Rows with zero realized completions in the future window are
excluded, never coded as 0.

**Corpus** (`backend/flow_v3/corpus_design.py`,
`scripts/build_flow_v3_corpus.py`): 109 predeclared controlled runs
(mechanism x station x severity x profile x seed, declared before any
simulation), split so every supervised mechanism (MANUAL_VARIATION,
MICRO_STOPS, ARRIVAL_BURST) and every severity band appears in every
partition — 41 train / 34 validation / 34 test runs, 335,901 event-
aligned observation rows (one row per `STATION_PROCESSING_COMPLETED`,
not a station-minute grid). EQUIPMENT_DEGRADATION is a fully separate,
never-trained-on unseen corpus (18 runs).

**Features** (11 kept of 34 raw, `backend/flow_v3/feature_selection.py`,
TRAIN-only constant/near-constant/duplicate/correlation filtering, no
PCA): `svc_recent_cycle_time_seconds`, `svc_cycle_time_ratio_to_baseline`,
`svc_cycle_time_trend_seconds`, `svc_cycle_time_std_seconds`,
`op_frac_running`, `op_frac_waiting`, `sensor_recent_mean`,
`sensor_trend`, plus static `station_type`/`zone`/`sensor_maturity`. No
raw `station_id`. Micro-stop and vehicle-mix features were dropped as
near-constant across the full 9-station observed population (only 2 of
9 stations are micro-stop-capable, and vehicle-mix proportions don't
vary much run-to-run) — a real finding about this corpus, not a bug.

For stations without direct duration instrumentation (`PARTIAL`/`POOR`
maturity — most of the physically capable set), cycle time is proxied by
per-vehicle entry-to-completion span (matched by `vehicle_id`, present
at every maturity), not cross-vehicle completion cadence — the latter
was tried first and rejected for the same arrival-confound reason as the
target: a station starved of arrivals shows an inflated "cycle time"
under a cadence-based proxy even when perfectly healthy. Verified: the
pre-scenario healthy-baseline ratio sits at ~1.04 with the vehicle-level
proxy vs. a biased ~1.4–2.0 under the rejected cadence-based one.

**Models**: Ridge baseline (TEST MAE 5.06 vph, R² 0.469) and LightGBM
final (small manual grid on VALIDATION only; TEST MAE 4.96 vph,
normalized MAE 9.6%, R² 0.477) — a modest, honest improvement, not a
dramatic one. `pred_contrib` reconstruction verified exactly
(max deviation 0.0). This is a genuinely harder regression problem than
Flow-v1/v2's classification task, by design: it excludes the occupancy
signal that made those easy.

**Queue projection** (`backend/flow_v3/queue_projection.py`): the only
layer reading current occupancy/capacity/arrival rate. Deterministic
deficit arithmetic (`arrival_rate - predicted_service_rate`) plus an
optional ~20-draw Monte Carlo over recent service-rate variability for a
`predictedOnsetMin`/`Max` interval — not a calibrated probability.
NORMAL/WATCH/HIGH/CRITICAL risk levels by time-to-blocking.

**Operational evaluation** (`scripts/evaluate_flow_v3_operational.py`,
congestion regimes from `backend/flow_v3/congestion.py`, reusing the
already-tested `backend.flow.bottleneck_events` recovery-gap merge):
threshold selected on VALIDATION only, TEST read once. **Honest result,
not oversold**: the frozen TEST partition's 18 congestion regimes all
happen to come from a single ARRIVAL_BURST run, a mechanism that raises
arrival pressure rather than degrading station service capability — by
this architecture's own design, that class of congestion is meant to be
caught by the queue-projection layer's arrival-rate input, not the
isolated ML signal, so the ML-only threshold-crossing proxy's 0% recall
on this specific TEST composition is an expected consequence of which
regimes this corpus happened to place in TEST, not evidence the model
learned nothing. On VALIDATION, where the 16 regimes come from
MANUAL_VARIATION and MICRO_STOPS (genuine service-capability
mechanisms), the same ML-only signal reaches 18.75% recall (3/16) — still weak,
but non-zero and mechanism-appropriate. **TrustTwin predicts developing
Flow risk and estimates time-to-impact before operational impact; it
does not yet demonstrate strong minutes-ahead recall from the ML signal
in isolation**, and a larger/more diverse predeclared TEST partition
(adding runs, never reshuffling existing ones) would be needed for a
statistically solid regime-recall number.

**Flow-v1/v2 (retired, kept for comparison)**

**Task**: predict whether a station will cause a genuine finite-buffer
blocking impact 5–10 minutes in the future. ACTIVE (already blocked) and
<5-minute IMMINENT rows are excluded from the target.

**Data**: `data/processed/flow_v2/` — built from Dataset C
(`historical_100_flow_calibrated`, a mechanistically-calibrated, Flow-
enriched synthetic corpus; see `backend/historical/flow_enrichment.py`
for the calibration rationale). Grouped, mechanism-aware shift split.
EQUIPMENT_DEGRADATION rows are held out entirely from supervised
train/val/test and used only as an unseen diagnostic.

**Final model**: LightGBM, `scale_pos_weight` from TRAIN, PR-AUC-based
early stopping (a custom feval — AUC saturates almost immediately on
this data and silently produced a degenerate 1-tree model on the first
attempt; caught and fixed). Threshold chosen by max-F2 grid search on
VALIDATION only, frozen, then TEST evaluated once.

**Limitations (do not oversell)**: occupancy dominates the top-feature
ranking — this model is closer to near-full queue forecasting than early
precursor prediction, which is exactly why Flow-v3 exists. Kept only as
a documented historical comparison point, not for further development.

## Quality (vehicle defect-risk prediction)

**Task**: for a vehicle currently on the line, predict the probability it
will eventually receive DEFECT at S45. Final QC is the label only, never
a feature before S45.

**Data source**: Dataset A (`data/generated/historical_100/`, the
naturalistic corpus with the audited QC generator) — **not** Dataset C,
whose Flow enrichment shifted the QC rate from 4.436% to 5.744%.

**Snapshots** (`backend/quality/snapshots.py`): 5 checkpoints per
vehicle — after S12 (body_joining exit), S20 (paint_surface exit), S27
(post-marriage fastening), S38 (final_assembly exit), S44 (pre-EOL). No
post-QC snapshot.

**Features** (`backend/quality/features.py`): 25 (24 numeric +
`vehicle_variant` categorical) — vehicle context, process-history
summary, sensor-history summary, quality-relevant process evidence
(torque/dimensional/paint/sealing deviation), and a leakage-safe cohort
feature (other vehicles' *already-recorded* QC outcomes for a shared
material batch, filtered strictly to `qc_time < snapshot_time`). No raw
`batch_key` category (would let the model memorize a specific batch's
outcome instead of learning a real signal).

**Models**: LogisticRegression baseline, LightGBM final model (same
PR-AUC early-stopping fix as Flow), validation-only F2 threshold.

**Early-detection metric** (the headline Quality result): 55.2% of
eventually-defective TEST vehicles are flagged before final QC, median
32 stations / ~1476s early (approximated to the vehicle's own S44
snapshot, not the exact S45 timestamp).

**Limitation**: this is synthetic validation against a simulated QC
outcome, not customer production validation.

**Revalidation** (`scripts/revalidate_quality_v3.py`, reporting only —
architecture and Dataset A unchanged): per-checkpoint TEST PR-AUC ranges
0.24 (S12) to 0.29 (S20); false-alert rate rises from ~3/100 good
vehicles at S12 to ~6/100 at S38/S44 as more evidence accumulates. A
cohort-feature ablation (retrained, like-for-like) found removing
`cohort_defect_rate_mean`/`cohort_sample_size_mean` did **not** hurt TEST
PR-AUC (0.281 without vs. 0.269 with) — most of this model's signal
comes from the vehicle's own process/sensor evidence, not genealogy. A
VALIDATION-only class-weight comparison confirmed the production
model's full `neg/pos` weighting is the best operating-point tradeoff
(highest precision, lowest false-alert rate of the three tested). A
two-consecutive-checkpoint persistence rule was tested and **rejected**
(vehicle-level recall 54.0% vs. 55.2% for raw single-checkpoint
alerting) — it doesn't meaningfully reduce false alerts while it does
cost recall, so the simpler raw rule stays.

## Anomaly

Two layers: rolling z-score/EWMA on a handful of interpretable features
(`backend/anomaly/statistical.py`), and an Isolation Forest
(`backend/anomaly/isolation_forest_model.py`). The Flow-v3 anomaly layer
(`scripts/train_anomaly_v3.py`) fits **only** on Flow-v3's dedicated
`HEALTHY_CONTROL` runs (no scenario active at all) — a correctness fix
over the earlier Flow-v2 approach, which fit on "Flow target == 0" rows;
that conflates "no bottleneck yet" with "truly undisturbed," since a row
can have target==0 while still sitting inside an active MILD/MODERATE
scenario. Separation confirmed against the scenario's own target station
during its actual active window (comparing against the unrestricted
"all SEVERE rows, whole run duration" population washes out the signal:
8 of 9 observed stations are never that scenario's target, and the
disturbance itself is a small fraction of an ~8.5-hour run). The
EQUIPMENT_DEGRADATION unseen holdout is never touched during fitting;
Anomaly ≠ defect — this layer never claims a Flow or Quality outcome.

## Trust / missing data

Exactly three data states (`backend/trust/data_state.py`): **LIVE**
(fresh direct reading), **INFERRED** (a 3-level virtual-sensor fallback —
same-station recent → same-station-type → operational baseline — judged
reliable), **UNKNOWN** (neither; a valid, intentional answer, never
forced into INFERRED). Trust level (`backend/trust/trust_level.py`) is a
deterministic, documented HIGH/MEDIUM/LOW rule based on live/inferred/
unknown fraction, freshness, virtual-sensor error, and signal count — **never presented as a calibrated probability**, and orthogonal to risk
(a HIGH-risk alert can carry LOW trust).

**Semantic correction**: the third hierarchy level (a station+sensor's
configured operational baseline) is retained only as an internal prior
and is **never** exposed as a current-measurement estimate — it now maps
to UNKNOWN, not INFERRED. Previously, an actually-abnormal sensor that
dropped out with no real fallback evidence could surface its configured
"assume healthy" baseline as if it were a live estimate; that is unsafe
and has been removed (`backend/trust/virtual_sensor.py`,
`backend/trust/data_state.py`, `TrustService.assess`).

**Observability boundary** (`backend/observability/policy.py`,
`docs/OBSERVABILITY_POLICY.md`): the simulator's internal event log is
never consumed directly by Flow/Quality/Anomaly/Trust. A deterministic
per-event-type, maturity-gated projection (`build_public_event_stream`)
is the only supported path to a `PublicEvent` stream; scenario identity,
severity, hidden degradation state, latent quality exposure, future
QC/bottleneck timestamps, and the sampled-but-not-yet-elapsed processing
duration at a `STATION_PROCESSING_STARTED` event are all `INTERNAL_ONLY`
and structurally absent from `PublicEvent` — verified against an actual
scenario-backed simulation run, not just synthetic events.
`public_events_as_of` enforces point-in-time cutoff for every feature
builder. Poor-maturity stations drop buffer occupancy, exact state
transitions, and micro-stop mechanics entirely, reflecting genuine
brownfield instrumentation limits rather than assumed telemetry.

**Compact validation** (`scripts/validate_trust_v3.py`): isolated random
masking and contiguous-outage masking against a live simulation. This
factory's sensor topology has well-populated same-station-type pools for
every sensor tested, so a contiguous outage never actually falls through
to UNKNOWN in that specific test — a property of this instrumentation
layout (shared sensor families across several same-type stations), not
evidence the UNKNOWN path is unreachable in general.

## Demo

`python scripts/run_final_demo.py` (after training the Flow-v3 and
Quality artifacts) drives four scenarios entirely from real model
artifacts and a live simulation replayed through the same public-event/
feature-building path used offline: a Flow precursor-deterioration ->
projected-impact -> actual-congestion trajectory (MICRO_STOPS at S26, a
genuine service-capability mechanism), a real defective TEST vehicle's
quality risk trajectory, a LIVE -> INFERRED -> UNKNOWN trust walkthrough,
and a VEHICLE_MIX_OVERLOAD hard negative (unusual workload, no critical
alert). No hardcoded scores. `python scripts/build_manager_analytics.py`
regenerates the manager analytics export (Flow-v1/v2 based; not yet
repointed to Flow-v3).
