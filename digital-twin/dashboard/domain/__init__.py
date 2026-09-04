"""Dashboard domain models.

Plain dataclasses with no Streamlit, SQL, or simulator dependencies, so they can be
shared freely between storage, ingestion and views.
"""

from dashboard.domain.metrics import RunMetricsSummary
from dashboard.domain.run import Run, RunStatus
from dashboard.domain.station import Station
from dashboard.domain.vehicle import Vehicle

__all__ = ["Run", "RunMetricsSummary", "RunStatus", "Station", "Vehicle"]
