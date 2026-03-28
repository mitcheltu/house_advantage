"""
Merge House + Senate Trades into Unified Congressional Trades CSV

Combines data/raw/house_trades_raw.csv and data/raw/senate_trades_raw.csv
into data/raw/congressional_trades_raw.csv — same schema the rest of the
pipeline expects.
"""
import json
import logging
import pandas as pd
from .utils import DATA_RAW

log = logging.getLogger("collector.merge_trades")

# Load expanded 641-ticker sector map from JSON (built via yfinance + manual curation)
_SECTOR_MAP_PATH = DATA_RAW / "_combined_sector_map.json"
if _SECTOR_MAP_PATH.exists():
    with open(_SECTOR_MAP_PATH) as _f:
        TICKER_SECTOR_MAP: dict[str, str] = json.load(_f)
    log.info(f"Loaded {len(TICKER_SECTOR_MAP)} ticker→sector mappings")
else:
    TICKER_SECTOR_MAP = {}
    log.warning("_combined_sector_map.json not found — sector tagging will be empty")

# Artifact tickers from disclosure parsing: bonds, crypto, hedge funds, etc.
# These are extraction artifacts (type codes), not real equity tickers.
_ARTIFACT_TICKERS = {"CS", "OT", "ST", "HN", "PS", "CT", "OI"}


def merge_trades() -> pd.DataFrame:
    """
    Merge House and Senate trade CSVs into unified congressional_trades_raw.csv.
    Output columns match the schema the rest of the pipeline expects:
      politician_id, ticker, company_name, trade_type, trade_date,
      disclosure_date, disclosure_lag_days, amount_lower, amount_upper,
      amount_midpoint, asset_type, industry_sector, source_url
    """
    dfs = []

    house_path = DATA_RAW / "house_trades_raw.csv"
    if house_path.exists():
        house = pd.read_csv(house_path)
        log.info(f"Loaded {len(house)} House trades")
        dfs.append(house)
    else:
        log.warning("No House trades file found")

    senate_path = DATA_RAW / "senate_trades_raw.csv"
    if senate_path.exists():
        senate = pd.read_csv(senate_path)
        log.info(f"Loaded {len(senate)} Senate trades")
        dfs.append(senate)
    else:
        log.warning("No Senate trades file found")

    if not dfs:
        log.error("No trade data found. Run House and/or Senate collectors first.")
        return pd.DataFrame()

    merged = pd.concat(dfs, ignore_index=True)

    # Drop extraction artifact tickers (bonds, crypto, hedge funds, etc.)
    before = len(merged)
    merged = merged[~merged["ticker"].str.upper().isin(_ARTIFACT_TICKERS)]
    dropped = before - len(merged)
    if dropped:
        log.info(f"Dropped {dropped} non-equity artifact rows (CS/OT/ST/HN/PS/CT/OI)")

    # Standardize to the schema expected downstream
    merged["politician_id"] = merged.get("politician_name", merged.get("full_name", ""))
    merged["industry_sector"] = merged["ticker"].map(TICKER_SECTOR_MAP).apply(
        lambda v: json.dumps(v) if isinstance(v, list) else v
    )
    merged["source_url"] = merged.get("doc_id", "").apply(
        lambda x: f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{x}.pdf"
        if x else ""
    )

    # Keep only the columns the pipeline expects
    output_cols = [
        "politician_id", "ticker", "company_name", "trade_type",
        "trade_date", "disclosure_date", "disclosure_lag_days",
        "amount_lower", "amount_upper", "amount_midpoint",
        "asset_type", "industry_sector", "source_url",
        # Extra columns for richer data
        "chamber", "first_name", "last_name", "source",
    ]
    for col in output_cols:
        if col not in merged.columns:
            merged[col] = None

    merged = merged[output_cols]

    # Deduplicate across chambers
    merged = merged.drop_duplicates(
        subset=["politician_id", "ticker", "trade_date", "trade_type"]
    )

    out_path = DATA_RAW / "congressional_trades_raw.csv"
    merged.to_csv(out_path, index=False)
    log.info(f"Saved {len(merged)} unified trades to {out_path}")
    return merged


if __name__ == "__main__":
    merge_trades()
