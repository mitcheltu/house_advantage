"""
Step 1f: Train Model 1 — Cohort Model (Isolation Forest on congressional trades).

Input:  data/features/model1_features.csv
Output: model/cohort_model.pkl + model/cohort_model_metadata.json
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
    "cohort_alpha", "proximity_days", "has_proximity_data",
    "committee_relevance", "disclosure_lag",
]


def train():
    df = pd.read_csv(ROOT / "data" / "features" / "model1_features.csv")
    X = df[FEATURES]

    print(f"[model1/train] Training Cohort Model on {len(X)} congressional trades.")
    print(f"[model1/train] Feature statistics:\n{X.describe().round(3)}")

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
    print(f"\n[model1/train] Outlier rate on training data: {outlier_pct:.1f}%")
    print(f"[model1/train] Score range: [{raw_scores.min():.4f}, {raw_scores.max():.4f}]")

    model_dir = ROOT / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(pipeline, model_dir / "cohort_model.pkl")

    metadata = {
        "model_name": "cohort_model",
        "model_version": "1.0.0",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "sklearn_version": sklearn.__version__,
        "training_population": "Congressional STOCK Act disclosures",
        "n_training_samples": int(len(X)),
        "training_date_range": {
            "start": str(pd.to_datetime(df["trade_date"]).min().date()),
            "end": str(pd.to_datetime(df["trade_date"]).max().date()),
        },
        "features": FEATURES,
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
        "known_limitation": (
            "Baseline is congressional trading cohort, which may itself "
            "reflect systematic information advantages. A low score indicates "
            "'normal for Congress', not 'clean in absolute terms'."
        ),
    }
    with open(model_dir / "cohort_model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[model1/train] Saved model/cohort_model.pkl + cohort_model_metadata.json")
    return pipeline


if __name__ == "__main__":
    train()
