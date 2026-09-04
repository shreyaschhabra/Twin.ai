from __future__ import annotations

import json
from pathlib import Path

from factory_registry import (
    get_factory,
    register_factory,
    set_configured_stations,
)


def test_factory_registration_retains_configuration_path(tmp_path: Path) -> None:
    factory = tmp_path / "factory.json"
    factory.write_text(json.dumps({"stations": [{"id": 0}], "darkZones": []}), encoding="utf-8")
    configured = tmp_path / "configured_stations.csv"
    configured.write_text("station_id,sensor_coverage\nS01,HIGH\n", encoding="utf-8")
    registry = tmp_path / "factories.json"

    registered = register_factory("Factory A", factory, registry)
    updated = set_configured_stations("Factory A", configured, registry)

    assert registered["dark_zone_count"] == 0
    assert updated["configured_stations"] == str(configured.resolve())
    assert get_factory("factory-a", registry) == updated
