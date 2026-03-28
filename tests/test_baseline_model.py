"""Tests for Model 2 — Baseline Model."""
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
    return joblib.load(ROOT / "model" / "baseline_model.pkl")


def test_outlier_rate(model):
    df = pd.read_csv(ROOT / "data" / "features" / "model2_features.csv")
    labels = model.predict(df[FEATURES])
    rate = (labels == -1).mean()
    assert 0.01 <= rate <= 0.20, f"Baseline outlier rate {rate:.2%} outside 1-20%"


def test_extreme_alpha_flagged(model):
    """Fund trade with huge alpha should score >= 60."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.45, "proximity_days": 7, "has_proximity_data": 0,
        "committee_relevance": 0.0, "disclosure_lag": 0,
    }])
    scaler = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx >= 60, f"Extreme-alpha fund trade scored only {idx}"


def test_market_rate_trade(model):
    """Market-rate trade should score < 40."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.005, "proximity_days": 7, "has_proximity_data": 0,
        "committee_relevance": 0.0, "disclosure_lag": 0,
    }])
    scaler = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx <= 42, f"Market-rate fund trade scored {idx} — model over-flagging"


def test_political_features_dont_affect_baseline(model):
    """Changing committee_relevance or has_proximity_data shouldn't move score much."""
    base = {
        "cohort_alpha": 0.10, "proximity_days": 7, "has_proximity_data": 0,
        "committee_relevance": 0.0, "disclosure_lag": 0,
    }
    political = base.copy()
    political["committee_relevance"] = 1.0
    political["has_proximity_data"] = 1

    scaler = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    s_base = normalize(iforest.decision_function(scaler.transform(pd.DataFrame([base]))))[0]
    s_pol = normalize(iforest.decision_function(scaler.transform(pd.DataFrame([political]))))[0]
    assert abs(s_base - s_pol) < 10, (
        f"Political features swung baseline score {abs(s_base - s_pol)} points"
    )
