"""
Train Model 1 V2 — Cohort Model (Isolation Forest on 9 V2 features).

Input:  data/features/model1_v2_features.csv
Output: model/cohort_model_v2.pkl + model/cohort_model_v2_metadata.json
"""
import json
import joblib
import numpy as np
import pandas as pd
import sklearn
from datetime import datetime
from pathlib import Path
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]


def train():
    df = pd.read_csv(ROOT / "data" / "features" / "model1_v2_features.csv")
    X = df[FEATURES]

    print(f"[model1/train_v2] Training Cohort V2 Model on {len(X)} congressional trades.")
    print(f"[model1/train_v2] Feature statistics:\n{X.describe().round(3)}")

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("iforest", IsolationForest(
            n_estimators=200,
            contamination="auto",
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )),
    ])
    pipeline.fit(X)

    labels = pipeline.predict(X)
    raw_scores = pipeline.named_steps["iforest"].decision_function(
        pipeline.named_steps["scaler"].transform(X)
    )

    outlier_pct = (labels == -1).mean() * 100
    print(f"\n[model1/train_v2] Outlier rate on training data: {outlier_pct:.1f}%")
    print(f"[model1/train_v2] Score range: [{raw_scores.min():.4f}, {raw_scores.max():.4f}]")

    model_dir = ROOT / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(pipeline, model_dir / "cohort_model_v2.pkl")

    metadata = {
        "model_name": "cohort_model_v2",
        "model_version": "2.0.0",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "sklearn_version": sklearn.__version__,
        "training_population": "Congressional STOCK Act disclosures",
        "n_training_samples": int(len(X)),
        "n_features": len(FEATURES),
        "features": FEATURES,
        "changes_from_v1": [
            "Added pre_trade_alpha (5-day pre-trade excess return)",
            "Added bill_proximity (sector-matched legislative timing)",
            "Added amount_zscore (personal trade-size anomaly)",
            "Added cluster_score (concurrent politician trading)",
            "Changed disclosure_lag from raw days to log1p(days)",
        ],
        "hyperparameters": {
            "n_estimators": 200,
            "contamination": "auto",
            "random_state": 42,
        },
        "training_stats": {
            "outlier_pct": round(float(outlier_pct), 2),
            "score_min": round(float(raw_scores.min()), 4),
            "score_max": round(float(raw_scores.max()), 4),
            "score_mean": round(float(raw_scores.mean()), 4),
            "score_std": round(float(raw_scores.std()), 4),
        },
    }
    with open(model_dir / "cohort_model_v2_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[model1/train_v2] Saved model/cohort_model_v2.pkl + cohort_model_v2_metadata.json")
    return pipeline


if __name__ == "__main__":
    train()
