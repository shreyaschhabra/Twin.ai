# Digital Twin

Digital Twin is a factory-specific simulation, bottleneck-prediction, defect-prediction, and
runtime-replay project. The repository-root [cli.py](cli.py) is its control
plane; simulation, training, DARK inference, and live runtime remain separate
components behind it.


## Reviewer-safe validated demo

For a fast end-to-end review that does **not** require rebuilding the C++ simulator,
this release includes a completed 10-minute causal simulator run at
`simulation/demo_run/`. After installing the Python requirements, run:

```text
# Windows
py cli.py system run prescribed --run-dir simulation/demo_run --output-dir runtime_output/reviewer_demo --run-id REVIEWER_DEMO --particles 3000 --explain-mode warnings

# Linux/macOS
python3 cli.py system run prescribed --run-dir simulation/demo_run --output-dir runtime_output/reviewer_demo --run-id REVIEWER_DEMO --particles 3000 --explain-mode warnings
```

The validated reference result uses both BASE models and exercises LIGHT + DARK
routes in both subsystems. The expected lifecycle result is `overall_status: PASS`.
If the same output directory already exists, either choose a new directory or add
`--force`.

This demo is intentionally packaged so a reviewer can validate the ML/runtime
integration even on a machine where the simulator toolchain is unavailable. The
first **new random simulator build** still uses CMake `FetchContent` for
`nlohmann/json` and therefore requires that dependency to be available/reachable
during the initial C++ build.

## Setup

Supported platforms are Windows, Linux, and macOS. Use Python 3.11+ and install
the complete Python environment (XGBoost + CatBoost + tests):

```text
# Windows
py -3.11 -m pip install -r requirements.txt

# Linux/macOS
python3 -m pip install -r requirements.txt
```

Subsystem-specific files remain available as `bottlenecks_prediction/requirements.txt`
and `Defect_Model/requirements.txt`, but the root requirements file is the supported
installation path for the complete digital twin.

On Windows, use `py cli.py` when `python` is not the selected launcher. If
`py -0p` reports no interpreter, install/register Python or invoke the known
interpreter directly. The CLI itself is platform-neutral and does not require
PowerShell, Bash, or CMD.

The simulator executable is discovered cross-platform. If no built executable is
found, the CLI attempts a standard CMake build automatically. You can also build
it explicitly:

```text
cmake -S simulation -B simulation/build
cmake --build simulation/build --config Release
```

On Windows the CLI checks Release and Debug `.exe` locations; on Linux/macOS it
checks the normal `simulation/build/simulation` path. `--simulator PATH` remains
available as an explicit override.

## Shell and one-shot commands

Start the interactive shell:

```text
py cli.py
dt> factory add simulation/config/factory.json --id demo-factory
dt> factory list
dt> data generate --count 20
dt> data simulate
dt> train demo-factory --factory-id demo-factory
dt> models use demo-factory
dt> exit
```

The same parser and handlers serve automation:

```text
py cli.py factory add simulation/config/factory.json --id demo-factory
py cli.py data generate --count 20 --seed 2026
py cli.py data simulate
py cli.py factory configure demo-factory --stations simulation/training/runs/run_0001/stations.csv
py cli.py train demo-factory --factory-id demo-factory
py cli.py models list
py cli.py models use demo-factory
```

`factory add` validates and registers `factory.json` in
`.digital_twin/factories.json`; `factory inspect`, `factory list`, and
`factory remove --force` manage that registry. Removing a registration never
deletes the factory JSON or its configured-stations file.

The `C:/Projects/factories/...` form is only an example of a user-owned
factory location: it must be replaced with a JSON file that exists on your
machine. The commands above use the repository's bundled factory definition.

## Workflow

```text
factory.json ──> factory registry/configuration
                         │
                         ├─> scenario generation ─> C++ simulator ─> completed run_* CSVs
                         │                                      │
                         └─> bottleneck feature training <──────┘
                                      │
                      DARK zones? ──┼── yes: causal historical calibration
                                    └── no: skip calibration
                                      │
                    immutable factory model artifact ─> selected-model pointer ─> causal runtime replay/live input
```

The 28-feature bottleneck model is shared by all factories. Every training
operation begins from the protected base model, writes a separate artifact, and
never loads another factory's learned weights. `base` cannot be deleted;
`models use <id>` only switches the small selection pointer and does not
retrain. `models use base` is also runnable: for prescribed/random runs the BASE
model uses that simulator run's own `stations.csv` topology, while factory model
artifacts continue to use their retained configured topology and calibration.

