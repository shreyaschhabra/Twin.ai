"""
Baseline material/component batch scheduling (Step 3 patch 2).

This is deliberately NOT part of ScenarioManager: batch assignment is a
normal production concern that happens for every vehicle at a
batch-relevant station whether or not any scenario is configured. If only
scenario-affected vehicles ever received a batch_id or a
MATERIAL_BATCH_ASSIGNED event, the mere PRESENCE of that data would be a
synthetic tell distinguishing healthy from bad-batch runs — exactly the
shortcut this patch removes.

The schedule is a deterministic, index-based rotation (no RNG needed —
reproducibility is automatic from n_vehicles/config alone): every
`cohort_size` visits to a batch-relevant station, a new batch_id is
minted. A BAD_BATCH scenario never changes this schedule; it only
declares one already-assigned batch_id as latently quality-degraded (see
ScenarioManager.check_batch_exposure), so the SAME master seed produces
the identical observable batch-id sequence whether or not that scenario
is present — only latent exposure differs.

Numbering is PER STATION, each starting at 1001, not one counter shared
across every batch-relevant station. Two different stations track two
different material streams (e.g. adhesive vs. fasteners) in reality, so
they shouldn't share one running counter — and a shared counter would
make "declare batch B1002 as bad" ambiguous about which station's B1002
it means once more than one station is configured. Combined with
station_id, a batch_id is unambiguous.

Like sensor_models_dev.yaml / sensor_models_full.yaml, the batch-relevant-
station config is per-line-config (material_batches_dev.yaml,
material_batches_full.yaml), not shared — dev-line and full-line reuse
the same S01-S12 numbering for different stations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Union

import yaml


class MaterialBatchScheduler:
    def __init__(self, batch_relevant_stations: Dict[str, int], starting_batch_number: int = 1001):
        self.cohort_sizes = dict(batch_relevant_stations)
        self.starting_batch_number = starting_batch_number
        self._visit_counts: Dict[str, int] = {sid: 0 for sid in self.cohort_sizes}
        self._current_batch: Dict[str, str] = {}
        self._next_batch_number: Dict[str, int] = {sid: starting_batch_number for sid in self.cohort_sizes}

    def is_relevant(self, station_id: str) -> bool:
        return station_id in self.cohort_sizes

    def assign(self, station_id: str) -> str:
        count = self._visit_counts[station_id]
        cohort_size = self.cohort_sizes[station_id]
        if count % cohort_size == 0:
            self._current_batch[station_id] = f"B{self._next_batch_number[station_id]}"
            self._next_batch_number[station_id] += 1
        self._visit_counts[station_id] = count + 1
        return self._current_batch[station_id]


def load_batch_relevant_stations(path: Union[str, Path]) -> Dict[str, int]:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Material batch config file not found: {resolved}")
    with resolved.open("r") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("batch_relevant_stations", {}))
