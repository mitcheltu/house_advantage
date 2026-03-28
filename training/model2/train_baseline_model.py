"""
Step 2g: Train Model 2 — Baseline Model (Isolation Forest on 13-F fund trades).

Input:  data/features/model2_features.csv
Output: model/baseline_model.pkl + model/baseline_model_metadata.json
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
    df = pd.read_csv(ROOT / "data" / "features" / "model2_features.csv")
    X = df[FEATURES]

    print(f"[model2/train] Training Baseline Model on {len(X)} institutional fund trades.")
    print(f"[model2/train] cohort_alpha stats:\n{X['cohort_alpha'].describe().round(4)}")
    print(f"[model2/train] NOTE: proximity_days=7, has_proximity_data=0, "
          f"committee_relevance=0.0, disclosure_lag=0 for all rows (by design).")

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
    print(f"\n[model2/train] Outlier rate on training data: {outlier_pct:.1f}%")
    print(f"[model2/train] Score range: [{raw_scores.min():.4f}, {raw_scores.max():.4f}]")

    model_dir = ROOT / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(pipeline, model_dir / "baseline_model.pkl")

    metadata = {
        "model_name": "baseline_model",
        "model_version": "1.0.0",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "sklearn_version": sklearn.__version__,
        "training_population": "SEC 13-F institutional fund managers",
        "n_training_samples": int(len(X)),
        "training_date_range": {
            "start": str(pd.to_datetime(df["inferred_date"]).min().date()),
            "end": str(pd.to_datetime(df["inferred_date"]).max().date()),
        },
        "features": FEATURES,
        "hyperparameters": {
            "n_estimators": 200,
            "contamination": "auto",
            "random_state": 42,
        },
        "design_note": (
            "Features 2-4 are fixed constants for all training samples. "
            "The model learns the normal distribution of cohort_alpha for "
            "institutional investors with no legislative access."
        ),
        "training_stats": {
            "outlier_pct": round(float(outlier_pct), 2),
            "score_min": round(float(raw_scores.min()), 4),
            "score_max": round(float(raw_scores.max()), 4),
            "score_mean": round(float(raw_scores.mean()), 4),
            "score_std": round(float(raw_scores.std()), 4),
        },
    }
    with open(model_dir / "baseline_model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[model2/train] Saved model/baseline_model.pkl + baseline_model_metadata.json")
    return pipeline


if __name__ == "__main__":
    train()
