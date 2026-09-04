# DigitalTwin.ai Dashboard

A stakeholder interface that sits **downstream** of the existing Digital Twin system.

```
factory.json
    ↓
existing scenario generator          simulation/training/scenario_generator.py
    ↓
existing random-run / simulation     simulation/training/orchestrator.py + C++ simulator
    ↓
existing prediction/runtime outputs  bottleneck_predictions.jsonl, defect_predictions.jsonl,
    ↓                                system_health.json, system_run_manifest.json
completed run artifacts
    ↓
dashboard ingestion                  dashboard/ingestion/
    ↓
SQLite                               dashboard/data/dashboard.db
    ↓
stakeholder views                    dashboard/views/
```

## Running it

```bash
py -m pip install -r dashboard/requirements.txt
```

```bash
py -m streamlit run dashboard/app.py
```

Use `py -m streamlit`, not a bare `streamlit`: pip installs the launcher into a
`Scripts\` directory that is not on PATH by default. `py` also pins the interpreter that
actually has the project's dependencies, which matters on a machine with several Pythons
installed.

The app starts cleanly with no factory.json, no database, no completed runs, no
prediction files, and no running runtime. Each of those renders an empty state.

## Boundaries

## The run loop

1. Click **RUN FACTORY**. Pick a simulated day length (a full 8h shift takes 20-30 min of
   wall clock; the 10-minute smoke test finishes in under a minute).
2. Copy the command and run it. It is preflighted, so it runs as-is.
3. **Run History -> Rebuild from artifacts.** The run appears as the next Production Day.

The command is verified before it is shown. Each check corresponds to a failure that was
observed against this repository:

| Check | Failure it prevents |
|---|---|
| Destination directories free (run id skips ahead if not) | `Generated-input directory already contains files` |
| Model's DARK contract matches the factory's corridor | `S15:sensor_coverage expected='NONE' current='NORMAL'` |
| Model's `station_id` levels cover every non-source station | `Found N unknown model-category outputs` |
| `catboost` importable | `No module named 'catboost'` |
| Simulator binary present | missing-executable error, or a silent CMake build |
| `PYTHONUTF8=1` always prefixed | `'charmap' codec can't encode character '⚠'` |

If a check fails the dashboard shows the blocker and the remedy instead of a command. It
never displays a command it believes will fail.

The bottleneck model is pinned explicitly with `--bottleneck-model-id`, chosen by
verifying coverage rather than trusting the saved selection. Your saved selection is
never modified.

**The dashboard never executes the system on page load.** Rendering reads artifacts and
the dashboard's own SQLite file. The RUN FACTORY control is explicit, and today it hands
the operator the exact `cli.py` command rather than driving execution itself.

**One seam only.** `dashboard/orchestration/existing_runtime_adapter.py` is the sole
module permitted to import the simulator, scenario generator, orchestrator or
`system_runtime`. A test enforces this.

**The dashboard is never a dependency.** No upstream module imports `dashboard`, and a
test enforces that too. Deleting `dashboard/` or its database leaves the simulator, both
models and the coordinated runtime fully operational.

**The database is disposable.** Delete `dashboard/data/dashboard.db` and rebuild history
from completed run artifacts (Run History → *Rebuild history from completed run
artifacts*, or `RunIngestor.rebuild_from_artifacts()`).

**Prediction streams stay separate.** Bottleneck risk is a station/flow signal; defect
risk is a vehicle-quality signal. They are never merged or averaged. `warning` is the
actionable alert on both streams and is never recomputed from probability and threshold.

**`system_health.json` and `system_run_manifest.json` stay authoritative.** The dashboard
reads them; it never derives a competing verdict. Only `overall_status == "PASS"` counts
as healthy.

## Factory configuration

*Configuration defines the plant; the intelligence operates on the plant.*

The dashboard reads the same `factory.json` the simulator consumes — it never maintains a
separate topology.

| Situation | Behaviour |
|---|---|
| File present and valid | Loaded as-is |
| File present but invalid | Reported INVALID, **left untouched** |
| File absent | One deterministic demo definition generated and saved |
| File absent, generation disabled | Reported MISSING |

An existing `factory.json` is **never** overwritten automatically. `generate_demo_factory`
and `write_factory` raise `FileExistsError` unless `overwrite=True` is passed explicitly.

The demo generator (`dashboard/factory/generator.py`) produces 30–50 stations with mixed
archetypes, uneven sensor coverage, and 2–3 internal DARK corridors of 2–3 stations each,
every one containing an unobserved manual cell. Output is a pure function of the seed and
is validated against the simulator contract before it is returned.

### Validation

`dashboard/factory/validator.py` mirrors `simulation/src/ConfigLoader.cpp` and reports two
channels:

- **errors** — the simulator would reject this file.
- **warnings** — the simulator accepts it, but it breaches a dashboard *demo* policy.

The 3-station DARK corridor cap applies **only to the demo generator**. It surfaces as a
warning on operator-supplied factories, never an error: the repository's own
`simulation/config/factory.json` has a legitimate 4-station corridor (`DZ_BODY_01`,
stations 11-14) and must never be reported as invalid.

**Do not shorten a real corridor to silence that warning.** A trained factory model's
contract (`factory_models/<id>/configured_stations.csv`) records which stations are DARK.
Changing the corridor extent makes the run fail its contract check with e.g.
`S15:sensor_coverage expected='NONE' current='NORMAL'`, and the model must be retrained.

## Configuration

| Environment variable | Default |
|---|---|
| `DT_DASHBOARD_FACTORY` | `simulation/config/factory.json` |
| `DT_DASHBOARD_DB` | `dashboard/data/dashboard.db` |
| `DT_DASHBOARD_RUNS` | `simulation/training/runs` |
| `DT_DASHBOARD_GENERATED` | `simulation/training/generated` |
| `DT_DASHBOARD_PREDICTIONS` | `runtime_output` |
| `DT_DASHBOARD_DEMO_SEED` | `42` |
| `DT_DASHBOARD_ALLOW_DEMO_FACTORY` | `true` |

## Run model

One completed run = one simulated production day. The `production_day` index lives in the
dashboard's database; the simulator has no such concept and was not modified to gain one.

## Tests

```bash
py -m pytest dashboard/tests -q
```
