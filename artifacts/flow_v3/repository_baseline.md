# Flow-v3 repository baseline

## Safety record

- Starting commit: `02a01b4e663e32fe0316c7d1dbbba154016a5b38`
- Starting branch/status: `main`, clean
- Implementation branch: `codex/flow-redesign-v3`
- Authoritative baseline command: `.venv/bin/python -m pytest tests -q`
- Baseline result: `237 passed in 85.70s` (`86.36s` wall time)
- Phase-A/Phase-B regression result: `246 passed in 76.93s` (`77.56s` wall time)
- Rebalance/buffer/final-headway regression result: `255 passed in 85.64s` (`86.22s` wall time)
- An initial unscoped system-Python run collected the read-only reference repository and stopped with 26 collection errors. The causes were an environment without TrustTwin's declared `simpy` dependency, the reference project's undeclared `catboost` dependency, and reference-package import-path conflicts. This is recorded as an environment/test-discovery issue, not a TrustTwin test failure.

## Preserved implementation and artifacts

Flow-v2 remains intact in:

- `backend/flow_v2/`
- `scripts/build_flow_v2_dataset.py`
- `scripts/train_flow_v2_model.py`
- `data/processed/flow_v2/`
- `artifacts/flow_v2/`

Other important current artifacts remain intact in:

- naturalistic corpus: `data/generated/historical_100/`
- Flow-calibrated corpus: `data/generated/historical_100_flow_calibrated/`
- Quality: `data/processed/quality_v1/` and `artifacts/quality/`
- anomaly: `artifacts/anomaly/`
- trust implementation: `backend/trust/`
- demos/manager export: `artifacts/demo/`

The Flow-v3 work is isolated under `backend/flow_v3/` and `artifacts/flow_v3/`. No old artifact has been overwritten or deleted.

## Independently confirmed current Flow-v2 behavior

- The primary sampling source is still a 60-second station grid. The manifest records 3,990,330 raw candidates and 2,963,764 retained rows, only a 25.73% reduction.
- `apply_already_full_exclusion` exists, but `scripts/build_flow_v2_dataset.py` deliberately does not call it; the manifest records zero already-full exclusions.
- Only 14 of 100 shifts contain the 1,181 detected blocking-impact events. S21 and S22 contribute 1,002 events (84.8%); S26 contributes 3.
- Current validation/test any-warning regime recall is about 96%, but 5–10 minute recall is only 4.59%/5.88%.
- Buffer occupancy is the top global feature family; `inbound_occupancy_mean_5m` is the dominant reported feature.
- The grouped-CV path passes each outer fold's test rows into LightGBM as the early-stopping validation set.
- The current leave-station diagnostic removes only positive rows for the held-out station, not every row from that station.
- The current leave-mechanism diagnostic removes only positive rows from selected mechanism shifts, not the complete runs.
- The anomaly model is fit on Flow-v2 TRAIN rows with `target == 0`, rather than on predeclared genuinely healthy runs.
- The split code contains hard-coded lists of shifts known to contain impact mechanisms before allocation, so the current split is not outcome-blind.

These observations are audit findings only. Phase A does not modify Flow-v2 behavior.

## Read-only reference repository

`digital_twin-main/` is present and is ignored by TrustTwin Git. It was inspected read-only. Useful concepts observed include independent simulator-run manifests, explicit temporal degradation modes, event/checkpoint observation policies, per-run reporting, and separation between current-run inference and historical calibration. No source code was copied, and its aggressive/factory-specific assumptions are not treated as TrustTwin defaults.
