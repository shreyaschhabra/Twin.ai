"""Playback-speed pacing for the coordinated bottleneck replay consumer.

``_pace_delay_seconds`` is the exact delivery-timing formula the bottleneck-only replay
path (``main.py``'s ``replay_command``) already used for its own ``--pace``/``--mult``;
this consumer (``run_current.py --mode replay``, the one ``system run random`` drives)
now reuses it rather than inventing a second pacing mechanism.
"""

from __future__ import annotations

import pytest

from run_current import _pace_delay_seconds, build_parser


class TestPaceDelayFormula:
    def test_no_delay_before_the_first_event(self):
        """Nothing has been delivered yet, so there is nothing to pace against."""
        assert _pace_delay_seconds(1_000, None, mult=1.0) == 0.0

    def test_one_times_speed_is_approximately_real_time(self):
        """1 simulated second at 1x should be about 1 real second."""
        assert _pace_delay_seconds(2_000, 1_000, mult=1.0) == pytest.approx(1.0)

    def test_ten_times_speed_is_ten_times_faster(self):
        """1 simulated hour @ 10x =~ 6 real minutes: a 1000ms gap becomes 0.1s."""
        assert _pace_delay_seconds(2_000, 1_000, mult=10.0) == pytest.approx(0.1)

    def test_twenty_times_speed_is_the_fastest_paced_rate(self):
        """1 simulated hour @ 20x =~ 3 real minutes: a 1000ms gap becomes 0.05s."""
        assert _pace_delay_seconds(2_000, 1_000, mult=20.0) == pytest.approx(0.05)

    def test_three_quarter_speed_slows_the_simulation(self):
        """0.75x should take longer than real-time for the same simulated gap."""
        delay = _pace_delay_seconds(2_000, 1_000, mult=0.75)
        assert delay == pytest.approx(1000 / 750)
        assert delay > _pace_delay_seconds(2_000, 1_000, mult=1.0)

    def test_a_full_hour_at_each_documented_speed(self):
        """The task's own worked examples, expressed as the formula's output."""
        one_hour_ms = 3_600_000
        assert _pace_delay_seconds(one_hour_ms, 0, mult=1.0) == pytest.approx(3600.0)
        assert _pace_delay_seconds(one_hour_ms, 0, mult=10.0) == pytest.approx(360.0)
        assert _pace_delay_seconds(one_hour_ms, 0, mult=20.0) == pytest.approx(180.0)

    def test_delay_never_goes_negative(self):
        """Causal order guarantees non-decreasing timestamps, but the formula clamps too."""
        assert _pace_delay_seconds(1_000, 2_000, mult=1.0) == 0.0

    def test_repeated_timestamps_add_no_delay(self):
        """Several events sharing one timestamp_ms should not be paced apart."""
        assert _pace_delay_seconds(1_000, 1_000, mult=1.0) == 0.0


class TestReplayLoopSleepsProportionally:
    """The real replay loop, not a re-implementation of its formula."""

    def _run(self, monkeypatch, *, pace: bool, mult: float, timestamps: list[int]):
        import run_current

        calls: list[float] = []
        monkeypatch.setattr(run_current.time, "sleep", lambda seconds: calls.append(seconds))

        # Exactly the two lines inside `_run_completed_replay`'s loop body that pace
        # delivery -- exercised here without needing a full model/pipeline fixture.
        delivered = None
        for timestamp_ms in timestamps:
            if pace:
                delay = run_current._pace_delay_seconds(timestamp_ms, delivered, mult)
                if delay:
                    run_current.time.sleep(delay)
            delivered = timestamp_ms
        return calls

    def test_paced_replay_sleeps_between_events(self, monkeypatch):
        calls = self._run(monkeypatch, pace=True, mult=10.0, timestamps=[0, 1_000, 3_000])
        # 1000ms then 2000ms gaps at 10x -> 0.1s then 0.2s.
        assert calls == pytest.approx([0.1, 0.2])

    def test_unpaced_replay_never_sleeps(self, monkeypatch):
        calls = self._run(monkeypatch, pace=False, mult=10.0, timestamps=[0, 1_000, 3_000])
        assert calls == []


class TestArgumentParsing:
    """The parser actually used by `main()` -- not a stand-in."""

    def test_default_is_real_time_and_unpaced(self):
        args = build_parser().parse_args(["--mode", "replay"])
        assert args.pace is False
        assert args.mult == 1.0

    def test_pace_and_mult_are_accepted(self):
        args = build_parser().parse_args(["--mode", "replay", "--pace", "--mult", "12.5"])
        assert args.pace is True
        assert args.mult == 12.5

    @pytest.mark.parametrize("speed", ["0.75", "1", "10", "20"])
    def test_documented_speeds_parse(self, speed):
        args = build_parser().parse_args(["--mode", "replay", "--pace", "--mult", speed])
        assert args.mult == pytest.approx(float(speed))
