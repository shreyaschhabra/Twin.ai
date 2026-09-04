# Final Bottleneck Prediction Pipeline

## Factory-specific training and operations

The canonical training input is the simulator's completed run directory tree:

```text
simulation/training/runs/run_0001/
simulation/training/runs/run_0002/
...
```

From the repository root, start the cross-platform interactive Python shell:

```powershell
py cli.py
```

On macOS/Linux, use `python3 cli.py`. The interactive prompt accepts the same
subcommands shown below, while non-interactive commands remain suitable for
scripts and CI:

```powershell
py cli.py factories register factory-a simulation/config/factory.json
py cli.py generate --count 20
py cli.py simulate
py cli.py factories configure factory-a --stations simulation/training/runs/run_0001/stations.csv
py cli.py train factory-a --factory-id factory-a
py cli.py models list
py cli.py models select factory-a
py cli.py run prescribed --run-dir simulation/training/runs/run_0001 --output predictions.jsonl --unpaced
```

`factories configure` saves the configured-stations path in
`.digital_twin/factories.json`; training with `--factory-id` uses that registered
factory and its configuration. `factories delete --force` removes only the
registry entry, never the factory definition or configuration file.

`train` reads those run folders in place, builds only the frozen 28-feature
bottleneck dataset, starts from the protected initial/base XGBoost state, and
publishes `factory_models/<factory-id>/`. Each artifact has its own bundle,
feature contract/category levels/threshold, configured-stations topology, and
DARK historical calibration when the factory has DARK zones. Factories with no
DARK zones are valid: no dwell or corridor calibration is created or required.
It deliberately excludes runtime queues, PF state,
recent observations, output predictions, and raw CSV copies.

The selected model is only a pointer in `factory_models/selected_model.json`.
Selecting a different artifact never modifies either model. The `base` model is
protected; deleting a run or factory artifact requires `--force` and the shell
will never delete `base`.

`run prescribed` uses only the selected artifact's historical calibration, so
the evaluated run cannot calibrate or train itself. By default it paces event
delivery at `--mult` (60× by default); use `--unpaced` for a fast offline replay.
The runtime still receives events in timestamp order through the same
`process_event()` / `advance_time()` implementation used for live input.

## Live current-run workflow

`run_current.py` starts **only the bottleneck consumer**. It does not launch or own
the simulator process. The intended deployment is:

```text
factory.json / scenario
        |
        v
C++ simulator (separate process)
        |
        +--> stations.csv + dz.csv + station_checkpoints.csv
        +--> units.csv (appended/flushed as units are created)
        +--> runtime_events.csv (ordered, flushed public event bus)
                         |
                         v
                  run_current.py
                         |
              LIGHT / DARK router
                  /           \
             LIGHT        DARK PF/corridor PF
                  \           /
                   exact 28 features
                         |
                 native XGBoost JSON
                         |
                    exact TreeSHAP
                         |
                  predictions.jsonl
```

The simulator's `dz.csv` is authoritative for DARK membership. Raw
`sensor_coverage` is telemetry richness and is **not** used as a DARK-zone flag.
S01/other zero-buffer source stations are not sent to the frozen bottleneck model
because the frozen training target never produced eligible labels for them.

Prior completed runs used for causal DARK calibration live under:

```text
data/calibration/history/<run_name>/
├── stations.csv
├── units.csv
└── station_events.csv
```

For simulator v2.1 history, calibration uses only paired public
`DARK_ZONE_ENTERED` / `DARK_ZONE_EXITED` boundaries. Hidden internal processing
truth is neither required nor reconstructed. The current run is **never** used to
calibrate itself by `run_current.py`.

## Start the bottleneck consumer

Install dependencies (Python 3.10+ recommended), start the simulator separately so
it writes to `data/input/current_run/`, then from `bottlenecks_prediction/` run:

```bash
pip install -r requirements.txt
python run_current.py
```

`run_current.py` defaults to live mode. It waits for the simulator's public files,
uses the selected model pointer (BASE by default), and tails `runtime_events.csv`.
BASE derives DARK topology from the run's `dz.csv`; a selected factory artifact must
match the run's station order, static station settings, and DARK topology or startup
is rejected. The consumer handles both identified RFID and non-identifying
POWER_DRAW evidence and writes predictions as the simulation progresses. POWER_DRAW
with blank `unit_id` is associated probabilistically across the active DARK
population; it is not discarded or assigned fake identity.

Useful options:

| Flag | Default | Description |
|---|---|---|
| `--mode` | `live` | `live` tails the simulator; `replay` processes a completed current run |
| `--particles` | `3000` | DARK corridor particle count |
| `--output` | `data/output/predictions.jsonl` | Prediction JSONL destination |
| `--run-id` | `CURRENT_RUN` | Runtime label |
| `--model-id` | selected pointer | Optional explicit BASE/factory artifact override |
| `--artifact-root` | `factory_models/` | Factory artifact store / selected-model pointer |
| `--wait-seconds` | `120` | Maximum wait for simulator public files |
| `--poll-ms` | `50` | Live bus polling interval |
| `--live-batch-size` | `128` | Maximum public records routed before batched XGBoost/SHAP scoring |

For a completed run (which must contain `run_metadata.json`):

```bash
python run_current.py --mode replay --particles 3000
```

Completed replay auto-discovers the simulator's real `checkpoint_events.csv` and
`station_checkpoints.csv`. Legacy synthetic checkpoint generation is used only when
a historical/older run has checkpoint definitions but no real checkpoint stream.

## Simulator live contract

The live consumer expects the simulator to create:

- `stations.csv`: physical station configuration.
- `dz.csv`: inclusive DARK corridor topology.
- `units.csv`: `unit_id` and `vehicle_model`, appended/flushed before first use.
- `station_checkpoints.csv`: RFID/POWER_DRAW checkpoint progress definitions.
- `runtime_events.csv`: one ordered public stream containing station events/boundaries and observable checkpoint evidence.
- `run_metadata.json`: created by the simulator at completion; the live consumer drains the bus and then exits.

The public bus deliberately does **not** expose hidden internal DARK movement or
processing truth. RFID and POWER_DRAW checkpoints remain visible because they are
the intended sparse DARK evidence.

## Causality

For DARK stations, `run_current.py` builds `historical_dwell.csv` and corridor-residence calibration only from prior completed runs under `data/calibration/history/`. The current run is excluded from calibration. Runtime features then use only events/evidence available up to each prediction timestamp.

## Tests

```bash
python -m pytest -q
```

Current packaged suite is executed with `python -m pytest -q`; the final validation pass is recorded in `BOTTLENECK_SIMULATOR_INTEGRATION_FIXES.md`.

## Performance note

The runtime now batches feature preparation, XGBoost inference, and exact TreeSHAP during unpaced replay (default batch size 256) instead of repeating pandas/DMatrix setup for every prediction. DARK particle-filter cost is unchanged; production 3000-particle replay should still be benchmarked on the target machine.
