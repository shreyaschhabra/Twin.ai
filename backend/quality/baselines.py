"""Quality baselines (Section 19/20): LogisticRegression baseline and a
LightGBM final model, same conventions as backend/flow/baselines.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from backend.quality.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def build_preprocessor(numeric_features=None, categorical_features=None) -> ColumnTransformer:
    numeric_features = numeric_features if numeric_features is not None else NUMERIC_FEATURES
    categorical_features = categorical_features if categorical_features is not None else CATEGORICAL_FEATURES
    numeric_pipe = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    categorical_pipe = Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    return ColumnTransformer([("num", numeric_pipe, numeric_features), ("cat", categorical_pipe, categorical_features)])


def build_logistic_regression_pipeline(numeric_features=None, categorical_features=None) -> Pipeline:
    return Pipeline([
        ("preprocess", build_preprocessor(numeric_features, categorical_features)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
    ])
