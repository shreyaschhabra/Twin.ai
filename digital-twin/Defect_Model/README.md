# Defect Model V2 — 30 causal features only

Expected root layout:

```text
model2 new/
├── factory_defect_prediction_v2_pack/
│   ├── train/outputs/*.zip
│   ├── validation/outputs/*.zip
│   └── test/outputs/*.zip
├── src/
├── generated_features/
├── saved_models/
├── results/
├── requirements.txt
└── README.md
```

Run from the project root:

```bash
python -m pip install -r requirements.txt
python src/check_actual_defect_rates.py
python src/build_causal_features.py --workers 4
python src/train_catboost.py
```

STOP after `train_catboost.py`. Inspect validation results first.

Only when you explicitly decide to spend the final test set:

```bash
python src/final_test.py
```

The first three scripts do not access `test/`.
