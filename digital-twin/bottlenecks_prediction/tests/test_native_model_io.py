from pathlib import Path

from ml.model_io import load_bottleneck_model_bundle
from ml.bottleneck_model.bottleneck_predictor import BottleneckPredictor


def test_native_model_bundle_loads_without_pickled_estimator() -> None:
    root = Path(__file__).resolve().parents[1]
    bundle_path = (
        root / "ml" / "bottleneck_model" / "bottleneck_model_artifacts"
        / "bottleneck_model_bundle.joblib"
    )
    bundle, model, native = load_bottleneck_model_bundle(bundle_path)
    assert "model" not in bundle
    assert native is not None and native.name == "bottleneck_xgboost.json"
    assert model.get_booster() is not None

    predictor = BottleneckPredictor(bundle_path)
    assert predictor.native_model_path == native
