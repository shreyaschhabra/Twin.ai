"""
Step 5, Section AC: controlled deterministic target test. Proves label
semantics on a tiny synthetic event sequence, independent of whether the
large generated dataset happens to contain enough positives.
"""

import pandas as pd

from backend.flow.labels import label_rows


def _blocked_event(shift_id, station_id, t, buffer_id):
    return {
        "shift_id": shift_id, "event_type": "STATION_STATE_CHANGED",
        "station_id": station_id, "buffer_id": buffer_id,
        "from_state": "PROCESSING", "to_state": "BLOCKED", "simulation_time": t,
    }


def _released_event(shift_id, station_id, t):
    return {
        "shift_id": shift_id, "event_type": "STATION_STATE_CHANGED",
        "station_id": station_id, "buffer_id": None,
        "from_state": "BLOCKED", "to_state": "PROCESSING", "simulation_time": t,
    }


class _FakeBuffer:
    def __init__(self, downstream_station):
        self.downstream_station = downstream_station


class _FakeConfig:
    def __init__(self, buffers):
        self.buffers = buffers


def test_controlled_bottleneck_impact_assignment_and_label_windows():
    from backend.flow.bottleneck_events import detect_bottleneck_events

    # S01 blocks on the buffer feeding S02 at t=600 -> impact belongs to S02
    events = pd.DataFrame([
        _blocked_event("SHIFT_T", "S01", 600.0, "B01"),
        _released_event("SHIFT_T", "S01", 650.0),
    ])
    config = _FakeConfig({"B01": _FakeBuffer(downstream_station="S02")})

    impacts = detect_bottleneck_events(events, config)
    assert len(impacts) == 1
    assert impacts.iloc[0].impact_station_id == "S02"
    assert impacts.iloc[0].onset_time == 600.0

    # station-minute grid: rows for S02 (the impacted station) and S99
    # (unrelated) at various t, at 60s spacing
    rows = []
    for t in [0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 570, 600, 620, 650, 700]:
        rows.append({"shift_id": "SHIFT_T", "station_id": "S02", "window_end_time": float(t)})
        rows.append({"shift_id": "SHIFT_T", "station_id": "S99", "window_end_time": float(t)})
    grid = pd.DataFrame(rows)

    labeled = label_rows(grid, impacts)
    s02 = labeled[labeled.station_id == "S02"].set_index("window_end_time")
    s99 = labeled[labeled.station_id == "S99"].set_index("window_end_time")

    # rows whose lead is in [300, 600] become positive — lead=600 at t=0
    # is the inclusive upper boundary, lead=300 at t=300 the inclusive lower
    for t in [0, 60, 120, 180, 240, 300]:
        lead = 600.0 - t
        assert 300 <= lead <= 600
        assert s02.loc[float(t)].label == "POSITIVE", f"t={t} lead={lead}"
        assert s02.loc[float(t)].target == 1

    # rows <5 min (300s) before impact are imminent/excluded, not silently positive
    for t in [360, 420, 480, 540, 570]:
        lead = 600.0 - t
        assert lead < 300
        assert s02.loc[float(t)].label == "IMMINENT"
        assert pd.isna(s02.loc[float(t)].target)

    # rows during the active impact [600, 650] are excluded as ACTIVE
    assert s02.loc[600.0].label == "ACTIVE"
    assert s02.loc[620.0].label == "ACTIVE"

    # after the impact resolves, no more future impacts -> negative
    assert s02.loc[700.0].label == "NEGATIVE"

    # an unrelated station (S99) stays negative throughout — the impact
    # must not leak onto a station it wasn't assigned to
    assert (s99.label == "NEGATIVE").all()


def test_recovery_grouping_rule_merges_close_reblocks_but_not_distant_ones():
    from backend.flow.bottleneck_events import detect_bottleneck_events, RECOVERY_GAP_SECONDS

    # two blocks on the same buffer, gap well under the recovery threshold
    # -> one merged event
    close_events = pd.DataFrame([
        _blocked_event("SHIFT_A", "S01", 1000.0, "B01"),
        _released_event("SHIFT_A", "S01", 1010.0),
        _blocked_event("SHIFT_A", "S01", 1010.0 + RECOVERY_GAP_SECONDS / 2, "B01"),
        _released_event("SHIFT_A", "S01", 1010.0 + RECOVERY_GAP_SECONDS / 2 + 5),
    ])
    config = _FakeConfig({"B01": _FakeBuffer(downstream_station="S02")})
    merged = detect_bottleneck_events(close_events, config)
    assert len(merged) == 1
    assert merged.iloc[0].n_sub_episodes == 2

    # same shape but gap well over the recovery threshold -> two events
    far_events = pd.DataFrame([
        _blocked_event("SHIFT_B", "S01", 1000.0, "B01"),
        _released_event("SHIFT_B", "S01", 1010.0),
        _blocked_event("SHIFT_B", "S01", 1010.0 + RECOVERY_GAP_SECONDS * 5, "B01"),
        _released_event("SHIFT_B", "S01", 1010.0 + RECOVERY_GAP_SECONDS * 5 + 5),
    ])
    separate = detect_bottleneck_events(far_events, config)
    assert len(separate) == 2
    assert all(separate.n_sub_episodes == 1)
