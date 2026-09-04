"""Playback-speed pacing for the coordinated defect replay consumer.

``_pace_delay_seconds`` mirrors the bottleneck consumer's own replay pacing (itself the
same delivery-timing formula ``main.py``'s ``replay_command`` already used for the
bottleneck-only path): both consumers pace independently against the same
``timestamp_ms`` values from one run's shared event timeline, so they advance through
simulated time together when ``system run random --mult`` is used.
"""

from __future__ import annotations

import pytest

from Defect_Model.run_current_defects import _pace_delay_seconds, parser


class TestPaceDelayFormula:
    def test_no_delay_before_the_first_event(self):
        assert _pace_delay_seconds(1_000, None, mult=1.0) == 0.0

    def test_one_times_speed_is_approximately_real_time(self):
        assert _pace_delay_seconds(2_000, 1_000, mult=1.0) == pytest.approx(1.0)

    def test_ten_times_speed_is_ten_times_faster(self):
        assert _pace_delay_seconds(2_000, 1_000, mult=10.0) == pytest.approx(0.1)

    def test_twenty_times_speed_is_the_fastest_paced_rate(self):
        assert _pace_delay_seconds(2_000, 1_000, mult=20.0) == pytest.approx(0.05)

    def test_three_quarter_speed_slows_the_simulation(self):
        delay = _pace_delay_seconds(2_000, 1_000, mult=0.75)
        assert delay == pytest.approx(1000 / 750)
        assert delay > _pace_delay_seconds(2_000, 1_000, mult=1.0)

    def test_matches_the_bottleneck_consumers_formula_exactly(self):
        """Both consumers must pace off the same clock, or their streams drift apart."""
        import sys
        from pathlib import Path

        bottleneck_package = Path(__file__).resolve().parents[2] / "bottlenecks_prediction"
        if str(bottleneck_package) not in sys.path:
            sys.path.insert(0, str(bottleneck_package))
        from run_current import _pace_delay_seconds as bottleneck_pace_delay

        for mult in (0.75, 1.0, 3.5, 10.0, 20.0):
            for gap in (0, 250, 1_000, 60_000):
                assert _pace_delay_seconds(gap, 0, mult) == pytest.approx(
                    bottleneck_pace_delay(gap, 0, mult)
                )


class TestReplayLoopSleepsProportionally:
    def _run(self, monkeypatch, *, pace: bool, mult: float, timestamps: list[int]):
        import Defect_Model.run_current_defects as run_current_defects

        calls: list[float] = []
        monkeypatch.setattr(
            run_current_defects.time, "sleep", lambda seconds: calls.append(seconds)
        )

        delivered = None
        for timestamp_ms in timestamps:
            if pace:
                delay = run_current_defects._pace_delay_seconds(timestamp_ms, delivered, mult)
                if delay:
                    run_current_defects.time.sleep(delay)
            delivered = timestamp_ms
        return calls

    def test_paced_replay_sleeps_between_events(self, monkeypatch):
        calls = self._run(monkeypatch, pace=True, mult=10.0, timestamps=[0, 1_000, 3_000])
        assert calls == pytest.approx([0.1, 0.2])

    def test_unpaced_replay_never_sleeps(self, monkeypatch):
        calls = self._run(monkeypatch, pace=False, mult=10.0, timestamps=[0, 1_000, 3_000])
        assert calls == []


class TestArgumentParsing:
    def test_default_is_real_time_and_unpaced(self):
        args = parser().parse_args(["--mode", "replay"])
        assert args.pace is False
        assert args.mult == 1.0

    def test_pace_and_mult_are_accepted(self):
        args = parser().parse_args(["--mode", "replay", "--pace", "--mult", "12.5"])
        assert args.pace is True
        assert args.mult == 12.5

    @pytest.mark.parametrize("speed", ["0.75", "1", "10", "20"])
    def test_documented_speeds_parse(self, speed):
        args = parser().parse_args(["--mode", "replay", "--pace", "--mult", speed])
        assert args.mult == pytest.approx(float(speed))
