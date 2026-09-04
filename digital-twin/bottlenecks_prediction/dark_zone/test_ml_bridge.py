from __future__ import annotations

from pathlib import Path
import hashlib
import tempfile

import numpy as np
import pandas as pd

from dark_zone_ml_bridge import (
    run_feature_bridge, load_corridor_residence_models, _corridor_residence_for, load_dwell_models
)
from dark_zone_feature_reconstructor import FEATURES_28

# Hash normalized source text so the integrity guard is stable across Windows
# CRLF and Unix LF checkouts.  These hashes freeze the intentional current
# DARK core, including the population-likelihood hook used for anonymous
# POWER_DRAW evidence in the corridor tracker.
EXPECTED_CORE_SHA256 = {
    "orchestrator.py": "96cb0806fb70f3672731740f3c5a73d1553d809f6b379491a23faedb295eff7a",
    "dark_zone_tracker.py": "7bf48aa34b31a19af2a1f65bebf0587a11d5d7a1fb7047ccc2fe1920340c82c6",
    "multi_station_tracker.py": "92c4888da8c7c49c8ba7e225284db379096367434ab64bb97f7c681d90f168b5",
    "persistence.py": "724736ed6fd1b50214290049aaa5b477cf9dba65e71080be7aca33d06aa0e552",
}


def _write_inputs(root: Path):
    pd.DataFrame([
        {"station_id":"S1","archetype":"MANUAL","base_cycle_time_ms":70000,"cycle_time_std_ms":10000,"buffer_capacity":3,"sensor_coverage":"NONE"},
        {"station_id":"S2","archetype":"MANUAL","base_cycle_time_ms":60000,"cycle_time_std_ms":8000,"buffer_capacity":3,"sensor_coverage":"NONE"},
        {"station_id":"S3","archetype":"AUTO","base_cycle_time_ms":80000,"cycle_time_std_ms":12000,"buffer_capacity":2,"sensor_coverage":"NONE"},
        {"station_id":"S4","archetype":"INSPECTION","base_cycle_time_ms":50000,"cycle_time_std_ms":5000,"buffer_capacity":2,"sensor_coverage":"FULL"},
    ]).to_csv(root/"stations.csv", index=False)
    pd.DataFrame({"unit_id":["U1","U2","C1","C2"],"vehicle_model":["A"]*4}).to_csv(root/"units.csv", index=False)
    rows = [
        [1,0,"UNIT_ARRIVED","S1","U1",np.nan,np.nan],
        [2,10000,"PROCESSING_STARTED","S1","U1",np.nan,np.nan],
        [3,20000,"UNIT_ARRIVED","S1","U2",np.nan,np.nan],
        [4,30000,"PROCESSING_STARTED","S1","U2",np.nan,np.nan],
        [5,80000,"PROCESSING_COMPLETED","S1","U1",70000,np.nan],
        [6,100000,"PROCESSING_COMPLETED","S1","U2",70000,np.nan],
        [7,0,"DARK_ZONE_ENTERED","S2","C1",np.nan,"DZ"],
        [8,30000,"DARK_ZONE_ENTERED","S2","C2",np.nan,"DZ"],
        [9,200000,"DARK_ZONE_EXITED","S4","C1",np.nan,"DZ"],
        [10,230000,"DARK_ZONE_EXITED","S4","C2",np.nan,"DZ"],
    ]
    pd.DataFrame(rows, columns=["event_id","timestamp_ms","event_type","station_id","unit_id","cycle_time_ms","dark_zone_id"]).to_csv(root/"station_events.csv", index=False)
    pd.DataFrame([
        {"station_id":"S1","unit_id":"U1","timestamp_ms":70000,"check_type":"VISUAL_ALIGNMENT","result":"PASS"},
        {"station_id":"S3","unit_id":"C1","timestamp_ms":150000,"check_type":"VISUAL_ALIGNMENT","result":"PASS"},
    ]).to_csv(root/"manual_checks.csv", index=False)
    pd.DataFrame([
        {"station_id":"S1","checkpoint_id":"CP1","checkpoint_type":"RFID","nominal_progress_fraction":0.5,"read_reliability":0.99,"false_positive_rate":0.01},
        {"station_id":"S2","checkpoint_id":"CP2","checkpoint_type":"RFID","nominal_progress_fraction":0.6,"read_reliability":0.99,"false_positive_rate":0.01},
    ]).to_csv(root/"station_checkpoints.csv", index=False)
    pd.DataFrame([
        {"event_id":"cp1","timestamp_ms":40000,"event_type":"RFID_CHECKPOINT","station_id":"S1","unit_id":"U1","checkpoint_id":"CP1"},
        {"event_id":"cp2","timestamp_ms":60000,"event_type":"RFID_CHECKPOINT","station_id":"S2","unit_id":"C1","checkpoint_id":"CP2"},
    ]).to_csv(root/"checkpoint_events.csv", index=False)
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    hist=[]
    for i in range(12):
        for sid,sec in [("S1",70),("S2",60)]:
            e=base+pd.Timedelta(minutes=5*i)
            hist.append({"station_id":sid,"variant":"A","entry_ts":e,"exit_ts":e+pd.Timedelta(seconds=sec+(i%3-1)*3)})
    pd.DataFrame(hist).to_csv(root/"historical_dwell.csv", index=False)


