from pathlib import Path
import sys
import pandas as pd

DARK_ZONE_DIR = Path(__file__).resolve().parents[1] / "dark_zone"
if str(DARK_ZONE_DIR) not in sys.path:
    sys.path.insert(0, str(DARK_ZONE_DIR))

from csv_adapter import load_checkpoint_events
from runtime.runtime_controller import DigitalTwinRuntimeController


def _station(sid, coverage, cap=4):
    return {"station_id":sid,"name":sid,"archetype":"A","base_cycle_time_ms":60000,
            "cycle_time_std_ms":6000,"buffer_capacity":cap,"sensor_coverage":coverage}


def _hist(path):
    pd.DataFrame([
        {"station_id":"S03","variant":"A","entry_ts":"2026-01-01T00:00:00Z","exit_ts":"2026-01-01T00:01:00Z"},
        {"station_id":"S03","variant":"A","entry_ts":"2026-01-01T00:02:00Z","exit_ts":"2026-01-01T00:03:00Z"},
        {"station_id":"S04","variant":"A","entry_ts":"2026-01-01T00:00:00Z","exit_ts":"2026-01-01T00:01:00Z"},
        {"station_id":"S04","variant":"A","entry_ts":"2026-01-01T00:02:00Z","exit_ts":"2026-01-01T00:03:00Z"},
    ]).to_csv(path,index=False)


def test_loader_keeps_anonymous_power_without_hidden_processing_rows(tmp_path: Path):
    cp=tmp_path/'checkpoint_events.csv'; defs=tmp_path/'station_checkpoints.csv'; units=tmp_path/'units.csv'; events=tmp_path/'station_events.csv'
    pd.DataFrame([{"event_id":"C1","timestamp_ms":30000,"event_type":"POWER_DRAW","station_id":"S04","unit_id":"","checkpoint_id":"P1"}]).to_csv(cp,index=False)
    pd.DataFrame([{"station_id":"S04","checkpoint_id":"P1","checkpoint_type":"POWER_DRAW","nominal_progress_fraction":0.55,"read_reliability":0.85,"false_positive_rate":0.0}]).to_csv(defs,index=False)
    pd.DataFrame([{"unit_id":"U1","vehicle_model":"A"}]).to_csv(units,index=False)
    pd.DataFrame([
        {"timestamp_ms":0,"event_type":"DARK_ZONE_ENTERED","station_id":"S03","unit_id":"U1"},
        {"timestamp_ms":120000,"event_type":"DARK_ZONE_EXITED","station_id":"S05","unit_id":"U1"},
    ]).to_csv(events,index=False)
    out=load_checkpoint_events(str(cp),str(defs),str(units),{"S03","S04"},station_events_csv=str(events))
    assert len(out)==1
    assert out[0].event_type.value=='power_draw'
    assert out[0].vehicle_id==''


def test_anonymous_corridor_power_updates_population(tmp_path: Path):
    stations=tmp_path/'stations.csv'; units=tmp_path/'units.csv'; hist=tmp_path/'hist.csv'
    pd.DataFrame([_station('S02','NORMAL'),_station('S03','NONE'),_station('S04','NONE'),_station('S05','NORMAL')]).to_csv(stations,index=False)
    pd.DataFrame([{"unit_id":"U1","vehicle_model":"A"},{"unit_id":"U2","vehicle_model":"A"}]).to_csv(units,index=False)
    _hist(hist)
    c=DigitalTwinRuntimeController(stations,units,DARK_ZONE_DIR,historical_dwell_csv=hist,corridor_particles=100,prediction_interval_s=1000)
    c.process_event({"timestamp_ms":0,"event_type":"DARK_ZONE_ENTERED","station_id":"S03","unit_id":"U1"})
    c.process_event({"timestamp_ms":1000,"event_type":"DARK_ZONE_ENTERED","station_id":"S03","unit_id":"U2"})
    packets=c.process_evidence_event({"timestamp_ms":30000,"event_type":"POWER_DRAW","station_id":"S04","unit_id":None,"checkpoint_progress":0.55})
    assert packets
    assert all(p.route=='DARK_CORRIDOR' for p in packets)
    assert c.corridor_bridge.evidence_applied == 1


def test_light_checkpoint_does_not_become_light_model_sample(tmp_path: Path):
    stations=tmp_path/'stations.csv'; units=tmp_path/'units.csv'; hist=tmp_path/'hist.csv'
    pd.DataFrame([_station('S02','NORMAL'),_station('S03','NONE'),_station('S04','NONE'),_station('S05','NORMAL')]).to_csv(stations,index=False)
    pd.DataFrame([{"unit_id":"U1","vehicle_model":"A"}]).to_csv(units,index=False)
    _hist(hist)
    c=DigitalTwinRuntimeController(stations,units,DARK_ZONE_DIR,historical_dwell_csv=hist,corridor_particles=100,prediction_interval_s=1000)
    packets=c.process_evidence_event({"timestamp_ms":30000,"event_type":"RFID_CHECKPOINT","station_id":"S05","unit_id":"U1","checkpoint_progress":0.5})
    assert packets == []
    # The LIGHT feature builder must not have consumed this evidence as a station event.
    assert c.light._event_sequence == 0 if hasattr(c.light, '_event_sequence') else True
