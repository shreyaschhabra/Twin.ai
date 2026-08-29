# TrustTwin.ai

Accenture Innovation Challenge 2026 — Team Bitrunners.

A confidence-aware predictive digital twin for brownfield vehicle assembly
lines: it predicts developing bottlenecks and vehicle-level quality risk,
and explicitly tells you when it doesn't have enough data to be confident —
LIVE / INFERRED / UNKNOWN — instead of silently guessing.

## Status

**Step 3 of implementation: sensor generation + controlled abnormal-scenario engine.**
The 12-station development line now also generates observable sensor
readings and can inject any of 8 approved abnormal-scenario families
(equipment degradation, micro-stops, vehicle-mix overload, bad batch,
environmental drift, sensor dropout, manual variation, rare background
quality events) against a matched healthy baseline. A physically separate
latent-truth log (`backend/simulation/scenarios/latent.py`) records why
each abnormality happened for debugging/evaluation — it is never merged
into observable data, and automated tests enforce that. No ML, anomaly
*detection*, FastAPI, or frontend code exists yet — those are later steps.

Run the nominal healthy shift:

```bash
python scripts/run_nominal_simulation.py
```

Run one demonstration of each scenario family against a matched baseline:

```bash
python scripts/run_scenario_demos.py
```

Observable output goes to `data/generated/scenario_demos/`; latent
ground-truth output (never an ML feature source) goes to
`data/generated/latent/`.

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