For a factory with DARK zones, training creates historical dwell and (when
needed) corridor-residence calibration from completed training runs only. For a
factory with no DARK zones, calibration is explicitly absent and no DARK code
is run. Runtime reads the artifact's configured station topology, so LIGHT-only
artifacts do not require DARK files.

## Running a trained model

First select the artifact to use. This is instant; it does not train or copy
the model:

```text
# Windows
py cli.py models use factory-a

# Linux/macOS
python3 cli.py models use factory-a
```

There are two post-training run modes.

### Prescribed replay

Use this when a completed simulator run already exists and you want predictions
for that exact event sequence. The completed run must follow the simulator-v2.1 public contract and contain
`stations.csv`, `units.csv`, `runtime_events.csv`, `dz.csv`,
`station_checkpoints.csv`, and `run_metadata.json`. `station_events.csv` may also
exist for audit/history, but completed prediction replay consumes the public bus.

```text
py cli.py run prescribed --run-dir simulation/training/runs/run_0001 --output predictions/factory-a-run-0001.jsonl --unpaced
```

In the interactive shell, omit `py cli.py` and enter the same command after
`dt>`. `--unpaced` processes the timestamp-ordered sequence as fast as
possible, which is normally right for offline analysis. Leave it off to pace
causal delivery at `--mult 60` (60x), or choose another multiplier. Add
`--model-id factory-a` to use an artifact without changing the selected model.
Existing prediction files require `--force`.

### Random end-to-end run

Use this to create a new random scenario, execute the C++ simulator, and
replay it with the selected model in one command. Choose fresh directories for
generated inputs and simulator output; the command deliberately refuses to
overwrite completed data.

```text
py cli.py run random --factory simulation/config/factory.json --generated simulation/training/generated/random-factory-a --runs simulation/training/runs/random-factory-a --output predictions/factory-a-random.jsonl --seed 2026 --unpaced
```

The random command shows generation and simulator progress, then writes the
same JSONL prediction format as prescribed replay. It accepts `--model-id`,
`--mult`, and `--force` with the same meanings. Use `run prescribed` for a
known scenario; use `run random` for a newly generated end-to-end test.

## Data, simulation, and runtime

### Concurrent live bottleneck runtime

For the production-style current run, the simulator and bottleneck consumer are
separate processes. The simulator writes an ordered, flushed
`runtime_events.csv` public bus into
`bottlenecks_prediction/data/input/current_run/`; the bus contains public station
events/boundaries plus observable RFID/POWER_DRAW checkpoint evidence. Start the
bottleneck consumer separately:

```text
cd bottlenecks_prediction
py run_current.py
```

`run_current.py` does not launch the simulator. It uses the selected model pointer
(`models use ...`; BASE if nothing else is selected), derives BASE DARK membership
from `dz.csv`, and for factory artifacts verifies the simulator station/static/DARK
contract matches the selected artifact before inference. DARK calibration is always
prior-only, the public bus is tailed live, and XGBoost + TreeSHAP JSONL predictions
are emitted as the simulator runs. The simulator's internal DARK processing truth
remains hidden.

`data generate` creates reproducible scenarios; `data simulate` invokes the
C++ simulator with executable arguments (not a shell command) and creates
independent `run_*` folders. `data list` and `data delete --force` inspect and
remove completed runs.

`run prescribed` causally replays a completed run; `run random` generates,
simulates, then replays one run. With pacing enabled, `--mult` is both the
simulation-time-to-wall-clock delivery multiplier and the event-delivery speed;
`--unpaced` processes the causal event sequence as fast as possible. Events
remain timestamp ordered in either mode.

Useful regression tests remain under `bottlenecks_prediction/tests`. Diagnostics
such as training metrics are retained in the artifact manifest as metadata but
are not runtime state. DARK particle-filter randomness is deterministically seeded
from `run_id` by default, so replaying the same public run with the same run ID is
reproducible. Factory-training code may supply an explicit training seed.


## Parallel bottleneck + defect operation

The production dashboard does **not** require one merged backend prediction file.
The two ML systems emit independent JSONL streams because they have different
prediction triggers and frequencies. They are synchronized by the simulator clock
and shared identifiers:

