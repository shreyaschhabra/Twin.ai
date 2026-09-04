"""Navigation placeholders for views implemented in later steps.

Each one renders an honest empty state describing what will live there and which
existing artifact it will read, so nothing implies data the prototype does not have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from dashboard.context import DashboardContext


def _placeholder(title: str, description: str, sources: list[str]) -> None:
    st.header(title)
    st.info(description)
    st.caption("Will read: " + ", ".join(f"`{source}`" for source in sources))


def render_overview(context: DashboardContext) -> None:
    st.header("Overview")

    columns = st.columns(4)
    columns[0].metric("Factory", context.factory.status)
    columns[1].metric(
        "Stations", context.factory.station_count if context.factory.station_count else "—"
    )
    columns[2].metric(
        "DARK zones", context.factory.dark_zone_count if context.factory.exists else "—"
    )
    runs = context.repository.count_runs() if context.repository else 0
    columns[3].metric("Production days recorded", runs if context.repository else "—")

    if context.factory.status != "VALID":
        st.warning(
            "No usable factory configuration. The dashboard reads the same factory.json "
            "the simulator uses; point it at a valid file or generate a demo definition "
            "from the sidebar."
        )
    elif context.factory.is_demo:
        st.warning(
            "This is a generated demo factory. Station parameters are illustrative "
            "prototype values, not measured plant data."
        )

    if runs == 0:
        st.info("No completed production runs yet.")

    st.caption(
        "This dashboard is downstream of the existing Digital Twin system. It reads "
        "completed run artifacts and prediction streams; it does not simulate or predict."
    )


def render_live_twin(context: DashboardContext) -> None:
    _placeholder(
        "Live Twin",
        "Live line visualisation is not implemented in this step.",
        ["runtime_events.csv", "system_health.json"],
    )


def render_bottlenecks(context: DashboardContext) -> None:
    _placeholder(
        "Bottlenecks",
        "Station bottleneck risk views are not implemented in this step. Bottleneck risk "
        "is a station/flow signal and stays separate from vehicle defect risk.",
        ["bottleneck_predictions.jsonl"],
    )


def render_defects(context: DashboardContext) -> None:
    _placeholder(
        "Defects",
        "Per-vehicle defect risk views are not implemented in this step. Defect risk is a "
        "vehicle-quality signal and stays separate from station bottleneck risk.",
        ["defect_predictions.jsonl"],
    )


def render_sensor_coverage(context: DashboardContext) -> None:
    st.header("Sensor Coverage")
    if context.factory.status != "VALID":
        st.info("No valid factory configuration to describe coverage for.")
        return
    counts = context.factory.sensor_coverage_counts()
    columns = st.columns(max(len(counts), 1))
    for column, (level, count) in zip(columns, sorted(counts.items())):
        column.metric(level, count)
    st.caption(
        "Coverage comes from factory.json. DARK-zone membership is separate: it comes "
        "from the factory's darkZones contract (dz.csv at runtime), not from sensor "
        "coverage. Detailed coverage analysis lands in a later step."
    )


def render_what_if(context: DashboardContext) -> None:
    _placeholder(
        "What-If",
        "Scenario comparison is not implemented in this step. Any business or ROI figure "
        "shown here later will be labelled illustrative unless derived from measured data.",
        ["system_run_manifest.json"],
    )
