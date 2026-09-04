"""Plant Manager page -- Plant Performance.

Answers: *where is plant performance deteriorating, and what keeps recurring?*
Managerial altitude -- patterns, recurrence and concentration across a scope of
production days, not single-event investigation. Aggregation lives in
:mod:`dashboard.stakeholder.plant`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard.stakeholder.plant import (
    defect_concentration,
    observability,
    performance_trend,
    recurring_constraints,
    scope_kpis,
)
from dashboard.stakeholder.streams import load_scope, resolve_scope, scope_options

if TYPE_CHECKING:
    from dashboard.context import DashboardContext

_SCOPE_KEY = "plant_manager_scope"


def render_plant_manager(context: "DashboardContext") -> None:
    st.header("Plant Manager · Plant Performance")
    st.caption(
        "Trends, recurring constraints and loss concentration across production days."
    )

    runs = context.run_history()
    if not runs:
        st.info(
            "Plant performance appears here once completed production days have been "
            "ingested. Use the Run Factory page to run the next one."
        )
        return

    options = scope_options(runs)
    choice = st.selectbox("Scope", options, key=_SCOPE_KEY)
    scoped_runs = resolve_scope(
        runs, choice, selected_run_id=st.session_state.get("selected_run_id")
    )
    scope = load_scope(scoped_runs)
    kpi = scope_kpis(scope)

    # -- KPI strip --------------------------------------------------------------------
    cols = st.columns(5)
    cols[0].metric("Production days", kpi.production_days)
    cols[1].metric("Bottleneck alerts", kpi.bottleneck_alerts)
    cols[2].metric("Defect alerts", kpi.defect_alerts)
    cols[3].metric("Affected stations", kpi.affected_stations)
    cols[4].metric("Avg prediction confidence", f"{kpi.avg_confidence_percent}%")

    if any(rs.is_demo for rs in scope):
        st.caption("⚠️ Scope includes demo runs — figures are illustrative, not plant data.")

    # -- Performance Trend --------------------------------------------------------
    st.subheader("Performance Trend")
    trend = performance_trend(scope)
    if len(trend) < 2:
        st.caption(
            "A trend needs at least two production days in scope. Widen the scope to "
            "\"All Runs\" once more days are available."
        )
    if trend:
        st.caption("Bottleneck activity (station alerts / records) by production day.")
        st.line_chart(
            [
                {
                    "Day": point.production_day,
                    "Alerting stations": point.bottleneck_alert_stations,
                    "Bottleneck records": point.bottleneck_records,
                }
                for point in trend
            ],
            x="Day",
        )
        st.caption("Defect activity (unit alerts / records) by production day — a separate series.")
        st.line_chart(
            [
                {
                    "Day": point.production_day,
                    "Alerting units": point.defect_alert_units,
                    "Defect records": point.defect_records,
                }
                for point in trend
            ],
            x="Day",
        )
        st.dataframe(
            [
                {
                    "Day": point.production_day,
                    "Run": point.run_id,
                    "Alerting stations": point.bottleneck_alert_stations,
                    "Alerting units": point.defect_alert_units,
                    "Avg confidence %": point.avg_confidence_percent,
                    "Runtime": "degraded" if point.degraded else "PASS",
                }
                for point in trend
            ],
            hide_index=True,
            use_container_width=True,
        )

    # -- Recurring Constraints --------------------------------------------------
    st.subheader("Recurring Constraints")
    st.caption(
        "Stations ranked by how many production days in scope they were affected by a "
        "bottleneck warning."
    )
    constraints = recurring_constraints(scope)
    if not constraints:
        st.success("No bottleneck warnings anywhere in the selected scope.")
    else:
        st.dataframe(
            [
                {
                    "Station": c.station,
                    "Days affected": f"{c.days_affected} / {c.days_in_scope}",
                    "Alert records": c.alert_count,
                    "Risk level": c.risk_level,
                    "Peak risk %": c.peak_risk_percent,
                    "Avg confidence %": c.avg_confidence_percent,
                    "Major drivers": ", ".join(c.drivers) or "—",
                }
                for c in constraints
            ],
            hide_index=True,
            use_container_width=True,
        )

    # -- Quality & Loss Concentration -----------------------------------------
    st.subheader("Quality & Loss Concentration")
    st.caption("Stations where defect exposure recurs (defect stream, warning flag).")
    concentration = defect_concentration(scope)
    if not concentration:
        st.success("No defect warnings anywhere in the selected scope.")
    else:
        st.dataframe(
            [
                {
                    "Station / area": c.station,
                    "Days affected": f"{c.days_affected} / {kpi.production_days}",
                    "Defect events": c.defect_events,
                    "Units affected": c.units_affected,
                    "Peak risk %": c.peak_risk_percent,
                    "Avg confidence %": c.avg_confidence_percent,
                }
                for c in concentration
            ],
            hide_index=True,
            use_container_width=True,
        )

    # -- Observability & Reliability ----------------------------------------
    st.subheader("Observability & Reliability")
    obs = observability(scope, context.factory.data)
    cols = st.columns(4)
    cols[0].metric(
        "Instrumented stations",
        f"{obs.total_stations - obs.coverage_breakdown.get('NONE', 0)} / {obs.total_stations}",
    )
    cols[1].metric("DARK-zone stations", obs.dark_zone_stations)
    cols[2].metric("Bottleneck confidence", f"{obs.bottleneck_confidence_percent}%")
    cols[3].metric("Defect confidence", f"{obs.defect_confidence_percent}%")
    cols2 = st.columns(4)
    cols2[0].metric("Low-confidence predictions", obs.low_confidence_predictions)
    cols2[1].metric("DARK / inferred predictions", obs.dark_inferred_predictions)
    cols2[2].metric("Degraded runs in scope", f"{obs.degraded_runs} / {obs.runs_in_scope}")
    cols2[3].metric(
        "Subsystem issue runs",
        obs.bottleneck_subsystem_issue_runs + obs.defect_subsystem_issue_runs,
    )
    if obs.coverage_breakdown:
        st.caption(
            "Sensor coverage: "
            + " · ".join(f"{level}: {count}" for level, count in obs.coverage_breakdown.items())
            + ". DARK membership comes from the factory DARK-zone contract, not sensor "
            "coverage; low state_confidence marks reconstructed state."
        )
    if obs.degraded_runs:
        st.warning(
            f"{obs.degraded_runs} run(s) in scope reported a non-PASS coordinated runtime "
            "status. The healthy stream is still shown; the failed one is treated as stale."
        )
