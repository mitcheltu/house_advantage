"""
QuiverQuant API Collector — Congressional Stock Trades

Downloads STOCK Act trade disclosures from QuiverQuant.
API: https://api.quiverquant.com/beta/live/congresstrading
Auth: Authorization: Token {key} header
Cost: $10-25/month
"""
import logging
import pandas as pd
from .utils import get_env, rate_limited_get, DATA_RAW

log = logging.getLogger("collector.quiverquant")

BASE_URL = "https://api.quiverquant.com/beta"

AMOUNT_RANGES = {
    "$1,001 - $15,000":       (1_001,   15_000),
    "$15,001 - $50,000":      (15_001,  50_000),
    "$50,001 - $100,000":     (50_001,  100_000),
    "$100,001 - $250,000":    (100_001, 250_000),
    "$250,001 - $500,000":    (250_001, 500_000),
    "$500,001 - $1,000,000":  (500_001, 1_000_000),
    "Over $1,000,000":        (1_000_001, 5_000_000),
}

# Static ticker→sector map for known actively-traded tickers
TICKER_SECTOR_MAP = {
    "LMT": "defense", "RTX": "defense", "BA": "defense", "NOC": "defense",
    "GD": "defense", "HII": "defense", "LHX": "defense",
    "JPM": "finance", "GS": "finance", "BAC": "finance", "WFC": "finance",
    "C": "finance", "MS": "finance", "BLK": "finance", "SCHW": "finance",
    "UNH": "healthcare", "CVS": "healthcare", "PFE": "healthcare",
    "JNJ": "healthcare", "MRK": "healthcare", "ABBV": "healthcare",
    "LLY": "healthcare", "TMO": "healthcare", "ABT": "healthcare",
    "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
    "EOG": "energy", "OXY": "energy", "MPC": "energy", "PSX": "energy",
    "AAPL": "tech", "MSFT": "tech", "GOOGL": "tech", "GOOG": "tech",
    "NVDA": "tech", "META": "tech", "AMZN": "tech", "TSLA": "tech",
    "CRM": "tech", "ORCL": "tech", "AVGO": "tech", "AMD": "tech",
    "INTC": "tech", "CSCO": "tech", "ADBE": "tech",
    "T": "telecom", "VZ": "telecom", "TMUS": "telecom",
    "ADM": "agriculture", "DE": "agriculture", "MOS": "agriculture",
}


def _parse_amount(amount_str: str) -> tuple[int, int]:
    """Parse QuiverQuant amount range string into (lower, upper)."""
    if not amount_str:
        return 1_001, 15_000
    for label, (lo, hi) in AMOUNT_RANGES.items():
        if label.lower() in amount_str.lower():
            return lo, hi
    return 1_001, 15_000


def collect_trades() -> pd.DataFrame:
    """
    Fetch all congressional trades from QuiverQuant.
    Saves to data/raw/congressional_trades_raw.csv
    """
    api_key = get_env("QUIVER_API_KEY")
    headers = {"Authorization": f"Token {api_key}"}

    log.info("Fetching congressional trades from QuiverQuant...")
    resp = rate_limited_get(
        f"{BASE_URL}/live/congresstrading",
        headers=headers,
        delay=1.0,
        timeout=120,
    )
    raw_data = resp.json()
    log.info(f"Received {len(raw_data)} raw trade records")

    records = []
    for t in raw_data:
        ticker = (t.get("Ticker") or "").upper().strip()
        if not ticker or not ticker.isalpha() or len(ticker) > 5:
            continue

        tx_type = (t.get("Transaction") or "").lower()
        if "purchase" in tx_type or "buy" in tx_type:
            trade_type = "buy"
        elif "sale" in tx_type or "sell" in tx_type:
            trade_type = "sell"
        elif "exchange" in tx_type:
            trade_type = "exchange"
        else:
            continue

        lo, hi = _parse_amount(t.get("Amount", ""))

        records.append({
            "politician_id": (t.get("Representative") or "").strip(),
            "ticker": ticker,
            "company_name": t.get("Company", ""),
            "trade_type": trade_type,
            "trade_date": t.get("TransactionDate"),
            "disclosure_date": t.get("DisclosureDate"),
            "amount_lower": lo,
            "amount_upper": hi,
            "amount_midpoint": (lo + hi) // 2,
            "asset_type": t.get("AssetType", "stock"),
            "industry_sector": TICKER_SECTOR_MAP.get(ticker),
            "source_url": t.get("Source", ""),
        })

    df = pd.DataFrame(records)

    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df["disclosure_date"] = pd.to_datetime(df["disclosure_date"], errors="coerce")
        df["disclosure_lag_days"] = (
            df["disclosure_date"] - df["trade_date"]
        ).dt.days

        # Filter to 2022+ and valid dates
        df = df.dropna(subset=["trade_date", "disclosure_date"])
        df = df[df["trade_date"] >= "2022-01-01"]
        df = df[df["disclosure_lag_days"].between(0, 365)]

        # Deduplicate
        df = df.drop_duplicates(
            subset=["politician_id", "ticker", "trade_date", "trade_type"]
        )

    out_path = DATA_RAW / "congressional_trades_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} cleaned trades to {out_path}")
    return df


if __name__ == "__main__":
    collect_trades()
