# TrustTwin.ai

Accenture Innovation Challenge 2026 — Team Bitrunners.

A confidence-aware predictive digital twin for brownfield vehicle assembly
lines: it predicts developing bottlenecks and vehicle-level quality risk,
and explicitly tells you when it doesn't have enough data to be confident —
LIVE / INFERRED / UNKNOWN — instead of silently guessing.

## Status

TrustTwin has four intelligence layers running on top of the locked
45-station, 4-zone `configs/full_line.yaml` factory:

- **Flow-v3**: predicts a station's future service capability (not
  current occupancy) from public process evidence, then a separate
  digital-twin queue-projection layer combines that with real-time
  buffer/arrival state to project time-to-blocking. See
  [ML_INTELLIGENCE.md](ML_INTELLIGENCE.md) for the corpus, features,
  model, and an honest read of what the operational evaluation does and
  doesn't show yet. Flow-v1/v2 (occupancy-driven classifiers) are
  retained only as a documented historical comparison.
- **Quality**: predicts vehicle-level defect risk before final QC, from
  Dataset A's naturalistic 100-shift corpus.
- **Anomaly**: statistical (z-score/EWMA) + Isolation Forest, fit only on
  genuinely undisturbed (`HEALTHY_CONTROL`) operation.
- **Trust**: every value carries a data state — LIVE / INFERRED /
  UNKNOWN — and a trust level — HIGH / MEDIUM / LOW — never conflated,
  never a calibrated probability.

An **observability boundary** (`backend/observability/policy.py`,
[docs/OBSERVABILITY_POLICY.md](docs/OBSERVABILITY_POLICY.md)) sits
between the simulator's internal truth and every one of these layers:
scenario identity, latent quality exposure, future outcomes, and
not-yet-elapsed process durations are structurally excluded from the
public event stream every layer above actually consumes.

No FastAPI or frontend backend-integration code exists yet — the layers
above expose plain Python objects and JSON artifacts
(`artifacts/final_submission/`), not an HTTP API.

Rebuild everything from scratch:

```bash
python scripts/generate_historical_100.py            # Dataset A (Quality's source)
python scripts/build_quality_dataset.py && python scripts/train_quality_models.py
python scripts/build_flow_v3_corpus.py                # ~20 min: 127 controlled simulation runs
python scripts/train_flow_v3_model.py
python scripts/evaluate_flow_v3_operational.py
python scripts/train_anomaly_v3.py
python scripts/validate_trust_v3.py
python scripts/run_final_demo.py
python scripts/build_model_contracts.py && python scripts/build_system_health.py
python -m pytest tests/ -q
```

Earlier per-step demos still work: `scripts/run_nominal_simulation.py`
(12-station healthy shift) and `scripts/run_scenario_demos.py` (one run
per scenario family on the 12-station line).

## Development factory (Step 1)

The final system targets a 45-station mixed-model line. For fast iteration
during development, a smaller **12-station development line**
(`configs/development_line.yaml`) is used first. It shares the exact same
station-type templates (`configs/station_types.yaml`) and the exact same
loader/schema code (`backend/config/`) that the 45-station line will use —
moving to the final configuration later is a matter of adding a new YAML
file, not rewriting code.

Run the summary script to inspect the current development line:

```bash
python scripts/print_config_summary.py
```

Run the configuration validation tests:

```bash
python -m pytest tests/ -v
```

## Repository structure

```
backend/
  config/        station/buffer/vehicle-variant schemas + YAML loader
  simulation/    SimPy discrete-event line simulator + internal event stream
  observability/ internal-truth -> public-event projection boundary
  historical/    naturalistic dataset generation (Dataset A) + scenario scheduling
  flow/          shared Flow building blocks (bottleneck detection, features, holdout)
  flow_v2/       retired occupancy-driven Flow classifier (historical comparison only)
  flow_v3/       corpus design, event-aligned observations, congestion regimes,
                 feature selection, queue projection
  quality/       vehicle defect-risk snapshots/features/labels
  anomaly/       statistical + Isolation Forest anomaly detection
  trust/         data-state classification + virtual-sensor fallback + trust level
  intelligence/  service wrappers turning artifacts into station/vehicle objects
configs/         YAML factory configuration (station types, lines, Flow-v3 rebalance)
data/            generated (simulator output) / processed (ML-ready) datasets
artifacts/       trained models, metrics, demos, final_submission/ bundle
tests/           automated tests
scripts/         dataset/training/evaluation/audit entry points
frontend/        not yet integrated with this backend
```

## Illustrative assumptions

All cycle times, sensor availability, buffer capacities, and process
parameters are illustrative simulation assumptions, not sourced from a real
plant. See [ASSUMPTIONS.md](ASSUMPTIONS.md).

## Team

Shreyas Chhabra, Jiya Patel — IIT Patna.
