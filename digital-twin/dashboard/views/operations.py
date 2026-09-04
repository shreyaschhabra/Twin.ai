"""Artifact-backed analysis views for the prototype dashboard.

The Bottlenecks, Defects, Live Twin and Sensor Coverage views live here. The three
stakeholder views (Supervisor, Plant Manager, Leadership) are their own modules --
:mod:`dashboard.views.supervisor`, :mod:`dashboard.views.plant_manager`,
:mod:`dashboard.views.leadership` -- backed by :mod:`dashboard.stakeholder`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.domain.station import Station


def _records(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict): rows.append(item)
            except json.JSONDecodeError: pass
    except OSError: pass
    return rows


def _run(context):
    runs = context.run_history()
    chosen = st.session_state.get("selected_run_id")
    return next((r for r in runs if r.run_id == chosen), None) or (runs[0] if runs else None)


def _data(context):
    run = _run(context)
    if not run or not run.predictions_path: return run, [], []
    root = Path(run.predictions_path)
    return run, _records(root / "bottleneck_predictions.jsonl"), _records(root / "defect_predictions.jsonl")


def _risk(row, kind): return float(row.get(f"{kind}_risk_percent", row.get(f"{kind}_probability", 0) * 100) or 0)
def _confidence(row): return round(float(row.get("state_confidence", 0) or 0) * 100)
def _latest(rows, key):
    result = {}
    for row in rows: result[str(row.get(key, "—"))] = row
    return result


def render_live_twin(context) -> None:
    st.header("Live Digital Twin")
    _, b, _ = _data(context); latest=_latest(b,"station_id"); stations=Station.all_from_factory(context.factory.data or {})
    if not stations: st.info("No valid factory topology available."); return
    cards=[]
    for s in stations:
        key=f"S{s.id+1:02d}"; row=latest.get(key, {}); risk=_risk(row,"bottleneck")
        cards.append({"Station":key,"Type":s.archetype,"Context":s.zone,"Coverage":s.sensor_coverage,"Risk %":round(risk,1),"Status":"ALERT" if row.get("warning") else "Flowing"})
    st.caption("Actual factory topology; latest current-run station prediction is shown for each node.")
    st.dataframe(cards, hide_index=True, use_container_width=True)


def render_bottlenecks(context) -> None:
    """Station bottleneck risk, live during a run and afterwards from the same history.

    The timeline is read incrementally from the bottleneck stream the existing runtime
    is writing, so it fills in while the run executes; when the run ends the same
    accumulated history stays on screen for historical analysis.
    """
    from dashboard.views.live_bottlenecks import (
        render_bottleneck_timeline,
        resolve_feed,
        status_banner,
    )

    st.header("Bottleneck Intelligence")
    run = _run(context)
    predictions_path = run.predictions_path if run else None
    feed, session = resolve_feed(context, run.run_id if run else None, predictions_path)
    if feed is None:
        st.info("No run selected yet. Start one from the Run Factory page, or pick one from Run History.")
        return

    status_banner(session)
    st.subheader("Bottleneck probability over simulator time")
    render_bottleneck_timeline(feed, session)

    latest = feed.state.latest_by_station()
    if not latest:
        return
    st.subheader("Latest prediction per station")
    table = sorted(
        (
            {
                "Station": station,
                "Risk %": round(point.risk_percent, 1),
                "Alert": point.warning,
                "Confidence %": round((point.state_confidence or 0.0) * 100),
                "Zone": point.zone,
                "Predictions": len(feed.state.series(station) or ()),
            }
            for station, point in latest.items()
        ),
        key=lambda row: row["Risk %"],
        reverse=True,
    )
    from dashboard.views.chart_utils import percent_bar_chart

    percent_bar_chart({row["Station"]: row["Risk %"] for row in table}, x_title="Station")
    st.dataframe(table, hide_index=True, use_container_width=True)


def render_defects(context) -> None:
    """Per-vehicle defect risk, live during a run and afterwards from the same history.

    Mirrors :func:`render_bottlenecks`: the timeline is read incrementally from the
    defect stream the existing runtime is writing, so it fills in while the run
    executes, and the same accumulated history stays on screen once the run ends.
    """
    from dashboard.views.chart_utils import percent_bar_chart
    from dashboard.views.live_defects import (
        defect_status_banner,
        render_defect_timeline,
        resolve_defect_feed,
    )

    st.header("Defect Intelligence")
    run = _run(context)
    predictions_path = run.predictions_path if run else None
    feed, session = resolve_defect_feed(context, run.run_id if run else None, predictions_path)
    if feed is None:
        st.info("No run selected yet. Start a run from Run Factory, or pick one from Run History.")
        return

    defect_status_banner(session)
    st.subheader("Defect probability over simulator time")
    render_defect_timeline(feed, session)

    latest = feed.state.latest_by_unit()
    if not latest:
        return
    st.subheader("Latest prediction per unit")
    table = sorted(
        (
            {
                "Unit": unit,
                "Risk %": round(point.risk_percent, 1),
                "Station": point.station_id,
                "Inspection priority": "High" if point.warning else "Monitor",
                "Confidence %": round((point.state_confidence or 0.0) * 100),
                "Predictions": len(feed.state.series(unit) or ()),
            }
            for unit, point in latest.items()
        ),
        key=lambda row: row["Risk %"],
        reverse=True,
    )
    percent_bar_chart(
        {row["Unit"]: row["Risk %"] for row in table[:20]}, x_title="Unit", height=280
    )
    st.dataframe(table[:50], hide_index=True, use_container_width=True)


def render_sensor_coverage(context) -> None:
    st.header("Sensor Coverage & Trust")
    _,b,_=_data(context); latest=_latest(b,"station_id"); stations=Station.all_from_factory(context.factory.data or {})
    if not stations: st.info("No valid factory configuration."); return
    table=[]
    for s in stations:
        row=latest.get(f"S{s.id+1:02d}",{}); table.append({"Station":f"S{s.id+1:02d}","Coverage":s.sensor_coverage,"Prediction confidence":f"{_confidence(row)}%" if row else "No prediction","Zone":s.zone})
    st.dataframe(table,hide_index=True,use_container_width=True)
    station=st.selectbox("Station", [x["Station"] for x in table]); item=next(x for x in table if x["Station"]==station)
    st.info(f"{station}\n\nCoverage: {item['Coverage']} · Confidence: {item['Prediction confidence']}\n\nSuggested improvement: candidate for low-cost sensing during the next maintenance window when coverage is limited.")
