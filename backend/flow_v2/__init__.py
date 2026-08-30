"""
Flow v2: a consequence-based, full-10-minute-precursor Flow ML
formulation, addressing the low positive-diversity / narrow-window
problems diagnosed in Flow v1 (backend/flow/, data/processed/flow_v1/).

Reuses, UNCHANGED: bottleneck-event detection (backend/flow/
bottleneck_events.py), the point-in-time feature builder (backend/flow/
features.py), and the EQUIPMENT_DEGRADATION holdout mask (backend/flow/
holdout.py). What changes is the ML dataset FORMULATION only: the label
window, row sampling/deduplication, and the train/validation/test
grouping -- never the simulator or the underlying causal event stream.
"""
