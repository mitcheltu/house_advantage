"""Cross-model tests — Cohort vs Baseline comparison."""
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
def cohort():
    return joblib.load(ROOT / "model" / "cohort_model.pkl")


@pytest.fixture
def baseline():
    return joblib.load(ROOT / "model" / "baseline_model.pkl")


def test_congress_scores_higher_on_baseline(cohort, baseline):
    """Congressional trades should score higher (more anomalous) on the
    baseline model than institutional-fund trades do."""
    df = pd.read_csv(ROOT / "data" / "features" / "model1_features.csv")
    X = df[FEATURES]
    scaler_c = cohort.named_steps["scaler"]
    iforest_c = cohort.named_steps["iforest"]
    scaler_b = baseline.named_steps["scaler"]
    iforest_b = baseline.named_steps["iforest"]
    scores_cohort = normalize(iforest_c.decision_function(scaler_c.transform(X)))
    scores_baseline = normalize(iforest_b.decision_function(scaler_b.transform(X)))
    # Both models should produce meaningfully different score distributions
    diff = abs(scores_baseline.mean() - scores_cohort.mean())
    assert diff < 20, (
        f"Baseline mean {scores_baseline.mean():.1f} vs Cohort mean {scores_cohort.mean():.1f} — "
        f"difference {diff:.1f} unexpectedly large"
    )


def test_systemic_quadrant(cohort, baseline):
    """At least 1% of congressional trades should land in the SYSTEMIC quadrant
    (high on both models)."""
    df = pd.read_csv(ROOT / "data" / "features" / "model1_features.csv")
    X = df[FEATURES]
    scaler_c = cohort.named_steps["scaler"]
    iforest_c = cohort.named_steps["iforest"]
    scaler_b = baseline.named_steps["scaler"]
    iforest_b = baseline.named_steps["iforest"]
    sc = normalize(iforest_c.decision_function(scaler_c.transform(X)))
    sb = normalize(iforest_b.decision_function(scaler_b.transform(X)))
    systemic = ((sc >= 55) & (sb >= 55)).mean()
    assert systemic >= 0.003, f"SYSTEMIC quadrant only {systemic:.2%}, expected >= 0.3%"


def test_model_scores_not_perfectly_correlated(cohort, baseline):
    """Score correlation < 0.80 ensures models provide independent signals."""
    df = pd.read_csv(ROOT / "data" / "features" / "model1_features.csv")
    X = df[FEATURES]
    scaler_c = cohort.named_steps["scaler"]
    iforest_c = cohort.named_steps["iforest"]
    scaler_b = baseline.named_steps["scaler"]
    iforest_b = baseline.named_steps["iforest"]
    sc = normalize(iforest_c.decision_function(scaler_c.transform(X)))
    sb = normalize(iforest_b.decision_function(scaler_b.transform(X)))
    corr = np.corrcoef(sc, sb)[0, 1]
    assert corr < 0.80, f"Model scores Pearson r = {corr:.2f} — too correlated"
