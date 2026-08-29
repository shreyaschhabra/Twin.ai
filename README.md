# TrustTwin.ai

Accenture Innovation Challenge 2026 — Team Bitrunners.

A confidence-aware predictive digital twin for brownfield vehicle assembly
lines: it predicts developing bottlenecks and vehicle-level quality risk,
and explicitly tells you when it doesn't have enough data to be confident —
LIVE / INFERRED / UNKNOWN — instead of silently guessing.

## Status

**Step 2 of implementation: SimPy core digital twin + master event stream.**
The 12-station development line now runs as a real discrete-event
simulation (SimPy): vehicles are generated, routed, queued, processed, and
completed, with genuine finite-capacity buffers, blocking, starvation, and
a chronological master event stream that vehicle genealogy is derived
from. No ML, anomaly detection, defect/scenario generation, API, or
frontend code exists yet — those are later steps.

Run the nominal development shift:

```bash
python scripts/run_nominal_simulation.py
```

This writes `data/generated/step2_nominal_events.parquet` and
`step2_nominal_genealogy.parquet`, and prints a sanity summary (station
utilization, blocked/starved time, buffer occupancy — sanity metrics only,
not final KPIs).

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
