from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DARK = ROOT / "dark_zone"
if str(DARK) not in sys.path:
    sys.path.insert(0, str(DARK))

from generate_checkpoint_events import generate_checkpoint_events


def test_no_applicable_checkpoint_produces_schema_correct_empty_csv(tmp_path):
    events = tmp_path / "station_events.csv"
    units = tmp_path / "units.csv"
    checkpoints = tmp_path / "station_checkpoints.csv"
    output = tmp_path / "checkpoint_events.csv"

    pd.DataFrame([
        {"station_id": "S05", "unit_id": "U1", "timestamp_ms": 1000, "event_type": "PROCESSING_STARTED"},
        {"station_id": "S05", "unit_id": "U1", "timestamp_ms": 2000, "event_type": "PROCESSING_COMPLETED"},
    ]).to_csv(events, index=False)
    pd.DataFrame([{"unit_id": "U1", "vehicle_model": "A"}]).to_csv(units, index=False)
    pd.DataFrame([
        {
            "station_id": "S13",
            "checkpoint_id": "CP1",
            "checkpoint_type": "RFID",
            "nominal_progress_fraction": 0.5,
            "read_reliability": 1.0,
            "false_positive_rate": 0.0,
        }
    ]).to_csv(checkpoints, index=False)

    out = generate_checkpoint_events(
        str(events), str(units), str(checkpoints), str(output),
        dark_zone_station_ids={"S05"}, seed=1,
    )

    assert out.empty
    assert list(out.columns) == [
        "event_id", "timestamp_ms", "event_type", "station_id", "unit_id", "checkpoint_id"
    ]
    reread = pd.read_csv(output)
    assert reread.empty
    assert list(reread.columns) == list(out.columns)
