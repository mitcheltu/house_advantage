"""
OpenFIGI API v3 Resolver — CUSIP-to-Ticker Mapping

Batch-resolves CUSIP identifiers (from SEC 13-F data) to ticker symbols.
API: https://api.openfigi.com/v3/mapping
Auth: Optional X-OPENFIGI-APIKEY header (higher rate limits with key)
Rate: 5 req/min without key, 20 req/min with key | 100 CUSIPs per batch
"""
import logging
import time
import json
import pandas as pd
from pathlib import Path

from .utils import get_env, DATA_RAW

log = logging.getLogger("collector.openfigi")

FIGI_URL = "https://api.openfigi.com/v3/mapping"


def _build_headers() -> dict:
    """Build request headers, optionally including API key."""
    headers = {"Content-Type": "application/json"}
    try:
        api_key = get_env("OPENFIGI_API_KEY")
        if api_key and api_key != "your_openfigi_api_key_here":
            headers["X-OPENFIGI-APIKEY"] = api_key
    except SystemExit:
        pass  # Key is optional
    return headers


def resolve_cusips(cusips: list[str], batch_size: int = 100) -> dict[str, dict]:
    """
    Resolve a list of CUSIPs to ticker symbols via OpenFIGI v3.

    Args:
        cusips: List of 9-character CUSIP strings
        batch_size: Max 100 per API call

    Returns:
        Dict mapping CUSIP → {ticker, name, marketSector, exchCode, figi}
    """
    import requests

    headers = _build_headers()
    has_key = "X-OPENFIGI-APIKEY" in headers
    delay = 3.2 if not has_key else 3.2  # Conservative rate limit

    # Deduplicate & clean
    cusips = list({c.strip()[:9] for c in cusips if c and len(c.strip()) >= 6})
    log.info(f"Resolving {len(cusips)} unique CUSIPs via OpenFIGI v3...")

    results = {}
    for i in range(0, len(cusips), batch_size):
        batch = cusips[i:i + batch_size]
        payload = [
            {"idType": "ID_CUSIP", "idValue": cusip, "exchCode": "US"}
            for cusip in batch
        ]

        try:
            resp = requests.post(FIGI_URL, headers=headers, json=payload, timeout=30)

            if resp.status_code == 429:
                log.warning("Rate limited by OpenFIGI. Waiting 60s...")
                time.sleep(60)
                resp = requests.post(FIGI_URL, headers=headers, json=payload, timeout=30)

            if resp.status_code != 200:
                log.error(f"OpenFIGI returned {resp.status_code}: {resp.text[:200]}")
                time.sleep(delay)
                continue

            data = resp.json()
            for cusip, result in zip(batch, data):
                if "data" in result and result["data"]:
                    best = result["data"][0]
                    results[cusip] = {
                        "ticker": best.get("ticker"),
                        "name": best.get("name"),
                        "market_sector": best.get("marketSector"),
                        "exchange": best.get("exchCode"),
                        "figi": best.get("figi"),
                    }

        except Exception as e:
            log.error(f"OpenFIGI batch error: {e}")

        time.sleep(delay)
        if (i // batch_size + 1) % 10 == 0:
            log.info(f"  Resolved {i + len(batch)}/{len(cusips)} CUSIPs")

    log.info(f"Successfully resolved {len(results)}/{len(cusips)} CUSIPs")
    return results


def build_cusip_ticker_map() -> pd.DataFrame:
    """
    Read all 13-F holdings files, extract unique CUSIPs, resolve to tickers.
    Saves: data/raw/cusip_ticker_map.csv
    """
    thirteenf_dir = DATA_RAW / "13f"
    if not thirteenf_dir.exists():
        log.warning("No 13f directory found. Run SEC 13-F collector first.")
        return pd.DataFrame()

    # Gather all unique CUSIPs from holdings files
    all_cusips = set()
    for csv_file in thirteenf_dir.glob("*_holdings.csv"):
        try:
            df = pd.read_csv(csv_file, dtype=str)
            if "cusip" in df.columns:
                cusips = df["cusip"].dropna().str.strip().str[:9]
                all_cusips.update(cusips[cusips.str.len() >= 6])
        except Exception as e:
            log.warning(f"Error reading {csv_file}: {e}")

    if not all_cusips:
        log.warning("No CUSIPs found in 13-F data")
        return pd.DataFrame()

    log.info(f"Found {len(all_cusips)} unique CUSIPs across 13-F files")

    # Check for existing cache
    cache_path = DATA_RAW / "cusip_ticker_map.csv"
    existing_map = {}
    if cache_path.exists():
        cached = pd.read_csv(cache_path, dtype=str)
        existing_map = dict(zip(cached["cusip"], cached.to_dict("records")))
        already_resolved = all_cusips & set(existing_map.keys())
        all_cusips -= already_resolved
        log.info(f"Found {len(already_resolved)} cached mappings, {len(all_cusips)} new to resolve")

    if all_cusips:
        new_mappings = resolve_cusips(list(all_cusips))
    else:
        new_mappings = {}

    # Merge cached + new
    all_resolved = []
    for cusip, info in {**existing_map, **{k: v for k, v in new_mappings.items()}}.items():
        if isinstance(info, dict):
            all_resolved.append({"cusip": cusip, **info})

    result_df = pd.DataFrame(all_resolved)
    result_df.to_csv(cache_path, index=False)
    log.info(f"Saved {len(result_df)} CUSIP→ticker mappings to {cache_path}")
    return result_df


if __name__ == "__main__":
    build_cusip_ticker_map()
