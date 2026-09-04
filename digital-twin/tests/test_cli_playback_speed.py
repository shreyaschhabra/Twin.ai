"""`cli.py system run random --mult`: the operator-facing playback-speed control.

This is the outermost layer of the fix: the dashboard's coordinated pathway always
runs through this exact CLI command, so if the range is wrong or the default drifts
from "1x = real-time" here, no downstream pacing change matters.
"""

from __future__ import annotations

import pytest

import cli


class TestPlaybackSpeedValidator:
    @pytest.mark.parametrize("value", ["0.75", "1", "1.0", "10", "20", "20.0"])
    def test_accepts_the_documented_range(self, value):
        assert cli._playback_speed(value) == pytest.approx(float(value))

    @pytest.mark.parametrize("value", ["0", "0.5", "0.74", "20.01", "21", "30", "60", "-1"])
    def test_rejects_outside_the_documented_range(self, value):
        with pytest.raises(Exception):
            cli._playback_speed(value)

    def test_thirty_and_sixty_are_never_valid(self):
        """The old fixed-jump choices must not survive as accepted values."""
        for stale in ("30", "30.0", "60", "60.0"):
            with pytest.raises(Exception):
                cli._playback_speed(stale)


class TestSystemRunRandomParser:
    def _parse(self, *extra: str):
        parser = cli.build_parser()
        return parser.parse_args(
            ["system", "run", "random", "--output-dir", "out", *extra]
        )

    def test_default_mult_is_one_real_time(self):
        args = self._parse()
        assert args.mult == 1.0

    @pytest.mark.parametrize("value", ["0.75", "1", "10", "20"])
    def test_accepts_documented_speeds(self, value):
        args = self._parse("--mult", value)
        assert args.mult == pytest.approx(float(value))

    @pytest.mark.parametrize("value", ["0.5", "30", "60"])
    def test_rejects_values_outside_the_dashboard_range(self, value):
        with pytest.raises(SystemExit):
            self._parse("--mult", value)

    def test_command_system_run_random_forwards_mult_to_the_runtime(self, tmp_path, monkeypatch):
        """The parsed speed must reach `run_dual_prescribed`, not stop at argparse."""
        captured = {}

        class _FakeRuntime:
            def run_dual_prescribed(self, **kwargs):
                captured.update(kwargs)
                return {"ok": True}

        monkeypatch.setattr(cli, "_system_runtime", lambda: _FakeRuntime())
        monkeypatch.setattr(cli, "generate", lambda *a, **k: None)
        monkeypatch.setattr(cli, "run_generated", lambda *a, **k: None)
        monkeypatch.setattr(cli, "_resolve_simulator", lambda *a, **k: "sim")

        args = self._parse(
            "--mult", "7.5",
            "--generated", str(tmp_path / "generated"),
            "--runs", str(tmp_path / "runs"),
        )
        rc = cli.command_system_run_random(args)
        assert rc == 0
        assert captured["multiplier"] == 7.5
