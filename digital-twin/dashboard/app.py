"""DigitalTwin.ai dashboard shell.

Launch with::

    py -m streamlit run dashboard/app.py

The dashboard sits downstream of the existing Digital Twin system. Rendering a page
reads artifacts and the dashboard's own SQLite file -- it never starts a simulation,
never runs a model, and never launches a factory run on load. The RUN FACTORY control
lives on its own page (see :mod:`dashboard.views.run_factory`) and hands execution to
the existing CLI pipeline, which runs as a background process: the script never blocks
on it, so the prediction streams that run is writing can be read and charted from any
page while it is still executing.

Every prerequisite is optional at startup: a missing factory.json, a missing database,
an empty run history, absent prediction files and an idle runtime all render as empty
states.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st  # noqa: E402

from dashboard.context import DashboardContext, build_context  # noqa: E402
from dashboard.factory.manager import FactoryStatus  # noqa: E402
from dashboard.views import (  # noqa: E402
    render_bottlenecks,
    render_defects,
    render_leadership,
    render_live_twin,
    render_plant_manager,
    render_run_factory,
    render_run_history,
    render_sensor_coverage,
    render_supervisor,
)

#: Navigation order. Run Factory first (so it is also the landing page); the three
#: stakeholder views are peers, not nested inside one another.
PAGES = {
    "Run Factory": render_run_factory,
    "Supervisor": render_supervisor,
    "Plant Manager": render_plant_manager,
    "Leadership": render_leadership,
    "Live Twin": render_live_twin,
    "Bottlenecks": render_bottlenecks,
    "Defects": render_defects,
    "Sensor Coverage": render_sensor_coverage,
    "Run History": render_run_history,
}

_STATUS_ICON = {
    FactoryStatus.VALID: "🟢",
    FactoryStatus.INVALID: "🟠",
    FactoryStatus.MISSING: "🔴",
}


def get_context() -> DashboardContext:
    """Build the context once per session and reuse it across reruns."""
    if "context" not in st.session_state:
        st.session_state["context"] = build_context()
    return st.session_state["context"]


def _render_factory_block(context: DashboardContext) -> None:
    st.caption("Factory")
    st.code(str(context.config.factory_path), language=None)
    status = context.factory.status
    st.markdown(f"{_STATUS_ICON.get(status, '⚪')} **{status}**")

    if status == FactoryStatus.VALID:
        st.caption(
            f"{context.factory.station_count} stations · "
            f"{context.factory.dark_zone_count} DARK zone(s)"
        )
        if context.factory.is_demo:
            st.caption("⚠️ Generated demo configuration — illustrative, not plant data.")
        for warning in context.factory.validation.warnings:
            st.caption(f"⚠️ {warning}")
    elif status == FactoryStatus.INVALID:
        with st.expander("Why is this invalid?"):
            for error in context.factory.validation.errors:
                st.markdown(f"- {error}")
        st.caption("The file was left untouched. Fix it, or point the dashboard elsewhere.")
    else:
        st.caption("No configuration at this path.")
        if st.button("Generate demo factory", use_container_width=True):
            _generate_demo_factory(context)


def _generate_demo_factory(context: DashboardContext) -> None:
    from dashboard.factory.manager import generate_demo_factory

    try:
        generate_demo_factory(context.config.factory_path, seed=context.config.demo_seed)
    except FileExistsError:
        st.warning("A factory configuration already exists at that path; nothing was changed.")
    except Exception as error:
        st.error(f"Could not generate a demo factory: {error}")
    else:
        context.refresh_factory()
        st.rerun()


def _render_current_run_block(context: DashboardContext) -> None:
    st.caption("Current Run")
    latest = context.latest_run()
    if latest is None:
        st.markdown("**Run:** —")
        st.markdown("**Production Day:** —")
        st.caption("No completed production runs yet.")
        return
    st.markdown(f"**Run:** `{latest.run_id}`")
    st.markdown(f"**Production Day:** {latest.production_day}")
    st.caption(f"Status: {latest.status.value}" + ("  ·  demo" if latest.is_demo else ""))


def _render_sidebar(context: DashboardContext) -> str:
    with st.sidebar:
        st.title("DIGITALTWIN.AI")
        st.divider()
        _render_factory_block(context)
        st.divider()
        _render_current_run_block(context)
        st.divider()

        st.caption("Navigation")
        page = st.radio("Navigation", list(PAGES), index=0, label_visibility="collapsed")

        st.divider()
        if context.database_ready:
            st.caption(f"Database: ready (schema v{context.database.schema_version()})")
        else:
            st.caption("Database: unavailable")
            if context.database_error:
                st.caption(context.database_error)
    return page


def main() -> None:
    st.set_page_config(
        page_title="DigitalTwin.ai",
        page_icon="🏭",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    context = get_context()
    page = _render_sidebar(context)

    st.title("DIGITALTWIN.AI")
    st.caption("Prototype dashboard")

    for notice in context.notices:
        st.info(notice)

    PAGES[page](context)


if __name__ == "__main__":
    main()