def test_core_engine_files_unchanged():
    here = Path(__file__).resolve().parent
    got = {
        name: hashlib.sha256((here / name).read_text().encode("utf-8")).hexdigest()
        for name in EXPECTED_CORE_SHA256
    }
    assert got == EXPECTED_CORE_SHA256


def test_load_conditioned_corridor_residence_is_separate_from_cycle_prior():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stations = pd.DataFrame([
            {"station_id":"S2","archetype":"MANUAL","base_cycle_time_ms":60000,"cycle_time_std_ms":5000,"buffer_capacity":4},
        ])
        # Processing cycle prior stays ~60 s.
        base = pd.Timestamp("2026-01-01T00:00:00Z")
        proc=[]
        for i in range(40):
            e=base+pd.Timedelta(minutes=i)
            proc.append({"station_id":"S2","variant":"A","entry_ts":e,"exit_ts":e+pd.Timedelta(seconds=60+(i%3-1))})
        pd.DataFrame(proc).to_csv(root/"processing.csv",index=False)
        processing,_ = load_dwell_models(str(root/"processing.csv"), stations)

        # Residence prior is load-conditioned and includes queueing.
        residence=[]
        for load,seconds in [(4,120),(9,360)]:
            for i in range(40):
                e=base+pd.Timedelta(minutes=1000+load*100+i)
                residence.append({"station_id":"S2","variant":"A","entry_ts":e,"exit_ts":e+pd.Timedelta(seconds=seconds+(i%5-2)*2),"corridor_load":load})
        pd.DataFrame(residence).to_csv(root/"residence.csv",index=False)
        bundle=load_corridor_residence_models(str(root/"residence.csv"))
        low,q1,src1=_corridor_residence_for(bundle,"S2","A",4,processing)
        high,q2,src2=_corridor_residence_for(bundle,"S2","A",9,processing)
        assert low.mean() < high.mean() * 0.5
        assert 100 < low.mean() < 140
        assert 330 < high.mean() < 390
        assert q1 > 0.4 and q2 > 0.4
        assert "load_conditioned" in src1 and "load_conditioned" in src2
        # The ordinary processing prior is still the cycle-feature source.
        assert 55 < processing[("S2","A")].mean() < 65


def test_end_to_end_bridge():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); out=root/"out"; _write_inputs(root)
        ml, dash, prov, audit, quality = run_feature_bridge(
            str(root/"stations.csv"), str(root/"station_events.csv"), str(root/"units.csv"),
            str(root/"historical_dwell.csv"), str(out),
            manual_checks_csv=str(root/"manual_checks.csv"),
            checkpoint_events_csv=str(root/"checkpoint_events.csv"),
            station_checkpoints_csv=str(root/"station_checkpoints.csv"),
            prediction_interval_s=30.0, corridor_particles=300, run_id="TEST",
        )
        assert quality["ready"]
        assert [c for c in ml.columns if c in FEATURES_28] == FEATURES_28
        assert "trigger" not in ml.columns
        assert len(ml) > 0
        assert audit["orchestrator_evidence_events_routed"] == 2
        assert audit["corridor_evidence_applied"] == 2
        assert audit["orchestrator_rejections"] == 0
        assert "S3" in quality["config_prior_fallback_stations"]
        assert not np.isinf(ml[[c for c in FEATURES_28 if c not in {"station_id","station_archetype"}]].apply(pd.to_numeric,errors="coerce").to_numpy()).any()
        # No station snapshots are emitted after a vehicle's confirmed dark-zone exit.
        exit_ms={"U1":80000,"U2":100000,"C1":200000,"C2":230000}
        t_ms=pd.to_datetime(ml["prediction_time"],utc=True).astype("int64")//1_000_000
        for vid,end in exit_ms.items():
            m=ml["vehicle_id"].astype(str).eq(vid)
            if m.any():
                assert int(t_ms[m].max()) <= end


if __name__ == "__main__":
    test_core_engine_files_unchanged()
    test_load_conditioned_corridor_residence_is_separate_from_cycle_prior()
    test_end_to_end_bridge()
    print("All Dark-Zone -> ML bridge tests passed.")
