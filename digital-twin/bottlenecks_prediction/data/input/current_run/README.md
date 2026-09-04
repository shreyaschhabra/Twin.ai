# Simulator drop zone

This folder is the hand-off point from the simulator to the bottleneck consumer.

## Live production flow

The simulator runs independently and writes/updates this folder. Start the bottleneck
consumer with:

```bash
python run_current.py
```

Live mode requires the simulator v2.1 public files:
- `stations.csv`
- `units.csv`
- `dz.csv` (authoritative DARK topology)
- `station_checkpoints.csv`
- `runtime_events.csv` (ordered public event bus)

The simulator also writes `run_metadata.json` when the run completes. RFID and
POWER_DRAW records remain observable inside DARK zones through the public event bus.

## Bundled validation example

The small completed CSV set committed in this folder is retained for an immediate
replay smoke test. Its `dz.csv` explicitly migrates the legacy example's five
single-station DARK zones to the new topology contract.

Run it with:

```bash
python run_current.py --mode replay
```

Replay additionally requires `station_events.csv` and `run_metadata.json` to prove
that the input is a completed run; optional manual/checkpoint files are used when
present. DARK calibration is built only from prior completed runs under
`data/calibration/history/`; the current run is never used to calibrate itself.
