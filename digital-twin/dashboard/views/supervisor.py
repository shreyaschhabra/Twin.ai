"""Supervisor page -- Action Center.

Answers one question: *what needs attention right now?* It is scoped to a single
run's latest predictions and is built from status cards and ranked tables, not
charts. All aggregation lives in :mod:`dashboard.stakeholder.supervisor`; this
module only lays the results out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard.stakeholder.streams import load_run_streams
from dashboard.stakeholder.supervisor import (
    KIND_BOTTLENECK,
    build_priority_queue,
    quality_watch,
    shift_health,
    station_watch,
)

if TYPE_CHECKING:
    from dashboard.context import DashboardContext

_TREND_LABEL = {
    "RISING": "▲ rising",
    "FALLING": "▼ falling",
    "STABLE": "▬ stable",
    "UNKNOWN": "– n/a",
}


def _current_run(context: "DashboardContext"):
    runs = context.run_history()
    if not runs:
        return None, []
    selected = st.session_state.get("selected_run_id")
    chosen = next((run for run in runs if run.run_id == selected), None) or runs[0]
    return chosen, runs


def render_supervisor(context: "DashboardContext") -> None:
    st.header("Supervisor · Action Center")
    st.caption("Live operational picture for the current run — what to act on now.")

    run, runs = _current_run(context)
    if run is None:
        st.info(
            "No run yet. Start one from the Run Factory page; this page then shows the "
            "current alerts, the stations and units to watch, and runtime trust."
        )
        return

    streams = load_run_streams(run)
    health = shift_health(streams)

    # -- KPI strip --------------------------------------------------------------------
    kpi = st.columns(5)
    kpi[0].metric("Current run", run.run_id)
    kpi[1].metric("Production day", run.production_day)
    kpi[2].metric(
        "Active bottleneck alerts",
        health.active_bottleneck_alerts,
        delta="action" if health.active_bottleneck_alerts else None,
        delta_color="inverse",
    )
    kpi[3].metric(
        "Active defect alerts",
        health.active_defect_alerts,
        delta="action" if health.active_defect_alerts else None,
        delta_color="inverse",
    )
    kpi[4].metric(
        "System health",
        health.health_status,
        delta="degraded" if health.degraded else None,
        delta_color="inverse",
    )

    if health.intervention_required:
        st.error("Intervention required — see Priority Actions below.")
    else:
        st.success("No active alerts. Runtime health is PASS.")

    # -- Priority Actions -----------------------------------------------------------
    st.subheader("Priority Actions")
    st.caption(
        "Bottleneck and defect interventions in one queue, ranked by each item's own "
        "risk. Bottleneck risk is a station/flow risk; defect risk is a unit-quality "
        "risk — they are never combined."
    )
    queue = build_priority_queue(streams)
    if not queue:
        st.success("Nothing actionable in the latest predictions for this run.")
    else:
        st.dataframe(
            [
                {
                    "Type": "Bottleneck" if action.kind == KIND_BOTTLENECK else "Defect",
                    "Station / Unit": (
                        action.station
                        if action.kind == KIND_BOTTLENECK
                        else f"{action.reference} @ {action.station}"
                    ),
                    "Risk %": action.risk_percent,
                    "Confidence %": action.confidence_percent,
                    "Top driver(s)": ", ".join(action.drivers) or "No explanation available",
                    "Flags": " ".join(
                        flag
                        for flag, on in (
                            ("⚠ low-confidence", action.low_confidence),
                            ("DARK/inferred", action.dark_context),
                        )
                        if on
                    ),
                    "Recommended action": action.recommended_action,
                }
                for action in queue
            ],
            hide_index=True,
            use_container_width=True,
        )

    # -- Station Watch / Quality Watch --------------------------------------------
    left, right = st.columns(2)
    with left:
        st.subheader("Station Watch")
        st.caption("Highest-risk stations right now (bottleneck stream).")
        watch = station_watch(streams)
        if not watch:
            st.info("No bottleneck predictions for this run yet.")
        else:
            st.dataframe(
                [
                    {
                        "Station": row.station,
                        "Risk %": row.risk_percent,
                        "Alert": "🔴" if row.warning else "",
                        "Confidence %": row.confidence_percent,
                        "Trend": _TREND_LABEL.get(row.trend, row.trend),
                    }
                    for row in watch
                ],
                hide_index=True,
                use_container_width=True,
            )
    with right:
        st.subheader("Quality Watch")
        st.caption("Highest-risk units right now, with where they are.")
        quality = quality_watch(streams)
        if not quality:
            st.info("No defect predictions for this run yet.")
        else:
            st.dataframe(
                [
                    {
                        "Unit": row.unit,
                        "Risk %": row.risk_percent,
                        "Current / last station": row.station,
                        "Inspection priority": row.inspection_priority,
                        "Confidence %": row.confidence_percent,
                    }
                    for row in quality
                ],
                hide_index=True,
                use_container_width=True,
            )

    # -- Shift Health -------------------------------------------------------------
    st.subheader("Shift Health")
    cols = st.columns(4)
    cols[0].metric("Runtime health", health.health_status)
    cols[1].metric("Bottleneck subsystem", health.bottleneck_subsystem)
    cols[2].metric("Defect subsystem", health.defect_subsystem)
    cols[3].metric(
        "Low-confidence now",
        health.low_confidence_bottleneck + health.low_confidence_defect,
    )
    cols2 = st.columns(4)
    cols2[0].metric("DARK / inferred alerts", health.dark_inferred_alerts)
    cols2[1].metric("Bottleneck stream", "available" if health.bottleneck_stream_available else "missing")
    cols2[2].metric("Defect stream", "available" if health.defect_stream_available else "missing")
    cols2[3].metric("Intervention", "required" if health.intervention_required else "not now")

    for note in health.notes:
        if health.intervention_required:
            st.warning(note)
        else:
            st.caption(note)
