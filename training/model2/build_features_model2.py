"""
Step 2f: Build the 5-feature matrix for Model 2 (Baseline Model).

Features 2–5 are fixed constants for institutional fund managers:
  1. cohort_alpha        — 30-day forward return vs SPY (computed)
  2. proximity_days      — Model 1 median value (no political context)
  3. has_proximity_data  — 0 (fund managers have no vote data)
  4. committee_relevance — 0.0 (fund managers are not on committees)
  5. disclosure_lag      — 0 (quarterly 13-F filing is the norm)

Input:  data/cleaned/baseline_trades_clean.csv
Output: data/features/model2_features.csv
"""
import numpy as np
import pandas as pd
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend" / "data" / "raw"

FEATURES = [
    "cohort_alpha", "proximity_days", "has_proximity_data",
    "committee_relevance", "disclosure_lag",
]


def load_price_cache() -> dict:
    cache = {}
    for f in (DATA / "prices").glob("*.csv"):
        if f.name.startswith("_"):
            continue
        df = pd.read_csv(f)
        df.columns = [c.lower() for c in df.columns]
        if "date" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
        cache[f.stem.upper()] = df.sort_values("date").reset_index(drop=True)
    return cache


def get_price(ticker: str, date: pd.Timestamp, cache: dict):
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] >= date]
    return float(subset.iloc[0]["close"]) if not subset.empty else None


def compute_cohort_alpha(ticker: str, date: pd.Timestamp, cache: dict) -> float:
    p0 = get_price(ticker, date, cache)
    p1 = get_price(ticker, date + timedelta(days=30), cache)
    s0 = get_price("SPY", date, cache)
    s1 = get_price("SPY", date + timedelta(days=30), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0


def build_feature_matrix(model1_median_proximity: int = 7) -> pd.DataFrame:
    df = pd.read_csv(
        ROOT / "data" / "cleaned" / "baseline_trades_clean.csv",
        parse_dates=["inferred_date"],
    )
    cache = load_price_cache()

    print(f"[model2/features] Computing cohort_alpha for {len(df)} baseline trades...")
    df["cohort_alpha"] = df.apply(
        lambda r: compute_cohort_alpha(r["ticker"], r["inferred_date"], cache), axis=1
    )

    # Fixed values — fund managers have no political context
    df["proximity_days"] = model1_median_proximity
    df["has_proximity_data"] = 0
    df["committee_relevance"] = 0.0
    df["disclosure_lag"] = 0

    before = len(df)
    df = df.dropna(subset=["cohort_alpha"])
    print(f"[model2/features] {before - len(df)} dropped (missing prices). "
          f"{len(df)} remain.")

    out = df[["cik", "fund_name", "ticker", "inferred_date",
               "trade_type"] + FEATURES]
    out_path = ROOT / "data" / "features" / "model2_features.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[model2/features] Saved {out_path} ({len(out)} rows)")

    print(f"\n[model2/features] Feature summary:")
    print(out[FEATURES].describe().round(4).to_string())
    return out


if __name__ == "__main__":
    build_feature_matrix()
