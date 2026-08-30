"""
Stratified evaluation: novel-onset vs. recently-recovered-reblock
positives (Step 5 rigor pass). Motivated by a direct finding: 50.3% of
POSITIVE rows in the combined pool were already BLOCKED at some point in
the preceding 5 minutes (prop_blocked_5m > 0), vs. 0.1% of NEGATIVE
rows -- meaning roughly half our "predicting a bottleneck 5-10 minutes
ahead" examples are really "this station is still inside an unstable,
recently-reblocking episode," not a genuinely fresh problem emerging from
healthy operation. This does not indicate future-data leakage (verified
independently -- see flow_independent_leakage_check.py and the passing
future-mutation tests), but it does mean reported metrics conflate two
very different task difficulties. This script reports them separately.

Usage:
    python scripts/flow_novel_vs_recurring_evaluation.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.flow.baselines import build_logistic_regression_pipeline
from backend.flow.evaluation import row_level_metrics

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "flow_v1"


def section(title):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def main():
    with (OUT_DIR / "dataset_manifest.json").open() as f:
        manifest = json.load(f)
    active_numeric = manifest["numeric_features"]
    active_categorical = manifest["categorical_features"]
    active_features = active_numeric + active_categorical

    train = pd.read_parquet(OUT_DIR / "train.parquet")
    val = pd.read_parquet(OUT_DIR / "validation.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")

    section("POSITIVE-CLASS COMPOSITION: novel onset vs. recently-recovered reblock")
    for name, df in [("TRAIN", train), ("VALIDATION", val), ("TEST", test)]:
        pos = df[df.target == 1]
        recovered = (pos.prop_blocked_5m > 0).sum()
        novel = len(pos) - recovered
        print(f"{name}: {len(pos)} positives -> {novel} novel-onset ({novel/max(1,len(pos))*100:.1f}%), "
              f"{recovered} recently-recovered-reblock ({recovered/max(1,len(pos))*100:.1f}%)")

    pipe = build_logistic_regression_pipeline(active_numeric, active_categorical)
    pipe.fit(train[active_features], train.target)

    section("ROW-LEVEL PERFORMANCE, STRATIFIED (Logistic Regression, same model as the main pipeline)")
    for part_name, df in [("VALIDATION", val), ("TEST", test)]:
        scores = pipe.predict_proba(df[active_features])[:, 1]
        df = df.copy()
        df["_score"] = scores
        neg = df[df.target == 0]
        pos_novel = df[(df.target == 1) & (df.prop_blocked_5m == 0)]
        pos_recovered = df[(df.target == 1) & (df.prop_blocked_5m > 0)]

        print(f"\n{part_name}:")
        for stratum_name, pos_stratum in [("NOVEL-ONSET positives", pos_novel),
                                           ("RECENTLY-RECOVERED-REBLOCK positives", pos_recovered)]:
            if len(pos_stratum) == 0:
                print(f"  {stratum_name}: 0 rows in this partition, skipped")
                continue
            eval_df = pd.concat([neg, pos_stratum])
            m = row_level_metrics(eval_df.target.values, eval_df._score.values, threshold=0.5)
            recall_only = (pos_stratum._score >= 0.5).mean()
            print(f"  {stratum_name} (n={len(pos_stratum)}): recall={recall_only:.3f}  "
                  f"(precision/PR-AUC computed against the FULL negative pool: "
                  f"precision={m.precision:.3f} PR-AUC={m.pr_auc:.3f})")

    section("INTERPRETATION")
    print("If recall on NOVEL-ONSET positives is meaningfully lower than on RECENTLY-RECOVERED-REBLOCK "
          "positives, that confirms the model is substantially better at recognizing 'this station is "
          "still unstable' than at genuinely forecasting a first-time problem from healthy operation -- "
          "the harder, more operationally valuable task this system is actually meant to solve.")


if __name__ == "__main__":
    main()
