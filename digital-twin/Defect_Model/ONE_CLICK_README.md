# One-click V5 defect runner

Copy these files into the ROOT of `model2 new/`:

- `run_defect_pipeline.py`
- `RUN_DEFECT_PIPELINE.command`

Then double-click `RUN_DEFECT_PIPELINE.command`.

It automatically picks the most recently modified existing run ZIP from the
train/validation/test `outputs/` folders and runs:

raw run data
→ causal 30-feature runtime builder
→ frozen V5 CatBoost
→ frozen warning threshold
→ SHAP for warnings
→ JSONL output

Outputs:
- `results/latest_defect_predictions.jsonl`
- `results/latest_defect_run_summary.json`
- timestamped prediction JSONL

Specific run from terminal:
`python run_defect_pipeline.py --run-zip "/path/to/run.zip"`

Important: this does NOT execute `simulation.exe` because that Windows binary
cannot run natively on macOS. It runs the complete finalized defect inference
pipeline on an already-generated run.
