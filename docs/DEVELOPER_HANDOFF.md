# TrustTwin - Developer Handoff

Welcome to the TrustTwin backend. The simulation, physical modeling, and ML intelligence layers (Flow, Quality, Anomaly, Trust) are fully implemented and validated. Your task is to build the application layer: the FastAPI backend to host these services and the Frontend to visualize them.

## Current State

The backend consists of:
1. **Simulation Engine** (`backend.simulation`): Generates physical manufacturing states and events.
2. **Observability Policy** (`backend.observability`): Filters internal physical events into a realistic stream of partial observability (what a real factory IoT system would see).
3. **Intelligence Layer** (`backend.intelligence`): 
   - **Flow**: Predicts station service deterioration and buffer congestion. Uses a hybrid of LightGBM predictions and robust fallback to predict `predicted_service_rate_vph`, then projects `time_to_blocking` using physics.
   - **Quality**: Evaluates component assembly risk leading to potential defects.
   - **Anomaly**: Detects broad operational deviations using Isolation Forest.
   - **Trust**: Validates sensor health (LIVE -> INFERRED -> UNKNOWN) based on data availability.

## Developer Tasks

1. **FastAPI & WebSockets (`app/`)**: You need to build a FastAPI server that wraps the `backend.intelligence` services and the simulation engine. Run the simulation in a background task, convert its events via `build_public_event_stream`, pass them through the intelligence services, and push the enriched state via WebSockets to the frontend.
2. **Frontend UI (`frontend/`)**: Build a dashboard to visualize the factory floor. 
   - **Flow**: Show buffer occupancies, capacity, and `riskLevel` (NORMAL, WATCH, HIGH, CRITICAL).
   - **Trust**: Visualize sensor data states (LIVE, INFERRED, UNKNOWN) with appropriate visual indicators.
   - **Quality/Anomaly**: Surface alerts and vehicle risk trajectories.

## Critical Constraints (DO NOT MODIFY)

The core backend is strictly frozen.
- **Do not modify `backend.simulation`, `backend.flow_v3`, `backend.intelligence`, or `backend.trust`.**
- **Do not retrain the ML models.** 
- **Do not alter the Observability Policy (`backend.observability.policy.py`).** You must feed only `PublicEvent`s to the intelligence services.
- **Do not bypass the simulation.** The physics engine accurately models the plant behavior; do not introduce "fake" states or mock data transitions (like faking sensor dropouts without a real scenario).

## Available Demos

To understand the intelligence layer's capabilities, review the deterministic demos in `artifacts/demo_v3/`:
- `demo_flow.json`: Shows early warning precursor deterioration before actual congestion hits.
- `demo_quality.json`: Shows a vehicle's quality risk rising progressively across stations ending in DEFECT.
- `demo_trust.json`: Demonstrates the deterministic transition from `LIVE -> INFERRED -> UNKNOWN`.
- `demo_hard_negative.json`: Shows the model successfully ignoring non-congestion events like `VEHICLE_MIX_OVERLOAD`.

See `docs/API_CONTRACT.md` for interface specifications.
