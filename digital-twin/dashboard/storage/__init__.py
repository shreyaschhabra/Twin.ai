"""Dashboard-owned SQLite persistence.

Deleting the database costs the dashboard only its cached run history; the simulator,
the models and the coordinated runtime never read it.
"""

from dashboard.storage.database import DashboardDatabase
from dashboard.storage.migrations import LATEST_VERSION, apply_migrations, get_current_version
from dashboard.storage.repositories import RunRepository
from dashboard.storage.schema import SCHEMA_VERSION

__all__ = [
    "DashboardDatabase",
    "LATEST_VERSION",
    "RunRepository",
    "SCHEMA_VERSION",
    "apply_migrations",
    "get_current_version",
]
