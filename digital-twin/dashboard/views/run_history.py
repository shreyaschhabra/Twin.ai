"""Run History view.

Shows the runs the dashboard has actually ingested. No history is invented: with an
empty database the view says so and offers a rebuild from completed run artifacts on
disk, which is the supported way to repopulate after the database is deleted.

Storage management lives here too: deleting a run (or all of them) removes both the
history row and the run/prediction artifacts this dashboard created for it -- reclaiming
disk, not just tidying the database. Deletion never touches factory configuration,
trained models, source code, or anything outside the dashboard's own configured roots
(see ``RunManager._owned_run_directories``), and a currently-executing run is never
offered for deletion.

Analytics are out of scope here. Selecting a run stores its id in session state so later
views can scope themselves to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from dashboard.context import DashboardContext
    from dashboard.domain.run import Run
    from dashboard.orchestration.run_manager import RunDeletionResult

SELECTED_RUN_KEY = "selected_run_id"

#: Session-state flag gating the "delete everything" confirmation step.
_CONFIRM_DELETE_ALL_KEY = "run_history_confirm_delete_all"

_STATUS_ICON = {
    "COMPLETED": "✅",
    "RUNNING": "🔄",
    "PENDING": "⏳",
    "PARTIAL": "⚠️",
    "FAILED": "❌",
}


def _active_run_id() -> str | None:
    """The run currently executing in this process, if any -- never offered for deletion."""
    from dashboard.live.session import get_registry

    session = get_registry().active_session()
    return session.run_id if session is not None else None


def render_run_history(context: DashboardContext) -> None:
    st.header("Run History")
    st.caption("One completed run = one simulated production day.")

    if not context.database_ready or context.repository is None:
        st.warning(
            "The dashboard database is unavailable, so no run history can be shown. "
            "The rest of the system is unaffected."
        )
        if context.database_error:
            st.caption(context.database_error)
        return

    runs = context.run_history()
    if not runs:
        _render_empty_state(context)
        return

    st.caption(f"{len(runs)} production run(s) recorded")
    st.dataframe(
        [_row(run) for run in runs],
        use_container_width=True,
        hide_index=True,
    )

    _render_storage_management(context, runs)
    _render_rebuild_control(context)

    st.subheader("Inspect a run")
    labels = {f"Day {run.production_day} — {run.run_id}": run.run_id for run in runs}
    choice = st.selectbox(
        "Select a production run",
        options=list(labels),
        index=None,
        placeholder="Choose a production run…",
    )
    if choice:
        run_id = labels[choice]
        st.session_state[SELECTED_RUN_KEY] = run_id
        selected = context.repository.get_run(run_id)
        if selected is not None:
            _render_detail(context, selected)


def _render_empty_state(context: DashboardContext) -> None:
    st.info("No completed production runs yet.")
    st.caption(
        "Runs appear here once the existing pipeline has produced completed run "
        "artifacts and the dashboard has ingested them. Use the Run Factory page to "
        "start the next production day."
    )
    _render_rebuild_control(context)


def _render_storage_management(context: DashboardContext, runs: list[Run]) -> None:
    """How many runs are stored, and explicit, confirmed controls to reclaim disk."""
    if context.run_manager is None:
        return
    active_run_id = _active_run_id()

    st.subheader("Storage")
    deletable = [run for run in runs if run.run_id != active_run_id]
    cols = st.columns(2)
    cols[0].metric("Stored runs", len(runs))
    cols[1].metric("Deletable now", len(deletable))
    if active_run_id and active_run_id in {r.run_id for r in runs}:
        st.caption(
            f"Run `{active_run_id}` is currently executing and is excluded from "
            "deletion so its artifacts are never removed while still being written."
        )

    if not deletable:
        st.caption("Nothing eligible to delete.")
        return

    if not st.session_state.get(_CONFIRM_DELETE_ALL_KEY):
        if st.button(
            f"🗑️ Delete All Runs ({len(deletable)})",
            type="secondary",
            help="Removes every stored run's history row and the run/prediction "
            "artifacts this dashboard created for it. Factory configuration, trained "
            "models and source code are never touched.",
        ):
            st.session_state[_CONFIRM_DELETE_ALL_KEY] = True
            st.rerun()
    else:
        st.warning(
            f"This permanently deletes {len(deletable)} run(s) — their history rows "
            "and the run/prediction artifacts on disk. This cannot be undone."
        )
        confirm_cols = st.columns(2)
        if confirm_cols[0].button(
            f"Yes, delete {len(deletable)} run(s) and their artifacts",
            type="primary",
            key="confirm_delete_all_runs",
        ):
            exclude = {active_run_id} if active_run_id else set()
            results = context.run_manager.delete_all_runs(exclude_run_ids=exclude)
            st.session_state[_CONFIRM_DELETE_ALL_KEY] = False
            _report_deletion(results)
            st.session_state.pop(SELECTED_RUN_KEY, None)
            st.rerun()
        if confirm_cols[1].button("Cancel", key="cancel_delete_all_runs"):
            st.session_state[_CONFIRM_DELETE_ALL_KEY] = False
            st.rerun()


def _report_deletion(results: list[RunDeletionResult]) -> None:
    errors = [error for result in results for error in result.errors]
    deleted_dirs = sum(len(result.deleted_directories) for result in results)
    if results:
        st.success(
            f"Deleted {len(results)} run(s) and {deleted_dirs} artifact director(ies)."
        )
    if errors:
        st.error(
            "Some artifacts could not be removed (history rows were still deleted):\n"
            + "\n".join(f"- {error}" for error in errors)
        )


def _render_rebuild_control(context: DashboardContext) -> None:
    """Rebuild history from artifacts — the reason the database is safe to delete."""
    if context.ingestor is None:
        return
    with st.expander("Rebuild history from completed run artifacts"):
        st.caption(
            f"Scans `{context.config.runs_root}` for completed run directories and "
            "rebuilds the dashboard database from them. Reads only; the existing "
            "system's artifacts are never modified."
        )
        if st.button("Rebuild from artifacts"):
            try:
                result = context.ingestor.rebuild_from_artifacts()
            except Exception as error:
                st.error(f"Rebuild failed: {error}")
                return
            if result.count:
                st.success(f"Ingested {result.count} completed run(s).")
                st.rerun()
            else:
                st.info("No completed run directories were found to ingest.")
            if result.skipped:
                st.caption(f"Skipped {len(result.skipped)} incomplete director(ies).")


def _row(run: Run) -> dict[str, object]:
    return {
        "Production Day": run.production_day,
        "Run ID": run.run_id,
        "Scenario": run.scenario_name or "—",
        "Playback Speed": f"{run.multiplier:g}×" if run.multiplier else "—",
        "DARK particles": (run.metadata.get("particles") or run.metadata.get("system_run_manifest", {}).get("particles") or "3000"),
        "Model": "BASE",
        "Status": f"{_STATUS_ICON.get(run.status.value, '')} {run.status.value}".strip(),
        "Completed": _timestamp(run.completed_at),
        "Demo": "demo" if run.is_demo else "",
    }


def _timestamp(value: str | None) -> str:
    if not value:
        return "—"
    return value[:19].replace("T", " ")


def _render_detail(context: DashboardContext, run: Run) -> None:
    if run.is_demo:
        st.warning("Prototype/demo run — figures are illustrative, not measured plant data.")

    left, right = st.columns(2)
    with left:
        st.metric("Production Day", run.production_day)
        st.metric("Status", run.status.value)
        st.metric("Seed", run.seed if run.seed is not None else "—")
    with right:
        st.metric("Scenario", run.scenario_name or "—")
        st.metric(
            "Simulated duration",
            f"{run.duration_ms / 3_600_000:.1f} h" if run.duration_ms else "—",
        )
        st.metric("Playback Speed", f"{run.multiplier:g}×" if run.multiplier else "—")

    st.caption(f"Factory: `{run.factory_path}`  ·  fingerprint `{run.factory_fingerprint or '—'}`")
    if run.artifact_path:
        st.caption(f"Run artifacts: `{run.artifact_path}`")
    if run.predictions_path:
        st.caption(f"Prediction outputs: `{run.predictions_path}`")

    if run.metadata:
        with st.expander("Recorded run metadata"):
            st.json(run.metadata)

    _render_per_run_delete(context, run)


def _render_per_run_delete(context: DashboardContext, run: Run) -> None:
    if context.run_manager is None:
        return
    if run.run_id == _active_run_id():
        st.caption("This run is currently executing and cannot be deleted yet.")
        return

    confirm_key = f"confirm_delete_{run.run_id}"
    if not st.session_state.get(confirm_key):
        if st.button(f"🗑️ Delete this run ({run.run_id})", key=f"delete_{run.run_id}"):
            st.session_state[confirm_key] = True
            st.rerun()
        return

    st.warning(
        f"This permanently deletes `{run.run_id}` — its history row and the "
        "run/prediction artifacts on disk. This cannot be undone."
    )
    cols = st.columns(2)
    if cols[0].button("Yes, delete this run", type="primary", key=f"confirm_yes_{run.run_id}"):
        result = context.run_manager.delete_run(run.run_id)
        st.session_state[confirm_key] = False
        _report_deletion([result])
        if st.session_state.get(SELECTED_RUN_KEY) == run.run_id:
            st.session_state.pop(SELECTED_RUN_KEY, None)
        st.rerun()
    if cols[1].button("Cancel", key=f"confirm_no_{run.run_id}"):
        st.session_state[confirm_key] = False
        st.rerun()
