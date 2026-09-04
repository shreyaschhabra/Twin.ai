"""Live consumption of the prediction streams the existing runtime is writing.

This package reads; it never predicts. It tails the runtime's own JSONL output while a
run executes so the dashboard can show a station's bottleneck-probability timeline (or a
unit's defect-probability timeline) as it is produced, and it keeps that accumulated
history available once the run has finished. The two streams are parsed by separate
state classes and never merged.
"""

from dashboard.live.bottleneck_state import (
    LiveBottleneckState,
    PredictionPoint,
    StationAnalytics,
    StationSeries,
    WarningPeriod,
    parse_point,
)
from dashboard.live.defect_state import (
    DefectPredictionPoint,
    LiveDefectState,
    UnitAnalytics,
    UnitSeries,
)
from dashboard.live.defect_state import WarningPeriod as DefectWarningPeriod
from dashboard.live.defect_state import parse_defect_point
from dashboard.live.session import (
    DEFECT_STREAM,
    LivePredictionFeed,
    LiveRunProgress,
    LiveRunRegistry,
    LiveRunSession,
    LiveRunStatus,
    bottleneck_stream_path,
    defect_stream_path,
    get_registry,
)
from dashboard.live.stream import JsonlTailer, TailResult

__all__ = [
    "DEFECT_STREAM",
    "DefectPredictionPoint",
    "DefectWarningPeriod",
    "JsonlTailer",
    "LiveBottleneckState",
    "LiveDefectState",
    "LivePredictionFeed",
    "LiveRunProgress",
    "LiveRunRegistry",
    "LiveRunSession",
    "LiveRunStatus",
    "PredictionPoint",
    "StationAnalytics",
    "StationSeries",
    "TailResult",
    "UnitAnalytics",
    "UnitSeries",
    "WarningPeriod",
    "bottleneck_stream_path",
    "defect_stream_path",
    "get_registry",
    "parse_defect_point",
    "parse_point",
]
