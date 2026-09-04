"""Probability/risk charts must never display outside 0-100%.

This is a visualization concern only: the underlying prediction records are never
altered, only how a percentage is plotted. Every chart of a bottleneck or defect risk
percentage shares one clamped scale (`dashboard.views.chart_utils.percent_scale`), so
an odd value cannot stretch an axis past the valid probability range.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("altair", reason="dashboard/requirements.txt not installed")
pytest.importorskip("pandas", reason="dashboard/requirements.txt not installed")

from dashboard.views.chart_utils import PERCENT_DOMAIN, percent_scale


class TestPercentScale:
    def test_domain_is_the_full_valid_probability_range(self):
        assert PERCENT_DOMAIN == (0, 100)

    def test_scale_domain_matches_and_is_clamped(self):
        scale = percent_scale()
        assert scale.domain == [0, 100]
        assert scale.clamp is True

    def test_scale_does_not_nice_the_domain_outward(self):
        """`nice` would round 0-100 out to something like 0-110; disabled deliberately."""
        scale = percent_scale()
        assert scale.nice is False


class TestBottleneckTimelineChartIsClamped:
    def _feed_with(self, tmp_path: Path, *records):
        from dashboard.live.session import LivePredictionFeed

        stream = tmp_path / "b.jsonl"
        import json

        with stream.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        feed = LivePredictionFeed("R", stream)
        feed.poll()
        return feed

    def _record(self, **overrides):
        payload = {
            "run_id": "R",
            "timestamp_ms": 1000,
            "station_id": "S02",
            "bottleneck_probability": 0.5,
            "bottleneck_risk_percent": 50.0,
            "warning": False,
            "decision_threshold": 0.4,
        }
        payload.update(overrides)
        return payload

    def test_chart_y_scale_is_clamped_even_with_an_out_of_range_probability(self, tmp_path: Path):
        """A malformed upstream value (e.g. >1.0) must not stretch the axis."""
        from dashboard.views.live_bottlenecks import render_timeline_chart

        feed = self._feed_with(
            tmp_path,
            self._record(timestamp_ms=1000, bottleneck_probability=0.5),
            # Nothing upstream should ever emit this, but the chart must not care --
            # parse_point stores whatever probability arrives.
            self._record(timestamp_ms=2000, bottleneck_probability=1.5),
        )

        captured = {}
        import dashboard.views.live_bottlenecks as module

        original_chart = module.st.altair_chart

        def capture(chart, **kwargs):
            captured["chart"] = chart

        module.st.altair_chart = capture
        try:
            render_timeline_chart(feed, "S02")
        finally:
            module.st.altair_chart = original_chart

        # Serialize to the actual Vega-Lite spec rather than walking Altair's Python
        # object graph -- the reliable way to check what will actually be rendered.
        spec = captured["chart"].to_dict()
        y_scales_with_domain = [
            layer_spec["encoding"]["y"]["scale"]
            for layer_spec in spec["layer"]
            if "y" in layer_spec.get("encoding", {}) and "scale" in layer_spec["encoding"]["y"]
        ]
        assert y_scales_with_domain, "no y-scale with a domain was found to check"
        for scale in y_scales_with_domain:
            assert scale["domain"] == [0, 100]
            assert scale["clamp"] is True
            assert scale["nice"] is False


class TestDefectTimelineChartIsClamped:
    def _feed_with(self, tmp_path: Path, *records):
        from dashboard.live.defect_state import LiveDefectState
        from dashboard.live.session import LivePredictionFeed

        stream = tmp_path / "d.jsonl"
        import json

        with stream.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        feed = LivePredictionFeed("R", stream, state=LiveDefectState())
        feed.poll()
        return feed

    def _record(self, **overrides):
        payload = {
            "run_id": "R",
            "timestamp_ms": 1000,
            "unit_id": "U000001",
            "station_id": "S02",
            "defect_probability": 0.5,
            "defect_risk_percent": 50.0,
            "warning": False,
            "decision_threshold": 0.4,
        }
        payload.update(overrides)
        return payload

    def test_chart_y_scale_is_clamped(self, tmp_path: Path):
        from dashboard.views.live_defects import render_defect_timeline_chart

        feed = self._feed_with(
            tmp_path,
            self._record(timestamp_ms=1000, defect_probability=0.2),
            self._record(timestamp_ms=2000, defect_probability=0.8, warning=True),
        )

        captured = {}
        import dashboard.views.live_defects as module

        original_chart = module.st.altair_chart

        def capture(chart, **kwargs):
            captured["chart"] = chart

        module.st.altair_chart = capture
        try:
            render_defect_timeline_chart(feed, "U000001")
        finally:
            module.st.altair_chart = original_chart

        spec = captured["chart"].to_dict()
        y_scales_with_domain = [
            layer_spec["encoding"]["y"]["scale"]
            for layer_spec in spec["layer"]
            if "y" in layer_spec.get("encoding", {}) and "scale" in layer_spec["encoding"]["y"]
        ]
        assert y_scales_with_domain, "no y-scale with a domain was found to check"
        for scale in y_scales_with_domain:
            assert scale["domain"] == [0, 100]
            assert scale["clamp"] is True
            assert scale["nice"] is False


class TestPercentBarChartIsClamped:
    def test_bar_chart_y_scale_is_clamped(self, monkeypatch):
        from dashboard.views.chart_utils import percent_bar_chart
        import dashboard.views.chart_utils as module

        captured = {}

        def capture(chart, **kwargs):
            captured["chart"] = chart

        monkeypatch.setattr(module.st, "altair_chart", capture)
        # An out-of-range value must not be allowed to stretch the axis either.
        percent_bar_chart({"S02": 45.0, "S05": 150.0, "S09": -10.0}, x_title="Station")

        y = captured["chart"].to_dict()["encoding"]["y"]
        assert y["scale"]["domain"] == [0, 100]
        assert y["scale"]["clamp"] is True
        assert y["scale"]["nice"] is False
