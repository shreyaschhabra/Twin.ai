"""Section 16: congestion regimes group raw BLOCKED sub-episodes using the
same tested recovery-gap rule as backend.flow.bottleneck_events. These
tests build a small synthetic internal event frame with a known merge case
(gap <= 60s) and a known split case (gap > 60s)."""

from __future__ import annotations

import pandas as pd

from backend.flow_v3.congestion import RECOVERY_GAP_SECONDS, detect_congestion_regimes


class _FakeBuffer:
    def __init__(self, downstream_station):
        self.downstream_station = downstream_station


class _FakeConfig:
    def __init__(self, buffers):
        self.buffers = buffers


def _row(run_id, event_type, station_id=None, buffer_id=None, from_state=None, to_state=None, t=0.0):
    return {
        "shift_id": run_id, "event_type": event_type, "station_id": station_id, "buffer_id": buffer_id,
        "from_state": from_state, "to_state": to_state, "simulation_time": t,
    }


def test_close_reblocking_merges_into_one_regime():
    config = _FakeConfig({"B10": _FakeBuffer("S11")})
    rows = [
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "PROCESSING", "BLOCKED", t=100.0),
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "BLOCKED", "PROCESSING", t=150.0),
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "PROCESSING", "BLOCKED", t=150.0 + RECOVERY_GAP_SECONDS - 5),
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "BLOCKED", "PROCESSING", t=400.0),
    ]
    df = pd.DataFrame(rows)
    regimes, subepisodes = detect_congestion_regimes(df, config)
    assert len(regimes) == 1
    assert regimes.iloc[0]["n_sub_episodes"] == 2
    assert regimes.iloc[0]["impact_station_id"] == "S11"
    assert (subepisodes.congestion_regime_id == regimes.iloc[0]["congestion_regime_id"]).sum() == 2


def test_far_reblocking_stays_two_regimes():
    config = _FakeConfig({"B10": _FakeBuffer("S11")})
    rows = [
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "PROCESSING", "BLOCKED", t=100.0),
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "BLOCKED", "PROCESSING", t=150.0),
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "PROCESSING", "BLOCKED", t=150.0 + RECOVERY_GAP_SECONDS + 30),
        _row("run1", "STATION_STATE_CHANGED", "S10", "B10", "BLOCKED", "PROCESSING", t=400.0),
    ]
    df = pd.DataFrame(rows)
    regimes, subepisodes = detect_congestion_regimes(df, config)
    assert len(regimes) == 2
    assert sorted(regimes.n_sub_episodes.tolist()) == [1, 1]
    assert set(subepisodes.congestion_regime_id) == set(regimes.congestion_regime_id)


def test_no_blocking_yields_empty_regimes_and_subepisodes():
    config = _FakeConfig({"B10": _FakeBuffer("S11")})
    rows = [_row("run1", "STATION_PROCESSING_COMPLETED", "S10", t=10.0)]
    df = pd.DataFrame(rows)
    regimes, subepisodes = detect_congestion_regimes(df, config)
    assert len(regimes) == 0
    assert len(subepisodes) == 0
