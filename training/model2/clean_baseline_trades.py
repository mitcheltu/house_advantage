"""
Step 2e: Clean baseline (13-F inferred) trades for Model 2 training.

Input:  data/raw/baseline_trades_inferred.csv
Output: data/cleaned/baseline_trades_clean.csv
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW  = ROOT / "data" / "raw" / "baseline_trades_inferred.csv"
OUT  = ROOT / "data" / "cleaned" / "baseline_trades_clean.csv"


def clean() -> pd.DataFrame:
    df = pd.read_csv(RAW, parse_dates=["inferred_date"])
    before = len(df)

    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    df = df[df["shares_delta"] >= 100]
    df = df.drop_duplicates(subset=["cik", "ticker", "inferred_date", "trade_type"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[model2/clean] {before} → {len(df)} baseline trades after cleaning.")
    print(f"[model2/clean] Saved {OUT}")
    return df


if __name__ == "__main__":
    clean()
