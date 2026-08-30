"""Interpretable dimensionality reduction (Section 19): constants,
near-constants, duplicates, then TRAIN-only correlation filtering. No PCA
-- TrustTwin needs features a human can read off an evidence panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

NEAR_CONSTANT_MAX_UNIQUE_RATIO = 0.01
CORRELATION_THRESHOLD = 0.95


@dataclass
class FeatureSelectionReport:
    raw_count: int
    after_basic_filter: int
    after_correlation_filter: int
    dropped_constant: list[str] = field(default_factory=list)
    dropped_near_constant: list[str] = field(default_factory=list)
    dropped_duplicate: list[str] = field(default_factory=list)
    dropped_correlated: list[tuple[str, str, float]] = field(default_factory=list)
    kept_features: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "raw_feature_count": self.raw_count,
            "after_basic_filter": self.after_basic_filter,
            "after_correlation_filter": self.after_correlation_filter,
            "final_count": len(self.kept_features),
            "dropped_constant": self.dropped_constant,
            "dropped_near_constant": self.dropped_near_constant,
            "dropped_duplicate": self.dropped_duplicate,
            "dropped_correlated": [
                {"dropped": a, "kept_instead": b, "abs_correlation": round(c, 4)}
                for a, b, c in self.dropped_correlated
            ],
            "kept_features": self.kept_features,
        }


def _causal_priority(feature: str) -> int:
    """Lower is preferred when two features are highly correlated. Static/
    interpretable/causal-feeling groups win over derived trend/std."""
    if feature.startswith("static_") or feature in {"baseline_cycle_time_seconds"}:
        return 0
    if feature.startswith("svc_") and "trend" not in feature and "std" not in feature:
        return 1
    if feature.startswith("ms_") and "trend" not in feature:
        return 1
    if "trend" in feature or "std" in feature or "drift" in feature:
        return 3
    return 2


def select_features(
    train_df: pd.DataFrame, candidate_features: list[str], correlation_threshold: float = CORRELATION_THRESHOLD,
) -> FeatureSelectionReport:
    """All statistics computed on TRAIN only, per Section 19."""
    raw_count = len(candidate_features)
    numeric = [f for f in candidate_features if pd.api.types.is_numeric_dtype(train_df[f])]
    non_numeric = [f for f in candidate_features if f not in numeric]

    dropped_constant, dropped_near_constant, dropped_duplicate = [], [], []
    survivors = list(numeric)
    n = len(train_df)

    for feature in numeric:
        nunique = train_df[feature].nunique(dropna=True)
        if nunique <= 1:
            dropped_constant.append(feature)
        elif n > 0 and nunique / n <= NEAR_CONSTANT_MAX_UNIQUE_RATIO:
            dropped_near_constant.append(feature)
    survivors = [f for f in survivors if f not in dropped_constant and f not in dropped_near_constant]

    seen_signatures: dict[tuple, str] = {}
    for feature in list(survivors):
        signature = tuple(np.round(train_df[feature].fillna(-999999.0).to_numpy(dtype=float), 6))
        if signature in seen_signatures:
            dropped_duplicate.append(feature)
            survivors.remove(feature)
        else:
            seen_signatures[signature] = feature

    after_basic_filter = len(survivors) + len(non_numeric)

    dropped_correlated: list[tuple[str, str, float]] = []
    if len(survivors) > 1:
        corr = train_df[survivors].corr().abs()
        ordered = sorted(survivors, key=lambda f: (_causal_priority(f), f))
        dropped: set[str] = set()
        for i, feature_a in enumerate(ordered):
            if feature_a in dropped:
                continue
            for feature_b in ordered[i + 1:]:
                if feature_b in dropped:
                    continue
                value = corr.loc[feature_a, feature_b]
                if pd.notna(value) and value >= correlation_threshold:
                    dropped.add(feature_b)
                    dropped_correlated.append((feature_b, feature_a, float(value)))
        survivors = [f for f in survivors if f not in dropped]

    kept = sorted(survivors) + sorted(non_numeric)
    return FeatureSelectionReport(
        raw_count=raw_count,
        after_basic_filter=after_basic_filter,
        after_correlation_filter=len(kept),
        dropped_constant=dropped_constant,
        dropped_near_constant=dropped_near_constant,
        dropped_duplicate=dropped_duplicate,
        dropped_correlated=dropped_correlated,
        kept_features=kept,
    )
