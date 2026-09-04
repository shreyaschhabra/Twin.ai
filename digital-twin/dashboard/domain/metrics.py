"""Run-level metric containers.

Placeholder for later analytics. Counts recorded here come from ingested artifacts;
any business or ROI figure added later must be labelled illustrative unless it is
derived from measured data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunMetricsSummary:
    """Aggregate counts for one production run."""

    run_id: str
    bottleneck_prediction_count: int = 0
    bottleneck_warning_count: int = 0
    defect_prediction_count: int = 0
    defect_warning_count: int = 0
    #: True when any figure here is illustrative rather than measured.
    is_illustrative: bool = False
