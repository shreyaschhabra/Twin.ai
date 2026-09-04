"""Downstream ingestion of completed run artifacts.

Read-only with respect to the existing system: these modules parse artifacts the
simulator and coordinated runtime have already written, and write only into the
dashboard's own database.
"""

from dashboard.ingestion.bottleneck_reader import (
    BottleneckStreamSummary,
    read_bottleneck_summary,
)
from dashboard.ingestion.defect_reader import DefectStreamSummary, read_defect_summary
from dashboard.ingestion.run_ingestor import (
    IncompleteRunError,
    IngestionResult,
    RunIngestor,
    factory_fingerprint,
)
from dashboard.ingestion.runtime_reader import (
    HealthView,
    health_view,
    read_run_metadata,
    read_system_health,
    read_system_manifest,
)

__all__ = [
    "BottleneckStreamSummary",
    "DefectStreamSummary",
    "HealthView",
    "IncompleteRunError",
    "IngestionResult",
    "RunIngestor",
    "factory_fingerprint",
    "health_view",
    "read_bottleneck_summary",
    "read_defect_summary",
    "read_run_metadata",
    "read_system_health",
    "read_system_manifest",
]
