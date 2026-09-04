"""The bottleneck timeline, rendered the same way live and after the fact.

One code path serves both modes. A run in progress and a finished run differ only in
where the feed came from -- a supervising session, or a rebuild from the run's stream
file -- and in whether the panel keeps refreshing itself. The data, the analytics and
the chart are identical, so a completed run needs no second processing step to become a
timeline.

Everything plotted is a record the existing runtime emitted. There is no interpolation
between points, no resampling onto a regular grid, and no recomputation of ``warning``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.live.bottleneck_state import (
    TREND_FALLING,
    TREND_RISING,
    TREND_STABLE,
    StationAnalytics,
)
from dashboard.live.session import (
    LivePredictionFeed,
    LiveRunSession,
    LiveRunStatus,
    bottleneck_stream_path,
    get_registry,
)

#: Where the station picker's choice is remembered, so switching pages or waiting
#: through a refresh does not reset it.
STATION_KEY = "live_bottleneck_station"

#: How often the live panel re-reads the stream while a run is executing.
LIVE_REFRESH = "2s"

_TREND_LABEL = {
    TREND_RISING: "Rising",
    TREND_FALLING: "Falling",
    TREND_STABLE: "Stable",
}


def format_sim_clock(timestamp_ms: int | None) -> str:
    """Simulator time as ``h:mm:ss``. This is never wall-clock time."""
    if timestamp_ms is None:
        return "—"
    total_seconds, milliseconds = divmod(int(timestamp_ms), 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}.{milliseconds // 100}"


def format_duration_ms(duration_ms: int | None) -> str:
    if not duration_ms:
        return "0s"
    seconds = duration_ms / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}m {int(seconds)}s"


def resolve_feed(context: Any, run_id: str | None, predictions_path: str | Path | None):
    """The feed to display, plus the session driving it when one exists.

    Returns ``(feed, session)``. ``session`` is None for a run this process did not
    launch -- a run ingested earlier, or one from a previous dashboard start.
    """
    registry = get_registry()
    session: LiveRunSession | None = registry.active_session()
    if session is not None and (run_id is None or session.run_id == run_id):
        session.refresh()
        return session.feed, session
    if run_id is None or predictions_path is None:
        return None, None
    existing = registry.session(run_id)
    if existing is not None:
        existing.refresh()
        return existing.feed, existing
    return registry.feed(run_id, bottleneck_stream_path(predictions_path)), None


def _series_frame(feed: LivePredictionFeed, station_id: str):
    import pandas as pd

    series = feed.state.series(station_id)
    rows = series.rows() if series else []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["sim_seconds"] = frame["timestamp_ms"] / 1000.0
    frame["Status"] = frame["warning"].map(lambda flag: "Warning" if flag else "Normal")
    return frame


def render_timeline_chart(feed: LivePredictionFeed, station_id: str) -> bool:
    """Bottleneck probability against simulator time. Returns False when empty.

    The x axis is the record's own ``timestamp_ms``, so the chart advances with the
    simulation, not with how long the page has been open.
    """
    frame = _series_frame(feed, station_id)
    if frame.empty:
        return False

    import altair as alt

    from dashboard.views.chart_utils import percent_scale

    base = alt.Chart(frame)
    line = base.mark_line(color="#4c78a8", interpolate="step-after").encode(
        x=alt.X("sim_seconds:Q", title="Simulator time (s)"),
        y=alt.Y(
            "risk_percent:Q",
            title="Bottleneck probability (%)",
            scale=percent_scale(),
        ),
    )
    points = base.mark_circle(size=45).encode(
        x="sim_seconds:Q",
        y="risk_percent:Q",
        color=alt.Color(
            "Status:N",
            scale=alt.Scale(domain=["Normal", "Warning"], range=["#4c78a8", "#d62728"]),
            legend=alt.Legend(title="Runtime alert"),
        ),
        tooltip=[
            alt.Tooltip("timestamp_ms:Q", title="Simulator time (ms)"),
            alt.Tooltip("risk_percent:Q", title="Risk %", format=".1f"),
            alt.Tooltip("threshold_percent:Q", title="Threshold %", format=".1f"),
            alt.Tooltip("Status:N", title="Alert"),
            alt.Tooltip("zone:N", title="Zone"),
            alt.Tooltip("route:N", title="Route"),
            alt.Tooltip("vehicle_id:N", title="Vehicle"),
        ],
    )
    layers = [line, points]

    analytics = feed.state.analytics(station_id)
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
            "flagged with `warning`; the flag is read from the stream, never recomputed."
        )
    return True


def render_station_metrics(analytics: StationAnalytics) -> None:
    """Temporal analytics for the selected station, over records emitted so far."""
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
        f"{analytics.point_count} prediction(s) for this station, spanning simulator time "
        f"{format_sim_clock(analytics.first_timestamp_ms)} → "
        f"{format_sim_clock(analytics.last_timestamp_ms)}. Time above threshold is "
        "measured between consecutive flagged records; a single isolated flagged record "
        "contributes no duration."
    )


def render_warning_periods(analytics: StationAnalytics) -> None:
    if not analytics.warning_periods:
        st.success("No warning period recorded for this station yet.")
        return
    st.dataframe(
        [
            {
                "From (sim)": format_sim_clock(period.start_ms),
                "To (sim)": format_sim_clock(period.end_ms),
                "Duration": format_duration_ms(period.duration_ms),
                "Predictions": period.point_count,
                "Still open": "yes" if period.open_ended else "",
            }
            for period in analytics.warning_periods
        ],
        hide_index=True,
        use_container_width=True,
    )


def select_station(feed: LivePredictionFeed, key: str = STATION_KEY) -> str | None:
    """Station picker whose choice survives a refresh and mid-run station changes."""
    stations = feed.state.station_ids()
    if not stations:
        return None
    previous = st.session_state.get(key)
    if previous is not None and previous not in stations:
        # A station remembered from another run is not an option here; Streamlit
        # rejects a keyed selectbox whose stored value is absent from its options.
        del st.session_state[key]
        previous = None
    index = stations.index(previous) if previous in stations else 0
    return st.selectbox("Station", stations, index=index, key=key)


def render_live_panel(feed: LivePredictionFeed, session: LiveRunSession | None) -> None:
    """The timeline panel body. Called directly, or from an auto-refreshing fragment."""
    if session is not None:
        session.refresh()
    else:
        feed.poll()

    state = feed.state
    header = st.columns(4)
    header[0].metric("Predictions so far", state.record_count)
    header[1].metric("Stations seen", len(state.stations))
    header[2].metric("Warning records", state.warning_count)
    header[3].metric("Simulator clock", format_sim_clock(state.last_timestamp_ms))

    if not state.stations:
        if session is not None and session.is_running:
            st.info(
                "The run is executing. Station timelines appear here as the bottleneck "
                "consumer emits its first predictions — no need to wait for the run to "
                "finish."
            )
        elif not feed.stream_exists:
            st.info(f"No bottleneck stream at `{feed.stream_path}` yet.")
        else:
            st.info("The bottleneck stream has not produced any usable predictions yet.")
        return

    station = select_station(feed)
    if station is None:
        return

    render_station_metrics(state.analytics(station))
    if not render_timeline_chart(feed, station):
        st.info(f"No predictions for {station} yet.")
    with st.expander(f"Warning periods · {station}"):
        render_warning_periods(state.analytics(station))

    alerting = state.active_warning_stations()
    if alerting:
        st.warning("Stations whose latest prediction is flagged: " + ", ".join(alerting))


def render_bottleneck_timeline(feed: LivePredictionFeed, session: LiveRunSession | None) -> None:
    """Render the panel, refreshing itself only while a run is actually executing.

    The refresh is scoped to a fragment so the rest of the page -- and the rest of the
    Streamlit session -- stays interactive while the pipeline runs.
    """
    running = session is not None and session.is_running
    if not running:
        render_live_panel(feed, session)
        return

    @st.fragment(run_every=LIVE_REFRESH)
    def _live_fragment() -> None:
        st.caption(
            f"LIVE · refreshing every {LIVE_REFRESH} while the run executes. "
            "The chart advances on the simulator clock, not on wall-clock time."
        )
        render_live_panel(feed, session)

    _live_fragment()


def status_banner(session: LiveRunSession | None) -> None:
    """One line describing the run behind the panel, if this process launched it."""
    if session is None:
        return
    progress = session.progress()
    if progress.status == LiveRunStatus.RUNNING:
        st.info(
            f"Run `{progress.run_id}` is executing · {progress.record_count} bottleneck "
            f"predictions consumed so far · {progress.elapsed_s / 60:.1f} min elapsed."
        )
    elif progress.status == LiveRunStatus.COMPLETED:
        st.success(
            f"Run `{progress.run_id}` finished · {progress.record_count} bottleneck "
            "predictions retained for historical analysis."
        )
    elif progress.status == LiveRunStatus.CANCELLED:
        st.warning(
            f"Run `{progress.run_id}` was stopped · the "
            f"{progress.record_count} prediction(s) it had already produced are kept."
        )
    elif progress.status == LiveRunStatus.FAILED:
        st.error(f"Run `{progress.run_id}` failed: {progress.error or 'unknown error'}")
