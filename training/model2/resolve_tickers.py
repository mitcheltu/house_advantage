"""
Step 2b: Resolve CUSIPs from 13-F holdings to ticker symbols via OpenFIGI.

Reads all 13-F CSVs in backend/data/raw/13f/, collects unique CUSIPs,
resolves them to tickers, and saves the mapping.

Input:  backend/data/raw/13f/*_holdings.csv
Output: data/raw/cusip_ticker_map.csv

Requires OPENFIGI_API_KEY in .env (free at openfigi.com/api).
"""
import glob
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

OUT = ROOT / "data" / "raw" / "cusip_ticker_map.csv"


def resolve_cusips_to_tickers(cusips: list[str]) -> dict[str, str]:
    api_key = os.getenv("OPENFIGI_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    mapping = {}
    batch_size = 100
    total = len(cusips)

    for i in range(0, total, batch_size):
        batch = cusips[i : i + batch_size]
        payload = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]

        try:
            resp = requests.post(
                "https://api.openfigi.com/v3/mapping",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            for cusip, result in zip(batch, resp.json()):
                data = result.get("data", [])
                if data and data[0].get("ticker"):
                    mapping[cusip] = data[0]["ticker"]
        except Exception as e:
            print(f"[resolve_tickers] Batch {i // batch_size} failed: {e}")

        # Rate limit: with key → 25 req/6s; without → 5 req/min
        delay = 0.3 if api_key else 12.0
        time.sleep(delay)

        if (i // batch_size) % 10 == 0:
            print(f"[resolve_tickers] Progress: {min(i + batch_size, total)}/{total} "
                  f"({len(mapping)} resolved)")

    print(f"[resolve_tickers] Resolved {len(mapping)}/{total} CUSIPs to tickers.")
    return mapping


def main():
    # Collect all unique CUSIPs across all 13-F files
    all_cusips = set()
    for f in sorted(glob.glob(str(ROOT / "backend" / "data" / "raw" / "13f" / "*_holdings.csv"))):
        df = pd.read_csv(f, usecols=["cusip"], dtype=str)
        all_cusips.update(df["cusip"].dropna().unique())
    
    print(f"[resolve_tickers] Found {len(all_cusips)} unique CUSIPs across all 13-F files.")

    mapping = resolve_cusips_to_tickers(sorted(all_cusips))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(mapping.items()), columns=["cusip", "ticker"]).to_csv(OUT, index=False)
    print(f"[resolve_tickers] Saved {OUT}")


if __name__ == "__main__":
    main()
