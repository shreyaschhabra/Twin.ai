"""The Run Factory page: configure and launch one production-day run.

Everything about starting, watching and stopping a run lives here and only here, so
other analysis pages never duplicate these controls. The RUN FACTORY action never fires
on page load, and never blocks the UI: the existing CLI pipeline runs as a background
process, a supervising thread drains its output and tails both prediction streams, and
the Streamlit script returns immediately after launching it. Other pages (Bottlenecks,
Defects) read the same live session to show predictions while this run is still
executing -- they do not need this page open to do so.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from dashboard.context import DashboardContext

#: Selectable simulated-day lengths, mapped to (duration_ms, rough wall-clock estimate
#: at 1x playback speed -- a higher speed finishes proportionally sooner).
RUN_DURATIONS: dict[str, tuple[int, str]] = {
    "Full shift — 8 simulated hours": (28_800_000, "8 hours at 1x, ~24 min at 20x"),
    "Half shift — 4 simulated hours": (14_400_000, "4 hours at 1x, ~12 min at 20x"),
    "Short — 1 simulated hour": (3_600_000, "1 hour at 1x, ~3 min at 20x"),
    "Smoke test — 10 simulated minutes": (600_000, "10 min at 1x, ~30s at 20x"),
}

#: How often the run-status panel re-reads the live prediction stream while a run is
#: executing. Scoped to a Streamlit fragment, so the rest of the page stays usable.
LIVE_STATUS_REFRESH = "2s"


def _live_registry():
    """The process-wide live-run registry.

    Imported lazily so the module-level import graph of the shell stays small and the
    registry is only touched by code paths that actually care about a run.
    """
    from dashboard.live.session import get_registry

    return get_registry()


def _current_session():
    """The run this process is executing, or the last one it executed."""
    registry = _live_registry()
    return registry.active_session() or registry.latest_session()


def _start_run(context: DashboardContext, plan) -> None:
    """Launch the planned run in the background and return immediately.

    The Streamlit script must never sit inside the pipeline: a run is a coffee break
    long, and blocking here would freeze every control on the page. The adapter starts
    the canonical ``cli.py`` command and a supervising thread drains its output and
    tails both prediction streams, so the timelines on the Bottlenecks and Defects pages
    fill in while the run is still executing.
    """
    from dashboard.live.session import bottleneck_stream_path

    session = _live_registry().create_session(
        plan.run_id, bottleneck_stream_path(plan.output_dir)
    )
    if context.run_manager is not None and context.repository is not None:
        # A PENDING row makes the run visible in history the moment it starts, and
        # carries the predictions path the timelines are read from.
        try:
            context.run_manager.record_planned_run(plan, is_demo=context.factory.is_demo)
        except Exception as error:  # a history hiccup must not block the run
            st.warning(f"The run started but could not be recorded yet: {error}")
    session.start(lambda: context.adapter.launch_planned_run(plan), plan=plan)
    st.session_state["selected_run_id"] = plan.run_id


def _ingest_finished_run(context: DashboardContext, session) -> None:
    """Record a finished run in history exactly once.

    This is bookkeeping, not a processing step the timeline waits on: the accumulated
    prediction history is already complete and displayable before this runs.
    """
    from dashboard.live.session import LiveRunStatus

    if session.ingested or context.ingestor is None or session.plan is None:
        return
    if session.status not in (LiveRunStatus.COMPLETED, LiveRunStatus.CANCELLED):
        return
    plan = session.plan
    try:
        run = context.ingestor.ingest_completed_run(
            plan.expected_run_dir,
            predictions_dir=plan.output_dir,
            run_id=plan.run_id,
            multiplier=plan.multiplier,
            particles=plan.particles,
            is_demo=context.factory.is_demo,
        )
    except Exception as error:
        # A run whose artifacts are incomplete (a cancelled one, typically) still keeps
        # every prediction it produced; only the history row is missing.
        st.caption(f"Run history was not updated: {error}")
        session.mark_ingested()
        return
    session.mark_ingested()
    st.session_state["selected_run_id"] = run.run_id


def _render_run_progress(context: DashboardContext, session) -> None:
    """Live status for the run this process launched."""
    from dashboard.live.session import LiveRunStatus

    progress = session.progress()
    defect_count = session.defect_feed.state.record_count
    columns = st.columns(6)
    columns[0].metric("Run", progress.run_id)
    columns[1].metric("Status", progress.status.value)
    columns[2].metric("Bottleneck predictions", progress.record_count)
    columns[3].metric("Defect predictions", defect_count)
    columns[4].metric("Stations seen", progress.station_count)
    columns[5].metric("Elapsed", f"{progress.elapsed_s / 60:.1f} min")

    if progress.status == LiveRunStatus.RUNNING:
        st.caption(
            "The pipeline is running as a background process. Predictions appear on "
            "the Bottlenecks and Defects pages as the runtime emits them — there is no "
            "need to wait for the run to finish."
        )
        if st.button("Stop run", key="stop_live_run"):
            session.cancel()
            st.rerun()
    elif progress.status == LiveRunStatus.FAILED:
        st.error(progress.error or "The factory runtime failed.")
    elif progress.status == LiveRunStatus.CANCELLED:
        st.warning("The run was stopped. Predictions produced before it stopped are kept.")
    else:
        st.success("Run complete. Its prediction history stays available for analysis.")

    output = session.recent_output(limit=12)
    if output:
        with st.expander("Runtime output"):
            st.code("\n".join(output))


def _render_run_status_panel(context: DashboardContext, session) -> None:
    """Run status, refreshing itself only while the pipeline is actually executing."""
    if not session.is_running:
        session.refresh()
        _ingest_finished_run(context, session)
        _render_run_progress(context, session)
        return

    @st.fragment(run_every=LIVE_STATUS_REFRESH)
    def _status_fragment() -> None:
        session.refresh()
        finished_now = not session.is_running
        _render_run_progress(context, session)
        if finished_now:
            _ingest_finished_run(context, session)
            # The whole page, not just this fragment, is stale once the run ends:
            # history, the sidebar's current run and every view need the new row.
            st.rerun(scope="app")

    _status_fragment()


def render_run_factory(context: DashboardContext) -> None:
    """The RUN FACTORY page: configuration, the action itself, and live status.

    Never fires on page load, and never blocks the UI.
    """
    from dashboard.live.session import LiveRunStatus
    from dashboard.orchestration.existing_runtime_adapter import (
        PLAYBACK_SPEED_MAX,
        PLAYBACK_SPEED_MIN,
    )

    st.header("Run Factory")
    st.caption(
        "One run = one simulated production day. Runs execute in the background; "
        "predictions appear on the Bottlenecks and Defects pages while the run is "
        "still in progress."
    )

    readiness = context.readiness()
    session = _current_session()
    running = session is not None and session.is_running

    with st.expander("Run configuration", expanded=True):
        cols = st.columns(4)
        cols[0].text_input("Factory", value=context.config.factory_path.name, disabled=True)
        cols[1].text_input("Scenario", value="Random", disabled=True)
        duration_label = cols[2].selectbox(
            "Duration", list(RUN_DURATIONS), index=3, disabled=running
        )
        multiplier = cols[3].slider(
            "Playback Speed",
            min_value=PLAYBACK_SPEED_MIN,
            max_value=PLAYBACK_SPEED_MAX,
            value=1.0,
            step=0.25,
            format="%.2fx",
            disabled=running,
            help=(
                "How fast simulated time advances relative to wall-clock time. 1x is "
                "approximately real-time; this paces the coordinated runtime's actual "
                "execution, not just what is displayed."
            ),
        )
        particles = st.slider("DARK particle count", 300, 3000, 3000, 100, disabled=running)
        st.caption("Model: BASE (fixed prototype model)")
        for blocker in readiness.blockers:
            st.warning(blocker)
        for warning in readiness.warnings:
            st.caption(f"Warning: {warning}")
        clicked = st.button(
            "RUN FACTORY", type="primary", disabled=running or not readiness.ready
        )

    if session is not None and session.status != LiveRunStatus.IDLE:
        st.subheader("Run status")
        _render_run_status_panel(context, session)

    if not clicked or context.run_manager is None:
        return

    duration_ms, _ = RUN_DURATIONS[duration_label]
    plan = context.run_manager.plan_next_run(
        duration_ms=duration_ms, multiplier=multiplier, particles=particles
    )
    if not plan.runnable:
        st.error("Run preflight failed:")
        for blocker in plan.blockers:
            st.markdown(f"- {blocker}")
        return
    # Shown only once preflight has verified it: the destination directories are free,
    # the pinned model can score every station, and the defect consumer's dependencies
    # are installed. This is the command the dashboard is about to run.
    st.code(
        plan.command_line("powershell" if sys.platform.startswith("win") else "bash"),
        language="bash",
    )
    try:
        _start_run(context, plan)
    except Exception as error:
        st.error(f"The factory run could not be started: {error}")
        return
    st.rerun()
