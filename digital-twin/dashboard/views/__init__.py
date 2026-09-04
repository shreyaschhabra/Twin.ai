"""Streamlit views.

Views read from a :class:`dashboard.context.DashboardContext` and never touch SQL,
the simulator, or the ML runtimes directly. The three stakeholder views delegate
their aggregation to :mod:`dashboard.stakeholder` and stay layout-only.
"""

from dashboard.views.leadership import render_leadership
from dashboard.views.operations import (
    render_bottlenecks,
    render_defects,
    render_live_twin,
    render_sensor_coverage,
)
from dashboard.views.plant_manager import render_plant_manager
from dashboard.views.run_factory import render_run_factory
from dashboard.views.run_history import SELECTED_RUN_KEY, render_run_history
from dashboard.views.supervisor import render_supervisor

__all__ = [
    "SELECTED_RUN_KEY",
    "render_bottlenecks",
    "render_defects",
    "render_leadership",
    "render_live_twin",
    "render_plant_manager",
    "render_run_factory",
    "render_run_history",
    "render_sensor_coverage",
    "render_supervisor",
]
