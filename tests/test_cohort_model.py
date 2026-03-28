"""Tests for Model 1 — Cohort Model."""
import pytest
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FEATURES = [
    "cohort_alpha", "proximity_days", "has_proximity_data",
    "committee_relevance", "disclosure_lag",
]


def normalize(raw):
    return ((-np.clip(raw, -0.5, 0.5) + 0.5) * 100).astype(int).clip(0, 100)


@pytest.fixture
def model():
    return joblib.load(ROOT / "model" / "cohort_model.pkl")


def test_outlier_rate(model):
    df = pd.read_csv(ROOT / "data" / "features" / "model1_features.csv")
    labels = model.predict(df[FEATURES])
    rate = (labels == -1).mean()
    assert 0.01 <= rate <= 0.20, f"Cohort outlier rate {rate:.2%} outside 1-20%"


def test_obvious_anomaly_flagged(model):
    """Extreme values on all 5 features should score >= 65."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.45, "proximity_days": 2, "has_proximity_data": 1,
        "committee_relevance": 1.0, "disclosure_lag": 120,
    }])
    scaler = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx >= 65, f"Obvious congressional anomaly scored only {idx}"


def test_normal_congressional_trade(model):
    """Unremarkable trade should score < 40."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.01, "proximity_days": 7, "has_proximity_data": 0,
        "committee_relevance": 0.0, "disclosure_lag": 10,
    }])
    scaler = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx < 40, f"Normal congressional trade scored {idx} — model over-flagging"


def test_stability(model):
    """Re-training with different seeds should produce >= 85% label agreement."""
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    df = pd.read_csv(ROOT / "data" / "features" / "model1_features.csv")
    X = df[FEATURES]
    labels_all = []
    for seed in range(10):
        p = Pipeline([
            ("s", StandardScaler()),
            ("i", IsolationForest(
                n_estimators=200, contamination="auto",
                random_state=seed, n_jobs=-1,
            )),
        ])
        p.fit(X)
        labels_all.append(p.predict(X))
    arr = np.array(labels_all)
    agreement = np.mean([
        max((arr[:, i] == -1).sum(), (arr[:, i] == 1).sum()) / 10
        for i in range(X.shape[0])
    ])
    assert agreement >= 0.85, f"Model stability {agreement:.2%} below 85%"
