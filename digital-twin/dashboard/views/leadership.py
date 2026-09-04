"""Leadership page -- Executive Economics.

A financial/strategic overview, not a re-render of the Plant Manager page. It
answers: *how is the operation performing financially, where are we losing money,
and what is improvement worth?*

The repository has no measured plant financials, so every figure here is
``observed run events x a user assumption`` and is labelled Estimated / Modeled /
Illustrative. Calculations live in :mod:`dashboard.stakeholder.economics` and are
Streamlit-free and deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard.stakeholder.economics import (
    EconomicsAssumptions,
    financial_overview,
    observe_economics,
    profit_loss_trend,
    quality_loss,
    scenario_savings,
    station_economics,
    what_matters_most,
)
from dashboard.stakeholder.streams import load_scope, resolve_scope, scope_options

if TYPE_CHECKING:
    from dashboard.context import DashboardContext

_SCOPE_KEY = "leadership_scope"
_ASSUMPTION_KEYS = {
    "revenue_per_unit": "econ_revenue_per_unit",
    "revenue_per_station_operation": "econ_revenue_per_station",
    "maintenance_cost_per_alarm": "econ_maint_per_alarm",
    "cost_per_defective_unit": "econ_cost_per_defect",
    "downtime_cost_per_alarm": "econ_downtime_per_alarm",
    "scrap_rework_cost_per_unit": "econ_scrap_per_unit",
}


def _money(value: float, currency: str = "$") -> str:
    return f"{currency}{value:,.0f}"


def _assumptions_controls() -> EconomicsAssumptions:
    defaults = EconomicsAssumptions()
    with st.expander("Economics Assumptions (illustrative — you set these)", expanded=False):
        st.caption(
            "The simulator does not measure revenue, cost or profit. These assumptions "
            "are multiplied by observed run events to produce the modeled figures below."
        )
        row1 = st.columns(3)
        revenue_per_unit = row1[0].number_input(
            "Revenue per unit", min_value=0.0, value=defaults.revenue_per_unit,
            step=50.0, key=_ASSUMPTION_KEYS["revenue_per_unit"],
        )
        revenue_per_station = row1[1].number_input(
            "Revenue per station/operation (optional)", min_value=0.0, value=0.0,
            step=10.0, key=_ASSUMPTION_KEYS["revenue_per_station_operation"],
            help="Flat revenue credited per unit per value-adding operation. 0 = disabled.",
        )
        maintenance_cost = row1[2].number_input(
            "Maintenance cost per alarm", min_value=0.0,
            value=defaults.maintenance_cost_per_alarm, step=25.0,
            key=_ASSUMPTION_KEYS["maintenance_cost_per_alarm"],
        )
        row2 = st.columns(3)
        cost_per_defect = row2[0].number_input(
            "Cost per defective unit", min_value=0.0,
            value=defaults.cost_per_defective_unit, step=25.0,
            key=_ASSUMPTION_KEYS["cost_per_defective_unit"],
        )
        downtime_cost = row2[1].number_input(
            "Downtime / lost-production cost per alarm (optional)", min_value=0.0,
            value=0.0, step=25.0, key=_ASSUMPTION_KEYS["downtime_cost_per_alarm"],
        )
        scrap_cost = row2[2].number_input(
            "Scrap / rework cost per unit (optional)", min_value=0.0, value=0.0,
            step=25.0, key=_ASSUMPTION_KEYS["scrap_rework_cost_per_unit"],
        )
    return EconomicsAssumptions(
        revenue_per_unit=revenue_per_unit,
        revenue_per_station_operation=revenue_per_station or None,
        maintenance_cost_per_alarm=maintenance_cost,
        cost_per_defective_unit=cost_per_defect,
        downtime_cost_per_alarm=downtime_cost,
        scrap_rework_cost_per_unit=scrap_cost,
    )


def render_leadership(context: "DashboardContext") -> None:
    st.header("Leadership · Executive Economics")
    st.caption(
        "Modeled financial picture from run activity and your assumptions. Figures are "
        "Estimated / Illustrative — the simulator measures events, not money."
    )

    runs = context.run_history()
    if not runs:
        st.info(
            "The economic overview appears once production days have been ingested. "
            "It combines observed alerts and defects with the assumptions you set."
        )
        return

    assumptions = _assumptions_controls()

    choice = st.selectbox("Scope", scope_options(runs), key=_SCOPE_KEY)
    scoped_runs = resolve_scope(
        runs, choice, selected_run_id=st.session_state.get("selected_run_id")
    )
    scope = load_scope(scoped_runs)
    observed = observe_economics(scope)
    overview = financial_overview(observed, assumptions)
    currency = assumptions.currency

    st.caption(
        f"Scope: {len(scope)} production day(s) · {observed.units_produced} unit(s) · "
        f"{observed.maintenance_alarms} modeled maintenance alarm(s) · "
        f"{observed.defective_units} unit(s) flagged for defects."
    )
    if any(rs.is_demo for rs in scope):
        st.warning("Scope includes demo runs — figures are illustrative, not plant data.")

    # -- A. Financial Overview ------------------------------------------------
    st.subheader("A · Financial Overview (Estimated)")
    row1 = st.columns(3)
    row1[0].metric("Estimated revenue", _money(overview.estimated_revenue, currency))
    row1[1].metric("Estimated maintenance cost", _money(overview.estimated_maintenance_cost, currency))
    row1[2].metric("Estimated defect loss", _money(overview.estimated_defect_loss, currency))
    row2 = st.columns(3)
    row2[0].metric("Estimated downtime / lost output", _money(overview.estimated_downtime_cost, currency))
    row2[1].metric("Estimated profit", _money(overview.estimated_profit, currency))
    row2[2].metric("Estimated avoidable loss", _money(overview.estimated_avoidable_loss, currency))
    st.caption(overview.basis)

    # -- B. Station Economics ----------------------------------------------
    st.subheader("B · Station Economics (Modeled)")
    stations = station_economics(observed, assumptions)
    if not stations:
        st.info("No station-level activity in scope.")
    else:
        st.dataframe(
            [
                {
                    "Station": row.station,
                    "Revenue contribution": _money(row.revenue_contribution, currency),
                    "Maintenance alarms": row.maintenance_alarm_count,
                    "Est. maintenance cost": _money(row.estimated_maintenance_cost, currency),
                    "Net modeled contribution": _money(row.net_modeled_contribution, currency),
                }
                for row in stations
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Revenue is attributed to stations by observed throughput unless a "
            "revenue-per-operation assumption is set. Modeled, not measured."
        )

    # -- C. Quality Loss --------------------------------------------------
    st.subheader("C · Quality Loss (Estimated)")
    losses = quality_loss(observed, assumptions)
    if not losses:
        st.success("No defect warnings in scope — no modeled quality loss.")
    else:
        st.dataframe(
            [
                {
                    "Station / area": row.station,
                    "Defect events": row.defect_events,
                    "Units affected": row.units_affected,
                    "Estimated defect loss": _money(row.estimated_defect_loss, currency),
                }
                for row in losses
            ],
            hide_index=True,
            use_container_width=True,
        )

    # -- D. Profit / Loss Trend -----------------------------------------
    st.subheader("D · Profit / Loss Trend (Modeled)")
    trend = profit_loss_trend(observed, assumptions)
    if len(trend) < 2:
        st.caption("Select \"All Runs\" (or a wider scope) to see the modeled trend across days.")
    if trend:
        st.line_chart(
            [
                {
                    "Day": point["production_day"],
                    "Modeled revenue": point["modeled_revenue"],
                    "Modeled cost": point["modeled_cost"],
                    "Estimated profit": point["estimated_profit"],
                }
                for point in trend
            ],
            x="Day",
        )

    # -- E. What Matters Most ------------------------------------------
    st.subheader("E · What Matters Most")
    for message in what_matters_most(observed, assumptions):
        st.markdown(f"- {message}")

    # -- F. Digital Twin Value / Scenario --------------------------
    st.subheader("F · Digital Twin Value / Scenario")
    st.caption(
        "Scenario analysis on your assumptions — not a measured or realised ROI. Shows "
        "modeled savings if avoidable alarms / defect losses were reduced."
    )
    st.dataframe(
        [
            {
                "Scenario": scenario["label"],
                "Modeled saving": _money(scenario["modeled_saving"], currency),
                "Modeled profit after": _money(scenario["modeled_profit_after"], currency),
            }
            for scenario in scenario_savings(observed, assumptions)
        ],
        hide_index=True,
        use_container_width=True,
    )
