"""
Step 2f-v2: Build the 9-feature matrix for Model 2 V2 (Baseline Model).

For institutional fund managers, political features are fixed at neutral values:
  1. cohort_alpha        — computed (30-day return vs SPY)
  2. pre_trade_alpha     — computed (5-day pre-trade return vs SPY)
  3. proximity_days      — Model 1 median value (no political context)
  4. bill_proximity      — Model 1 median value (no bill access)
  5. has_proximity_data  — 0 (fund managers have no vote data)
  6. committee_relevance — 0.0 (not on committees)
  7. amount_zscore       — 0.0 (no personal baseline in congressional context)
  8. cluster_score       — 0 (no congressional clustering)
  9. disclosure_lag      — 0.0 (log1p(0) = 0, quarterly filing is norm)

Input:  data/cleaned/baseline_trades_clean.csv
Output: data/features/model2_v2_features.csv
"""
import numpy as np
import pandas as pd
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend" / "data" / "raw"

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
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


def get_price(ticker, date, cache):
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] >= date]
    return float(subset.iloc[0]["close"]) if not subset.empty else None


def get_price_before(ticker, date, cache):
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] <= date]
    return float(subset.iloc[-1]["close"]) if not subset.empty else None


def compute_cohort_alpha(ticker, date, cache):
    p0 = get_price(ticker, date, cache)
    p1 = get_price(ticker, date + timedelta(days=30), cache)
    s0 = get_price("SPY", date, cache)
    s1 = get_price("SPY", date + timedelta(days=30), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0


def compute_pre_trade_alpha(ticker, date, cache):
    p1 = get_price_before(ticker, date, cache)
    p0 = get_price_before(ticker, date - timedelta(days=7), cache)
    s1 = get_price_before("SPY", date, cache)
    s0 = get_price_before("SPY", date - timedelta(days=7), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0


def build_feature_matrix(model1_median_proximity: int = 7,
                         model1_median_bill_prox: int = 90) -> pd.DataFrame:
    df = pd.read_csv(
        ROOT / "data" / "cleaned" / "baseline_trades_clean.csv",
        parse_dates=["inferred_date"],
    )
    cache = load_price_cache()

    # Deduplicate price lookups: compute per unique (ticker, date) pair
    unique_pairs = df[["ticker", "inferred_date"]].drop_duplicates()
    print(f"[model2/v2] {len(df)} baseline trades, {len(unique_pairs)} unique (ticker, date) pairs")

    print("[model2/v2] Computing cohort_alpha + pre_trade_alpha...")
    alpha_map = {}
    pre_alpha_map = {}
    for _, row in unique_pairs.iterrows():
        key = (row["ticker"], row["inferred_date"])
        alpha_map[key] = compute_cohort_alpha(row["ticker"], row["inferred_date"], cache)
        pre_alpha_map[key] = compute_pre_trade_alpha(row["ticker"], row["inferred_date"], cache)

    df["cohort_alpha"] = df.apply(
        lambda r: alpha_map.get((r["ticker"], r["inferred_date"]), np.nan), axis=1
    )
    df["pre_trade_alpha"] = df.apply(
        lambda r: pre_alpha_map.get((r["ticker"], r["inferred_date"]), np.nan), axis=1
    )
    df["pre_trade_alpha"] = df["pre_trade_alpha"].fillna(0.0)
    print(f"  cohort_alpha computed: {df['cohort_alpha'].notna().sum()}/{len(df)}")
    print(f"  pre_trade_alpha computed: {(df['pre_trade_alpha'] != 0).sum()}/{len(df)}")

    # Fixed values — fund managers have no political context
    df["proximity_days"] = model1_median_proximity
    df["bill_proximity"] = model1_median_bill_prox
    df["has_proximity_data"] = 0
    df["committee_relevance"] = 0.0
    df["amount_zscore"] = 0.0
    df["cluster_score"] = 0
    df["disclosure_lag"] = 0.0   # log1p(0) = 0

    before = len(df)
    df = df.dropna(subset=["cohort_alpha"])
    print(f"[model2/v2] {before - len(df)} dropped (missing prices). "
          f"{len(df)} remain.")

    out = df[["cik", "fund_name", "ticker", "inferred_date",
               "trade_type"] + FEATURES]
    out_path = ROOT / "data" / "features" / "model2_v2_features.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[model2/v2] Saved {out_path} ({len(out)} rows)")

    print(f"\n[model2/v2] Feature summary:")
    print(out[FEATURES].describe().round(4).to_string())
    return out


if __name__ == "__main__":
    build_feature_matrix()
