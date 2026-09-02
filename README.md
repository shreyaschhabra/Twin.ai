# DigitalTwin.ai — Minimal Data Simulation

This folder is the simplified version of the original `Data_Simulation` package.
The simulation logic is preserved; only module/config organization was consolidated.

## Structure

```text
Data_Simulation_Minimal/
├── factory.yaml       # factory + stations + sensors + material-batch config
├── config.py          # schemas + strict config loader
├── models.py          # events, vehicles, buffers, sensors, QC, batches, RNG, genealogy
├── scenarios.py       # scenario definitions, effects, latent truth, scenario manager
├── simulation.py      # station runtime + discrete-event engine
├── historical.py      # shift scheduler + flow calibration + historical dataset writer
├── observability.py   # public/observable event projection policy
└── generate.py        # one CLI for standard and calibrated dataset generation
```

## Dependencies

Python 3.10+. Install once with:

```bash
pip install -r requirements.txt
```

## Generate data

Standard 100-shift dataset:

```bash
python generate.py
```

Flow-calibrated dataset:

```bash
python generate.py --mode calibrated
```

Small smoke run:

```bash
python generate.py --shifts 1 --vehicles 20 --output data/smoke
```

Useful knobs: `--shifts`, `--vehicles`, `--seed`, `--batch-size`, `--output`.

Generated outputs keep the same observable/latent split and Parquet table logic.
