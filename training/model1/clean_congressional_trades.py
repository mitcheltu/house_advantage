"""
Step 1d: Clean congressional trades for Model 1 training.

Input:  backend/data/raw/congressional_trades_raw.csv
Output: data/cleaned/congressional_trades_clean.csv
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW  = ROOT / "backend" / "data" / "raw" / "congressional_trades_raw.csv"
OUT  = ROOT / "data" / "cleaned" / "congressional_trades_clean.csv"


def clean() -> pd.DataFrame:
    df = pd.read_csv(RAW, parse_dates=["trade_date", "disclosure_date"])

    before = len(df)
    # Keep equities with valid tickers
    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    # Drop rows missing critical dates
    df = df.dropna(subset=["trade_date", "disclosure_date", "ticker"])
    # Sane disclosure lag (0–365 days)
    df = df[df["disclosure_lag_days"].between(0, 365)]
    # Valid trade types only
    df = df[df["trade_type"].isin(["buy", "sell", "exchange"])]
    # De-duplicate
    df = df.drop_duplicates(subset=["politician_id", "ticker", "trade_date", "trade_type"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[model1/clean] {before} → {len(df)} trades after cleaning.")
    print(f"[model1/clean] Saved {OUT}")
    return df


if __name__ == "__main__":
    clean()
