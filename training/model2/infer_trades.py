"""
Step 2c: Infer trades from consecutive 13-F quarterly snapshots.

Compares quarter-over-quarter holdings to derive buy/sell signals.
Filters to curated clean funds only.

Input:  backend/data/raw/13f/*_holdings.csv + data/raw/cusip_ticker_map.csv
Output: data/raw/baseline_trades_inferred.csv
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_13F = ROOT / "backend" / "data" / "raw" / "13f"

# Curated clean funds (CIK → name) — must match collect_sec_13f.py
CLEAN_FUND_CIKS = {
    "102909":  "Vanguard",
    "93751":   "StateStreet",
    "315066":  "Fidelity",
    "1037389": "Berkshire",
    "1061768": "Renaissance",
    "1038133": "TRowePrice",
    "1364742": "BlackRock",
    "1350694": "Citadel",
    "1336528": "Bridgewater",
    "1535392": "TwoSigma",
}

MIN_SHARES_DELTA = 100  # noise threshold


def _load_quarter(path: Path) -> pd.DataFrame:
    """Load a single quarter of holdings, filter to clean funds, normalise."""
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.lower().strip() for c in df.columns]
    
    # Filter to clean funds
    df = df[df["cik"].isin(CLEAN_FUND_CIKS.keys())]
    
    # Parse shares
    shares_col = "sshprnamt" if "sshprnamt" in df.columns else "shares"
    df["shares"] = pd.to_numeric(df[shares_col], errors="coerce").fillna(0)
    
    # Equity shares only
    type_col = next((c for c in df.columns if "sshprnamt" in c and "type" in c), None)
    share_type_col = "share_type" if "share_type" in df.columns else type_col
    if share_type_col and share_type_col in df.columns:
        df = df[df[share_type_col] == "SH"]
    
    return df


def infer_from_pair(q1_path: Path, q2_path: Path,
                    ticker_map: dict[str, str],
                    trade_date: str) -> pd.DataFrame:
    q1 = _load_quarter(q1_path)
    q2 = _load_quarter(q2_path)

    q1_pivot = q1.groupby(["cik", "cusip"])["shares"].sum()
    q2_pivot = q2.groupby(["cik", "cusip"])["shares"].sum()

    combined = q1_pivot.rename("q1_shares").to_frame().join(
        q2_pivot.rename("q2_shares"), how="outer"
    ).fillna(0).reset_index()

    combined["delta"] = combined["q2_shares"] - combined["q1_shares"]
    combined = combined[combined["delta"].abs() >= MIN_SHARES_DELTA]
    combined["trade_type"] = combined["delta"].apply(lambda x: "buy" if x > 0 else "sell")
    combined["shares_delta"] = combined["delta"].abs().astype(int)
    combined["inferred_date"] = trade_date
    combined["ticker"] = combined["cusip"].map(ticker_map)
    combined["fund_name"] = combined["cik"].map(CLEAN_FUND_CIKS)

    # Drop unresolved tickers
    combined = combined.dropna(subset=["ticker"])
    combined = combined[combined["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]

    return combined[["cik", "fund_name", "cusip", "ticker",
                      "trade_type", "shares_delta", "inferred_date"]]


def build_all_inferred_trades() -> pd.DataFrame:
    # Load CUSIP→ticker map
    map_path = ROOT / "data" / "raw" / "cusip_ticker_map.csv"
    if not map_path.exists():
        raise FileNotFoundError(
            f"{map_path} not found. Run resolve_tickers.py first."
        )
    cmap = pd.read_csv(map_path, dtype=str)
    ticker_map = dict(zip(cmap["cusip"], cmap["ticker"]))
    print(f"[model2/infer] Loaded {len(ticker_map)} CUSIP→ticker mappings")

    # Discover available quarters from filenames
    available = sorted([
        f.stem.replace("_holdings", "")
        for f in RAW_13F.glob("*_holdings.csv")
    ])
    print(f"[model2/infer] Available quarters: {available}")

    # Build consecutive pairs
    all_trades = []
    for i in range(len(available) - 1):
        q1_key = available[i]
        q2_key = available[i + 1]
        q1_path = RAW_13F / f"{q1_key}_holdings.csv"
        q2_path = RAW_13F / f"{q2_key}_holdings.csv"

        # Parse year/quarter for trade date (end of q1 period)
        year = int(q1_key[:4])
        q = int(q1_key[5])
        quarter_ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        trade_date = f"{year}-{quarter_ends[q]}"

        try:
            inferred = infer_from_pair(q1_path, q2_path, ticker_map, trade_date)
            all_trades.append(inferred)
            print(f"[model2/infer] {q1_key}→{q2_key}: {len(inferred)} inferred trades")
        except Exception as e:
            print(f"[model2/infer] Skipping {q1_key}→{q2_key}: {e}")

    if not all_trades:
        raise RuntimeError("No trades inferred — check 13-F files and CUSIP map.")

    df = pd.concat(all_trades, ignore_index=True)
    df["inferred_date"] = pd.to_datetime(df["inferred_date"])

    out_path = ROOT / "data" / "raw" / "baseline_trades_inferred.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\n[model2/infer] Total inferred baseline trades: {len(df)}")
    print(f"[model2/infer] Saved {out_path}")
    return df


if __name__ == "__main__":
    build_all_inferred_trades()
