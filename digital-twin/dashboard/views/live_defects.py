"""The defect-probability timeline for a selected unit, live and after the fact.

The per-unit sibling of :mod:`dashboard.views.live_bottlenecks` -- same design, same
guarantees, applied to the defect stream instead of the bottleneck stream. A run in
progress and a finished run differ only in where the feed came from and whether the
panel keeps refreshing itself; the data, the analytics and the chart are identical, so a
completed run needs no second processing step to become a timeline.

Everything plotted is a record the existing defect consumer emitted. There is no
interpolation between points, no resampling onto a regular grid, and no recomputation of
``warning`` -- including the runtime's own suppression of ``warning`` once a unit
reaches final inspection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.live.defect_state import TREND_FALLING, TREND_RISING, TREND_STABLE, UnitAnalytics
from dashboard.live.session import (
    LivePredictionFeed,
    LiveRunSession,
    LiveRunStatus,
    defect_stream_path,
    get_registry,
)
from dashboard.views.chart_utils import percent_scale
from dashboard.views.live_bottlenecks import format_duration_ms, format_sim_clock
from dashboard.views.live_bottlenecks import render_warning_periods as _render_warning_periods

#: Where the unit picker's choice is remembered, so switching pages or waiting through a
#: refresh does not reset it.
UNIT_KEY = "live_defect_unit"

#: How often the live panel re-reads the stream while a run is executing.
LIVE_REFRESH = "2s"

_TREND_LABEL = {
    TREND_RISING: "Rising",
    TREND_FALLING: "Falling",
    TREND_STABLE: "Stable",
}


def resolve_defect_feed(context: Any, run_id: str | None, predictions_path: str | Path | None):
    """The defect feed to display, plus the session driving it when one exists.

    Returns ``(feed, session)``. ``session`` is None for a run this process did not
    launch -- a run ingested earlier, or one from a previous dashboard start.
    """
    registry = get_registry()
    session: LiveRunSession | None = registry.active_session()
    if session is not None and (run_id is None or session.run_id == run_id):
        session.refresh()
        return session.defect_feed, session
    if run_id is None or predictions_path is None:
        return None, None
    existing = registry.session(run_id)
    if existing is not None:
        existing.refresh()
        return existing.defect_feed, existing
    return registry.defect_feed(run_id, defect_stream_path(predictions_path)), None


def _series_frame(feed: LivePredictionFeed, unit_id: str):
    import pandas as pd

    series = feed.state.series(unit_id)
    rows = series.rows() if series else []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["sim_seconds"] = frame["timestamp_ms"] / 1000.0
    frame["Status"] = frame["warning"].map(lambda flag: "Warning" if flag else "Normal")
    return frame


def render_defect_timeline_chart(feed: LivePredictionFeed, unit_id: str) -> bool:
    """Defect probability against simulator time. Returns False when empty.

    The x axis is the record's own ``timestamp_ms``, so the chart advances with the
    simulation, not with how long the page has been open. The y axis is capped to the
    valid 0-100% probability range.
    """
    frame = _series_frame(feed, unit_id)
    if frame.empty:
        return False

    import altair as alt

    base = alt.Chart(frame)
    line = base.mark_line(color="#54a24b", interpolate="step-after").encode(
        x=alt.X("sim_seconds:Q", title="Simulator time (s)"),
        y=alt.Y(
            "risk_percent:Q",
            title="Defect probability (%)",
            scale=percent_scale(),
        ),
    )
    points = base.mark_circle(size=45).encode(
        x="sim_seconds:Q",
        y="risk_percent:Q",
        color=alt.Color(
            "Status:N",
            scale=alt.Scale(domain=["Normal", "Warning"], range=["#54a24b", "#d62728"]),
            legend=alt.Legend(title="Runtime alert"),
        ),
        tooltip=[
            alt.Tooltip("timestamp_ms:Q", title="Simulator time (ms)"),
            alt.Tooltip("risk_percent:Q", title="Risk %", format=".1f"),
            alt.Tooltip("threshold_percent:Q", title="Threshold %", format=".1f"),
            alt.Tooltip("Status:N", title="Alert"),
            alt.Tooltip("station_id:N", title="Station"),
            alt.Tooltip("route:N", title="Route"),
        ],
    )
    layers = [line, points]

    analytics = feed.state.analytics(unit_id)
    if analytics.threshold is not None:
        threshold_frame = frame.head(1).assign(threshold_pct=analytics.threshold * 100.0)
        layers.append(
            alt.Chart(threshold_frame)
            .mark_rule(color="#d62728", strokeDash=[6, 4])
            .encode(y=alt.Y("threshold_pct:Q", scale=percent_scale()))
        )

    st.altair_chart(alt.layer(*layers).properties(height=320), use_container_width=True)
    if analytics.threshold is not None:
        st.caption(
            f"Dashed line: the runtime's decision threshold, "
            f"{analytics.threshold * 100:.1f}%. Red points are records the runtime "
            "flagged with `warning`; the flag is read from the stream, never recomputed "
            "-- including its suppression once a unit reaches final inspection."
        )
    return True


def render_unit_metrics(analytics: UnitAnalytics) -> None:
    """Temporal analytics for the selected unit, over records emitted so far."""
    top = st.columns(4)
    top[0].metric(
        "Current risk",
        "—" if analytics.current_risk is None else f"{analytics.current_risk * 100:.1f}%",
        delta="ALERT" if analytics.warning_now else None,
        delta_color="inverse" if analytics.warning_now else "normal",
    )
    top[1].metric(
        "Peak risk",
        "—" if analytics.peak_risk is None else f"{analytics.peak_risk * 100:.1f}%",
    )
    top[2].metric(
        "Average risk",
        "—" if analytics.average_risk is None else f"{analytics.average_risk * 100:.1f}%",
    )
    top[3].metric(
        "Threshold",
        "—" if analytics.threshold is None else f"{analytics.threshold * 100:.1f}%",
    )

    bottom = st.columns(4)
    bottom[0].metric("Threshold crossings", analytics.threshold_crossings)
    bottom[1].metric("Time above threshold", format_duration_ms(analytics.time_above_threshold_ms))
    bottom[2].metric("Warning periods", len(analytics.warning_periods))
    bottom[3].metric("Trend", _TREND_LABEL.get(analytics.trend, "Not enough data"))

    st.caption(
        f"{analytics.point_count} prediction(s) for this unit, spanning simulator time "
        f"{format_sim_clock(analytics.first_timestamp_ms)} → "
        f"{format_sim_clock(analytics.last_timestamp_ms)}. Time above threshold is "
        "measured between consecutive flagged records; a single isolated flagged record "
        "contributes no duration."
    )


def select_unit(feed: LivePredictionFeed, key: str = UNIT_KEY) -> str | None:
    """Unit picker whose choice survives a refresh and mid-run unit changes."""
    units = feed.state.unit_ids()
    if not units:
        return None
    previous = st.session_state.get(key)
    if previous is not None and previous not in units:
        # A unit remembered from another run is not an option here; Streamlit rejects a
        # keyed selectbox whose stored value is absent from its options.
        del st.session_state[key]
        previous = None
    index = units.index(previous) if previous in units else 0
    return st.selectbox("Unit", units, index=index, key=key)


def render_live_defect_panel(feed: LivePredictionFeed, session: LiveRunSession | None) -> None:
    """The timeline panel body. Called directly, or from an auto-refreshing fragment."""
    if session is not None:
        session.refresh()
    else:
        feed.poll()

    state = feed.state
    header = st.columns(4)
    header[0].metric("Predictions so far", state.record_count)
    header[1].metric("Units seen", len(state.units))
    header[2].metric("Warning records", state.warning_count)
    header[3].metric("Simulator clock", format_sim_clock(state.last_timestamp_ms))

    if not state.units:
        if session is not None and session.is_running:
            st.info(
                "The run is executing. Unit timelines appear here as the defect "
                "consumer emits its first predictions — no need to wait for the run to "
                "finish."
            )
        elif not feed.stream_exists:
            st.info(f"No defect stream at `{feed.stream_path}` yet.")
        else:
            st.info("The defect stream has not produced any usable predictions yet.")
        return

    unit = select_unit(feed)
    if unit is None:
        return

    render_unit_metrics(state.analytics(unit))
    if not render_defect_timeline_chart(feed, unit):
        st.info(f"No predictions for {unit} yet.")
    with st.expander(f"Warning periods · {unit}"):
        _render_warning_periods(state.analytics(unit))

    alerting = state.active_warning_units()
    if alerting:
        shown = ", ".join(alerting[:20])
        more = f" and {len(alerting) - 20} more" if len(alerting) > 20 else ""
        st.warning(f"Units whose latest prediction is flagged: {shown}{more}")


def render_defect_timeline(feed: LivePredictionFeed, session: LiveRunSession | None) -> None:
    """Render the panel, refreshing itself only while a run is actually executing.

    The refresh is scoped to a fragment so the rest of the page -- and the rest of the
    Streamlit session -- stays interactive while the pipeline runs.
    """
    running = session is not None and session.is_running
    if not running:
        render_live_defect_panel(feed, session)
        return

    @st.fragment(run_every=LIVE_REFRESH)
    def _live_fragment() -> None:
        st.caption(
            f"LIVE · refreshing every {LIVE_REFRESH} while the run executes. "
            "The chart advances on the simulator clock, not on wall-clock time."
        )
        render_live_defect_panel(feed, session)

    _live_fragment()


def defect_status_banner(session: LiveRunSession | None) -> None:
    """One line describing the run behind the panel, if this process launched it."""
    if session is None:
        return
    status = session.status
    defect_state = session.defect_feed.state
    if status == LiveRunStatus.RUNNING:
        st.info(
            f"Run `{session.run_id}` is executing · {defect_state.record_count} defect "
            "predictions consumed so far."
        )
    elif status == LiveRunStatus.COMPLETED:
        st.success(
            f"Run `{session.run_id}` finished · {defect_state.record_count} defect "
            "predictions retained for historical analysis."
        )
    elif status == LiveRunStatus.CANCELLED:
        st.warning(
            f"Run `{session.run_id}` was stopped · the {defect_state.record_count} "
            "defect prediction(s) it had already produced are kept."
        )
    elif status == LiveRunStatus.FAILED:
        st.error(f"Run `{session.run_id}` failed: {session.error or 'unknown error'}")
