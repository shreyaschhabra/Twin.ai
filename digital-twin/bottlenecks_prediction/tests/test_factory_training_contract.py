from pathlib import Path
import json
import pandas as pd

from training.build_bottleneck_dataset import _load_run
from ml.bottleneck_model.train_bottleneck_xgboost import harmonize_types, BOTTLENECK_FEATURES


def test_boundary_controls_are_not_factory_training_events(tmp_path: Path) -> None:
    run=tmp_path/'run_0001'; run.mkdir()
    pd.DataFrame([
        {"station_id":"S02","buffer_capacity":4,"base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"archetype":"A"},
        {"station_id":"S03","buffer_capacity":4,"base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"archetype":"A"},
        {"station_id":"S05","buffer_capacity":4,"base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"archetype":"A"},
    ]).to_csv(run/'stations.csv',index=False)
    pd.DataFrame([
        {"timestamp_ms":0,"station_id":"S02","event_type":"UNIT_ARRIVED","queue_length_after":1,"cycle_time_ms":None},
        {"timestamp_ms":1000,"station_id":"S03","event_type":"DARK_ZONE_ENTERED","queue_length_after":None,"cycle_time_ms":None},
        {"timestamp_ms":5000,"station_id":"S05","event_type":"DARK_ZONE_EXITED","queue_length_after":None,"cycle_time_ms":None},
        {"timestamp_ms":5000,"station_id":"S05","event_type":"UNIT_ARRIVED","queue_length_after":1,"cycle_time_ms":None},
    ]).to_csv(run/'station_events.csv',index=False)
    (run/'run_metadata.json').write_text(json.dumps({"schema_version":"2.1"}))
    _, events=_load_run(run)
    assert events.event_type.tolist()==['UNIT_ARRIVED','UNIT_ARRIVED']
    assert events.station_id.tolist()==['S02','S05']


def test_continuation_preserves_base_category_levels() -> None:
    cols={name:[0.0,0.0] for name in BOTTLENECK_FEATURES}
    cols["station_id"]=["S02","S05"]
    cols["station_archetype"]=["A","A"]
    cols["y_bottleneck"]=[0,1]
    train=pd.DataFrame(cols); val=pd.DataFrame(cols); test=pd.DataFrame(cols)
    fixed={"station_id":["S02","S03","S04","S05"],"station_archetype":["A"]}
    levels=harmonize_types(train,val,test,fixed)
    assert levels["station_id"]==["S02","S03","S04","S05"]
    assert list(train["station_id"].cat.categories)==fixed["station_id"]


def test_factory_training_rejects_run_from_different_dark_topology(tmp_path: Path) -> None:
    import pytest
    from factory_models import _validate_training_runs_against_factory

    configured = pd.DataFrame([
        {"station_id":"S01","archetype":"A","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":0,"sensor_coverage":"NORMAL"},
        {"station_id":"S02","archetype":"A","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NONE"},
        {"station_id":"S03","archetype":"A","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
    ])
    configured_csv = tmp_path / "configured.csv"
    configured.to_csv(configured_csv, index=False)

    run = tmp_path / "run_0001"; run.mkdir()
    raw = configured.copy(); raw["sensor_coverage"] = ["HIGH", "HIGH", "HIGH"]
    raw.to_csv(run / "stations.csv", index=False)
    pd.DataFrame([{"dark_zone_id":"DZ1","start_station_id":"S03","end_station_id":"S03"}]).to_csv(run / "dz.csv", index=False)

    with pytest.raises(ValueError, match="selected factory model contract"):
        _validate_training_runs_against_factory(
            [run], configured_csv, dark_station_ids={"S02"}
        )


def test_factory_training_rejects_static_station_drift(tmp_path: Path) -> None:
    import pytest
    from factory_models import _validate_training_runs_against_factory

    configured = pd.DataFrame([
        {"station_id":"S01","archetype":"A","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":0,"sensor_coverage":"NORMAL"},
        {"station_id":"S02","archetype":"A","base_cycle_time_ms":60000,"cycle_time_std_ms":6000,"buffer_capacity":4,"sensor_coverage":"NORMAL"},
    ])
    configured_csv = tmp_path / "configured.csv"; configured.to_csv(configured_csv, index=False)
    run = tmp_path / "run_0001"; run.mkdir()
    drift = configured.copy(); drift.loc[1, "buffer_capacity"] = 9
    drift.to_csv(run / "stations.csv", index=False)

    with pytest.raises(ValueError, match="buffer_capacity"):
        _validate_training_runs_against_factory(
            [run], configured_csv, dark_station_ids=set()
        )
