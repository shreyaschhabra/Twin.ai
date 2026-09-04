"""DigitalTwin.ai dashboard.

A downstream stakeholder interface over the existing Digital Twin system. It reads
completed run artifacts and prediction streams and keeps its own SQLite run history.
It never simulates, never trains or runs a model, and is never a dependency of the
simulator or the ML runtimes -- deleting `dashboard/` or its database leaves the rest
of the system fully operational.
"""

__all__ = []
