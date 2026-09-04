"""Shared chart helpers for probability/risk visualizations.

Bottleneck and defect risk are both reported as a probability (0..1) expressed as a
percentage for display. A percentage cannot legitimately fall outside 0-100; this module
exists so every chart that plots one enforces that bound at the axis level instead of
each view re-deriving its own `alt.Scale`. This is a visualization concern only -- it
never touches the underlying prediction records.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

#: Every probability/risk percentage chart in the dashboard shares this scale: fixed to
#: the valid probability range, clamped so an out-of-range value cannot stretch the
#: axis, and not "niced" outward past 100.
PERCENT_DOMAIN = (0, 100)


def percent_scale():
    """An Altair scale clamped to the valid 0-100% probability range."""
    import altair as alt

    return alt.Scale(domain=list(PERCENT_DOMAIN), clamp=True, nice=False)


def percent_bar_chart(
    values: dict[str, float], *, x_title: str, y_title: str = "Risk %", height: int = 300
) -> None:
    """A bar chart of percentages, axis-capped to 0-100% regardless of the data.

    Replaces bare ``st.bar_chart`` calls for risk/probability summaries, whose
    auto-scaled y-axis would otherwise expand past 100 (or below 0) if an odd value
    ever showed up. Values are clamped for *display* only.
    """
    import altair as alt
    import pandas as pd

    frame = pd.DataFrame(
        {"label": list(values.keys()), "value": [float(v) for v in values.values()]}
    )
    chart = (
        alt.Chart(frame)
        .mark_bar(color="#4c78a8")
        .encode(
            x=alt.X("label:N", title=x_title, sort=None),
            y=alt.Y("value:Q", title=y_title, scale=percent_scale()),
            tooltip=[
                alt.Tooltip("label:N", title=x_title),
                alt.Tooltip("value:Q", title=y_title, format=".1f"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)
