# V5 Defect Runtime Pipeline V3 — SHAP integrated

This overlays the already parity-validated V2 runtime pipeline.

## What changed

Added native CatBoost SHAP explanations without changing the trained model.

New file:
- `ml/defect_explainer.py`

Updated:
- `ml/defect_model_runtime.py`
- `runtime/defect_pipeline.py`
- `output/defect_prediction_output.py`
- `defect_main.py`

Optional check:
- `src/check_runtime_shap_v5.py`

`runtime/defect_feature_runtime.py` is unchanged from the parity-validated V2 pack.

## Explanation modes

`warnings` is the default and recommended runtime mode:
- normal prediction -> probability/warning only
- actionable warning -> probability + SHAP top drivers

`all` computes SHAP for every prediction and is heavier.

`off` disables SHAP.

## Output fields

Each explained prediction includes:
- `explanation_available`
- `explanation_method = catboost_native_shap`
- `shap_value_space = raw_log_odds`
- `shap_base_value_raw`
- `shap_reconstructed_probability`
- `shap_probability_reconstruction_error`
- `top_risk_drivers`
- `top_protective_drivers`

Each driver contains:
- exact feature name
- dashboard-friendly label
- feature value
- SHAP contribution
- risk direction

## Install

Copy/overwrite the bundle contents into the project root.

Do NOT replace:
- `src/feature_schema.py`
- the trained V5 artifacts
- `generated_features_v5/`

Then run:

```bash
python src/check_runtime_shap_v5.py
```

Expected final line:

```text
RUNTIME SHAP CHECK PASSED
```

The SHAP check is post-ML only. It does not retrain or retune V5.
