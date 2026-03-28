"""
Train Model 2 V2 — Baseline Model (Isolation Forest on 9 V2 features).

Input:  data/features/model2_v2_features.csv
Output: model/baseline_model_v2.pkl + model/baseline_model_v2_metadata.json
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
    df = pd.read_csv(ROOT / "data" / "features" / "model2_v2_features.csv")
    X = df[FEATURES]

    print(f"[model2/train_v2] Training Baseline V2 Model on {len(X)} institutional fund trades.")
    print(f"[model2/train_v2] cohort_alpha stats:\n{X['cohort_alpha'].describe().round(4)}")
    print(f"[model2/train_v2] pre_trade_alpha stats:\n{X['pre_trade_alpha'].describe().round(4)}")
    print(f"[model2/train_v2] NOTE: proximity_days, bill_proximity are median values; "
          f"has_proximity_data=0, committee_relevance=0.0, amount_zscore=0.0, "
          f"cluster_score=0, disclosure_lag=0.0 for all rows (by design).")

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
    print(f"\n[model2/train_v2] Outlier rate on training data: {outlier_pct:.1f}%")
    print(f"[model2/train_v2] Score range: [{raw_scores.min():.4f}, {raw_scores.max():.4f}]")

    model_dir = ROOT / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(pipeline, model_dir / "baseline_model_v2.pkl")

    metadata = {
        "model_name": "baseline_model_v2",
        "model_version": "2.0.0",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "sklearn_version": sklearn.__version__,
        "training_population": "SEC 13-F institutional fund managers",
        "n_training_samples": int(len(X)),
        "n_features": len(FEATURES),
        "features": FEATURES,
        "changes_from_v1": [
            "Added pre_trade_alpha (computed for institutional trades)",
            "Added bill_proximity, amount_zscore, cluster_score (fixed at neutral values)",
            "Changed disclosure_lag from 0 to log1p(0)=0.0",
        ],
        "design_note": (
            "Only cohort_alpha and pre_trade_alpha carry signal. "
            "Other features are fixed at neutral values representing "
            "institutional investors with no legislative access."
        ),
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
    with open(model_dir / "baseline_model_v2_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[model2/train_v2] Saved model/baseline_model_v2.pkl + baseline_model_v2_metadata.json")
    return pipeline


if __name__ == "__main__":
    train()