```text
                         C++ SIMULATOR
                              │
                    runtime_events.csv
                              │
              ┌───────────────┴───────────────┐
              │                               │
     bottleneck consumer               defect consumer
              │                               │
 bottleneck_predictions.jsonl       defect_predictions.jsonl
              │                               │
              └──────────── dashboard ────────┘

Dashboard synchronization keys:
run_id + timestamp_ms + station_id + unit_id/vehicle_id
```

The root `system` control plane coordinates these consumers without coupling their
models or state. `system run live` starts **both prediction consumers only**; the
simulator remains an independent process and may start before or after the consumers.
Live operation defaults to **fault isolation**. If one prediction process fails, the
external simulator and the healthy ML consumer continue; `system_health.json` becomes
`DEGRADED` and identifies the unavailable subsystem. Use
`--failure-policy fail-fast` for CI/strict validation when the first ML failure should
stop its peer. The simulator is external and is never terminated by either policy.

### Live dual runtime

Start the two consumers:

```text
py cli.py system run live \
  --run-dir bottlenecks_prediction/data/input/current_run \
  --output-dir runtime_output \
  --run-id CURRENT_RUN \
  --failure-policy isolate
```

Then run the simulator normally. Both consumers wait for the same public files, tail
the same ordered bus, and stop only after the simulator publishes `run_metadata.json`
and the bus drains. Outputs remain separate:

```text
runtime_output/
├── bottleneck_predictions.jsonl
├── defect_predictions.jsonl
├── bottleneck_runtime.log
├── defect_runtime.log
├── system_health.json
└── system_run_manifest.json
```

`system_health.json` records process status, selected bottleneck/defect model IDs,
simulator state, prediction counts, and synchronization validation.

### Completed dual replay

For an already completed simulator-v2.1 run:

```text
py cli.py system run prescribed \
  --run-dir simulation/training/runs/run_0001 \
  --output-dir runtime_output/run_0001 \
  --run-id run_0001
```

Both subsystems replay the exact same `runtime_events.csv` public bus. Bottlenecks
consume STATION + RFID/POWER evidence and ignore SENSOR/MANUAL records; defects
consume STATION + SENSOR + MANUAL + causal DARK evidence. Inspection ground truth
is never consumed by runtime inference.

The models can be selected independently. The normal selected-model pointers are
used by default, or one run can override them without mutating those pointers:

```text
py cli.py system run prescribed ... \
  --bottleneck-model-id factory-a \
  --defect-model-id factory-a
```

### Random dual end-to-end check

`system run random` generates one scenario, runs the C++ simulator, then sends the
completed run through both prediction systems:

```text
py cli.py system run random \
  --factory simulation/config/factory.json \
  --generated simulation/training/generated/dual_random_test \
  --runs simulation/training/runs/dual_random_test \
  --output-dir runtime_output/dual_random_test \
  --seed 2026
```

### Operational status

```text
py cli.py system status
```

This reports selected model IDs, current-run file readiness, whether the simulator
run is complete, output locations, synchronization keys, and the last dual-runtime
health record. It does not merge the prediction streams.

### Causality and isolation guarantees

- Bottleneck and defect model selections are independent.
- Both consumers use the same `run_id`, run directory, and simulator clock.
- The current run never calibrates its own DARK estimator.
- `inspection_results.csv` is defect ground truth only and is absent from live input.
- SENSOR/MANUAL public records do not modify bottleneck state.
- Defect PF state is independent from bottleneck PF state.
- A selected factory artifact is rejected when its frozen factory/DARK contract does
  not match the simulator run.
- Live mode defaults to subsystem isolation: one ML failure marks health `DEGRADED`
  while the external simulator and healthy ML consumer continue.
- Strict validation can opt into `--failure-policy fail-fast`.
- DARK PF retrospective history revisions never rewind defect feature time. For this
  prototype, if later evidence makes the PF place a newly discovered transition in
  the already-processed past, that transition is dropped from the online defect
  feature stream. The evidence still updates the PF's current belief; only the stale
  historical transition is ignored.


## Dashboard and final validation references

- [DASHBOARD_CONTRACTS.md](DASHBOARD_CONTRACTS.md) defines the exact separate
  bottleneck/defect output fields, synchronization rules, SHAP fields, DARK
  confidence handling, and the important defect `threshold_crossed` versus
  actionable `warning` semantics.
- [FINAL_SYSTEM_VALIDATION.md](FINAL_SYSTEM_VALIDATION.md) records the final
  regression and black-box simulator/dual-runtime validation.
