# TrustTwin.ai — ML / Intelligence Layer

Documents the Flow, Quality, Anomaly, Trust, and Demo subsystems built on
top of the frozen 45-station simulation. Does **not** cover API/frontend
integration — that is a separate, later task; this layer exposes plain
Python objects and JSON artifacts only.

## Flow (bottleneck prediction)

**Task**: predict whether a station will cause a genuine finite-buffer
blocking impact 5–10 minutes in the future. ACTIVE (already blocked) and
<5-minute IMMINENT rows are excluded from the target.

**Data**: `data/processed/flow_v1/` — built from Dataset C
(`historical_100_flow_calibrated`, a mechanistically-calibrated, Flow-
enriched synthetic corpus; see `backend/historical/flow_enrichment.py`
for the calibration rationale). Chronological shift split: TRAIN
SHIFT001-070, VALIDATION SHIFT071-085, TEST SHIFT086-100.
EQUIPMENT_DEGRADATION rows are held out entirely from supervised
train/val/test (`backend/flow/holdout.py`) and used only as an unseen
diagnostic.

**Features**: 42 point-in-time features (39 numeric + `station_type`/
`sensor_maturity`/`zone` categorical) across 7 groups — station
performance, buffer/WIP, arrival/departure, vehicle mix, sensor/process
trend, operational state, static context. `station_id`/`shift_id` are
metadata only, never model inputs. See `backend/flow/feature_manifest.py`.

**Final model**: LightGBM (`scripts/train_flow_final_model.py`),
`scale_pos_weight` from TRAIN, 15-trial Optuna tuning, **PR-AUC-based
early stopping** (a custom feval — AUC saturates almost immediately on
this data and silently produced a degenerate 1-tree model on the first
attempt; caught and fixed). Threshold chosen by max-F2 grid search on
VALIDATION only, frozen, then TEST evaluated once.

**Event-level evaluation** (`backend/flow/event_evaluation.py`): an
impact event is "eligible" only if ≥1 valid POSITIVE row exists 5–10
minutes before its onset; event recall is computed over eligible events
only (not the raw cross-shift event count — a real bug in an earlier
version). All reported lead times are structurally bounded to [300,600]s.

**Limitations (do not oversell)**: positive-class diversity is very low
(TEST's ~13-16 eligible positives concentrate at 2 stations, S21/S22).
Leave-one-station diagnostic (train without S22 positives) shows TEST_S22
PR-AUC collapsing to ~0.01 — this is documented, not "fixed": **TrustTwin
learns the operational signature of a configured line and provides early
congestion risk. It does not demonstrate universal bottleneck prediction
across arbitrary factories.**

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

## Anomaly

Two layers: rolling z-score/EWMA on a handful of interpretable features
(`backend/anomaly/statistical.py`), and an Isolation Forest
(`backend/anomaly/isolation_forest_model.py`) fit **only** on Dataset C's
TRAIN negative rows — the EQUIPMENT_DEGRADATION holdout is never touched
during fitting (tested), and is used solely for the post-hoc diagnostic:
83.5% detection rate during degradation, ~630s mean time-into-degradation
before flagged. Anomaly ≠ defect — this layer never claims a Flow or
Quality outcome.

## Trust / missing data

Exactly three data states (`backend/trust/data_state.py`): **LIVE**
(fresh direct reading), **INFERRED** (a 3-level virtual-sensor fallback —
same-station recent → same-station-type → operational baseline — judged
reliable), **UNKNOWN** (neither; a valid, intentional answer, never
forced into INFERRED). Trust level (`backend/trust/trust_level.py`) is a
deterministic, documented HIGH/MEDIUM/LOW rule based on live/inferred/
unknown fraction, freshness, virtual-sensor error, and signal count — **never presented as a calibrated probability**, and orthogonal to risk
(a HIGH-risk alert can carry LOW trust).

## Demo

`python scripts/build_demos.py` (after training all three model
artifacts) regenerates all four `artifacts/demo/*.json` files from real
data — a detected S22 bottleneck episode, a real defective TEST vehicle's
risk trajectory, a constructed sensor-loss timeline, and a representative
VEHICLE_MIX_OVERLOAD instance. `python scripts/build_manager_analytics.py`
regenerates the manager analytics export.
