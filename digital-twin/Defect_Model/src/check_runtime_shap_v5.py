from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from feature_schema import DEFECT_FEATURES, TARGET_COLUMN
from ml.defect_model_runtime import DefectModelRuntime
from runtime.defect_feature_runtime import DefectFeaturePacket


def main():
    validation_path = ROOT / "generated_features_v5" / "validation.pkl"
    model_path = ROOT / "saved_models" / "defect_v5_models.joblib"
    config_path = ROOT / "saved_models" / "defect_v5_config.json"
    calibrator_path = ROOT / "saved_models" / "defect_v5_calibrator.joblib"

    val = pd.read_pickle(validation_path)
    val = val[val[TARGET_COLUMN].notna()].copy().reset_index(drop=True)

    runtime = DefectModelRuntime(model_path, config_path, calibrator_path)

    # Pick the highest-risk PRE-final-inspection row so the explanation is meaningful.
    pre = val[val["prediction_station_index"] < val["final_station_index"]].copy()
    scores = runtime.predict_feature_rows(pre[DEFECT_FEATURES])
    pos = int(scores["defect_probability"].to_numpy().argmax())
    row = pre.iloc[pos]
    expected = scores.iloc[pos]

    packet = DefectFeaturePacket(
        run_id=str(row["run_id"]),
        unit_id=str(row["unit_id"]),
        station_id=str(row["prediction_station"]),
        station_index=int(row["prediction_station_index"]),
        prediction_time_ms=int(row["prediction_time"]),
        event_id=None,
        event_sequence=int(row["prediction_event_sequence"]),
        final_station_id=f"S{int(row['final_station_index']) + 1:02d}",
        final_station_index=int(row["final_station_index"]),
        features_30={f: row[f] for f in DEFECT_FEATURES},
    )

    prediction = runtime.predict_packet(packet, explain=True, shap_top_k=5)
    payload = prediction.as_dict()

    assert prediction.explanation_available is True
    assert prediction.explanation_method == "catboost_native_shap"
    assert prediction.shap_value_space == "raw_log_odds"
    assert prediction.shap_probability_reconstruction_error is not None
    assert prediction.shap_probability_reconstruction_error < 1e-10
    assert abs(
        prediction.defect_probability - float(expected["defect_probability"])
    ) < 1e-12
    assert len(prediction.top_risk_drivers) > 0
    assert len(prediction.top_protective_drivers) > 0

    print("=" * 90)
    print("V5 RUNTIME SHAP CHECK")
    print("=" * 90)
    print(f"Run: {prediction.run_id}")
    print(f"Unit: {prediction.unit_id}")
    print(f"Station: {prediction.station_id}")
    print(f"Defect probability: {100*prediction.defect_probability:.2f}%")
    print(f"SHAP reconstruction error: {prediction.shap_probability_reconstruction_error:.3e}")
    print("\nTop risk drivers:")
    for d in prediction.top_risk_drivers:
        print(
            f"  + {d['feature']:<36} "
            f"SHAP={d['shap_value_raw']:+.5f}  value={d['feature_value']}"
        )
    print("\nTop protective drivers:")
    for d in prediction.top_protective_drivers:
        print(
            f"  - {d['feature']:<36} "
            f"SHAP={d['shap_value_raw']:+.5f}  value={d['feature_value']}"
        )
    print("\nRUNTIME SHAP CHECK PASSED")


if __name__ == "__main__":
    main()
