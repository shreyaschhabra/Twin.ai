from __future__ import annotations

import pytest

from runtime.event_source import OrderedEvents


def test_ordered_event_source_preserves_valid_order() -> None:
    source = OrderedEvents([
        {"timestamp_ms": 1, "station_id": "S01", "event_type": "UNIT_ARRIVED"},
        {"timestamp_ms": 1, "station_id": "S01", "event_type": "PROCESSING_STARTED"},
        {"timestamp_ms": 2, "station_id": "S01", "event_type": "PROCESSING_COMPLETED"},
    ])
    assert [event["timestamp_ms"] for event in source] == [1, 1, 2]


def test_ordered_event_source_rejects_retroactive_input() -> None:
    source = OrderedEvents([
        {"timestamp_ms": 2},
        {"timestamp_ms": 1},
    ])
    with pytest.raises(ValueError, match="out of order"):
        list(source)
