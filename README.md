# TrustTwin.ai

Accenture Innovation Challenge 2026 — Team Bitrunners.

A confidence-aware predictive digital twin for brownfield vehicle assembly
lines: it predicts developing bottlenecks and vehicle-level quality risk,
and explicitly tells you when it doesn't have enough data to be confident —
LIVE / INFERRED / UNKNOWN — instead of silently guessing.

## Status

**Step 4 of implementation: full 45-station factory + historical dataset + QC generation.**
The factory now exists at two scales: `configs/development_line.yaml`
(12 stations, fast iteration/unit tests) and `configs/full_line.yaml`
(the locked 45-station, 4-zone factory — the one real dataset/ML work now
targets). Both run through the exact same simulator, scenario engine,
sensor engine, batch engine, and RNG architecture with zero code
branching. The full line generates a 24-shift, 10,800-vehicle
DEVELOPMENT historical dataset with probabilistic final-QC outcomes
(~3.9% defect rate) derived from accumulated latent quality exposure —
never a deterministic threshold. No ML, anomaly *detection*, FastAPI, or
frontend code exists yet — those are later steps, and this is still only
the development-scale dataset (20-30 shifts), not the final 100.

Generate the development dataset:

```bash
python scripts/generate_development_dataset.py
```

Run the EDA / synthetic-data validity / leakage / shortcut audit:

```bash
python scripts/audit_development_dataset.py
```

Observable data → `data/generated/development_45/observable/`; latent
ground truth (scenario truth, quality exposure, the exposure→probability
link — never an ML feature source) → `data/generated/development_45/latent/`.
A reproducibility manifest is written alongside at
`data/generated/development_45/manifest.json`.

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
  config/       station/buffer/vehicle-variant schemas + YAML loader (Step 1)
  simulation/   SimPy discrete-event line simulator + event stream (Step 2)
  twin/         live twin state manager (later step)
  features/     Flow/Quality feature engineering (later step)
  models/       trained ML models (later step)
  anomaly/      statistical + Isolation Forest anomaly detection (later step)
  confidence/   trust-tier / confidence scoring (later step)
  api/          FastAPI backend (later step)
  services/     supporting services (later step)
frontend/       React + Vite UI (later step)
configs/        YAML factory configuration (station types, lines)
data/           generated / processed / external datasets
notebooks/      EDA and modeling notebooks (later step)
artifacts/      trained models, metrics, plots (later step)
tests/          automated tests
scripts/        one-off developer/debugging scripts
```

## Illustrative assumptions

All cycle times, sensor availability, buffer capacities, and process
parameters are illustrative simulation assumptions, not sourced from a real
plant. See [ASSUMPTIONS.md](ASSUMPTIONS.md).

## Team

Shreyas Chhabra, Jiya Patel — IIT Patna.
