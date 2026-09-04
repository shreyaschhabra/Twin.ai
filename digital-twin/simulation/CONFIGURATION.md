# Simulation configuration

`factory.json` is the fixed physical line: contiguous station IDs, processing and buffer parameters, sensor coverage, checkpoints, and DARK zones. A scenario supplies only a seed, duration, and dynamic degradation. `defects.json` defines defect introduction and downstream effects.

Sensor coverage determines the emitted telemetry: `PARTIAL` stations emit `VIBRATION` (g) and `TEMPERATURE` (C); `HIGH` stations also emit `CURRENT` (A) and `TORQUE` (Nm); `NONE` emits no telemetry. Defect `sensorEffects` may use any emitted sensor type, including `TORQUE`, for example `"sensorEffects":{"TORQUE":{"meanShift":4.0}}`.

The simulator accepts filesystem inputs and writes one independent run directory. Run the default
example from a build directory with `simulation`, or choose files explicitly:

`simulation --factory config/factory.json --scenario config/scenarios/degradation.json --defects config/defects.json --output output/run_001`

For bulk training, an external scenario generator supplies one `scenario.json` and optional
matching `defects.json` per invocation. No ZIP, extraction, or packaging step occurs in the
simulation path. Each `--output` directory is a self-contained run artifact.

Every run contains `stations.csv`, `units.csv`, `station_events.csv`, `sensor_readings.csv`,
`manual_checks.csv`, `inspection_results.csv`, `checkpoint_events.csv`, `station_checkpoints.csv`,
`runtime_events.csv`, `dz.csv`, and `run_metadata.json`. `dz.csv` is the stable factory topology
interface for runtime consumers:
`dark_zone_id,name,start_station_id,end_station_id,sensor_telemetry,manual_checks,checkpoints`.

`runtime_events.csv` is the ordered **live public event bus**. It interleaves public station
boundary/events (`record_type=STATION`) with observable checkpoint evidence
(`record_type=EVIDENCE`) using a monotonically increasing `sequence`. The file is flushed as
events occur so `bottlenecks_prediction/run_current.py` can tail it while the simulator runs.
It does not expose hidden internal DARK processing truth.

A DARK zone is an internal inclusive station range defined only in `factory.json`. Normal unit
movement events for its stations are suppressed. `station_events.csv` instead records
`DARK_ZONE_ENTERED` and `DARK_ZONE_EXITED` with a `dark_zone_id` and unit identity. RFID and
POWER_DRAW checkpoints remain observable inside DARK zones. RFID may identify the unit; a
POWER_DRAW checkpoint may legitimately leave `unit_id` blank and is interpreted downstream as
station/population evidence rather than hidden truth. Sensors remain station-level and never
contain a unit ID. Manual checks and other non-identifying observations may also leave identity
blank according to their public schema.

Defects live on individual units. Introduction probability is `baseProbability + degradationLevel * degradationSensitivity`, clamped to one. Cycle effects multiply after the normal degradation multiplier; CV additions accumulate. Sensor shifts add to normal degradation/activity signals. Multiple defect manual-check effects use the maximum configured failure probability. Inspections independently attempt each applicable defect and report only detected defects.
