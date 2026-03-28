"""
Targeted bill enrichment for severe/systemic trades.

Strategy:
  Phase 1: Re-paginate the list endpoint (fast, ~50 pages of 250)
           to get latestAction + originChamber for ALL bills (free fields).
  Phase 2: Fetch detail only for bills that already have policy_area
           (the ~205 that can be matched to trade sectors) to get
           sponsor_bioguide + legislationUrl.
  Phase 3: Write updated CSV and load into MySQL.
"""
import sys, os, logging, time
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from backend.ingest.collectors.utils import rate_limited_get, DATA_RAW
from backend.ingest.collectors.collect_congress_gov import (
    BASE_URL, CURRENT_CONGRESS, _params, _paginate, _policy_area_to_sector,
)
from backend.db.connection import get_engine
from backend.db.setup_db import load_bills

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("enrich_bills")

# ── Phase 1: Re-paginate list endpoint for free fields ────────

def phase1_list_all_bills(congress: int = CURRENT_CONGRESS) -> dict:
    """
    Paginate the list endpoint for all bill types.
    Returns a dict keyed by bill_id -> {latestAction, originChamber, ...}
    """
    log.info("Phase 1: Paginating list endpoint for all bills...")
    lookup = {}

    for bill_type in ["hr", "s", "hjres", "sjres"]:
        log.info(f"  Fetching {bill_type} bills from list endpoint...")
        bills = _paginate(
            f"{BASE_URL}/bill/{congress}/{bill_type}",
            _params(limit=250),
            result_key="bills",
        )
        log.info(f"    Got {len(bills)} {bill_type} bills")

        for b in bills:
            number = b.get("number", "")
            bill_id = f"{bill_type}{number}-{congress}"
            latest_action_obj = b.get("latestAction") or {}

            lookup[bill_id] = {
                "latest_action": latest_action_obj.get("text"),
                "latest_action_date": latest_action_obj.get("actionDate"),
                "origin_chamber": b.get("originChamber"),
            }

    log.info(f"Phase 1 complete: {len(lookup)} bills in lookup")
    return lookup


# ── Phase 2: Fetch detail for bills with policy_area ─────────

def phase2_detail_for_matched_bills(df: pd.DataFrame,
                                     congress: int = CURRENT_CONGRESS) -> pd.DataFrame:
    """
    Fetch bill detail (sponsor, legislationUrl) only for rows that
    already have a policy_area (i.e., can be matched to trade sectors).
    """
    has_policy = df["policy_area"].notna() & (df["policy_area"] != "")
    to_fetch = df[has_policy].copy()
    log.info(f"Phase 2: Fetching detail for {len(to_fetch)} bills with policy_area...")

    for idx, row in to_fetch.iterrows():
        bill_id = str(row["id"])
        # Parse bill_type and number from id like "hr123-119"
        parts = bill_id.rsplit("-", 1)
        if len(parts) != 2:
            continue
        type_num = parts[0]
        # Split type from number: "hr123" -> ("hr", "123"), "hjres45" -> ("hjres", "45")
        for prefix in ("hjres", "sjres", "hr", "s"):
            if type_num.startswith(prefix):
                bill_type = prefix
                bill_number = type_num[len(prefix):]
                break
        else:
            continue

        try:
            detail_resp = rate_limited_get(
                f"{BASE_URL}/bill/{congress}/{bill_type}/{bill_number}",
                params=_params(),
                delay=1.5,
                max_retries=3,
            )
            detail = detail_resp.json().get("bill", {})
            sponsors = detail.get("sponsors", [])
            if sponsors:
                df.at[idx, "sponsor_bioguide"] = sponsors[0].get("bioguideId")
            legislation_url = detail.get("legislationUrl")
            if legislation_url:
                df.at[idx, "url"] = legislation_url
            # Also grab policyArea from detail in case it's more accurate
            pa = detail.get("policyArea", {}).get("name")
            if pa:
                df.at[idx, "policy_area"] = pa
        except Exception as e:
            log.warning(f"  Detail fetch failed for {bill_id}: {e}")

    fetched = df.loc[has_policy, "url"].notna().sum()
    log.info(f"Phase 2 complete: {fetched} bills now have URLs")
    return df


# ── Main ──────────────────────────────────────────────────────

def main():
    csv_path = DATA_RAW / "bills_raw.csv"
    log.info(f"Reading existing CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    log.info(f"  {len(df)} bills, columns: {list(df.columns)}")

    # Ensure new columns exist
    for col in ["latest_action", "latest_action_date", "origin_chamber",
                "sponsor_bioguide", "url"]:
        if col not in df.columns:
            df[col] = None

    # Phase 1: Merge list endpoint data
    lookup = phase1_list_all_bills()
    updated_list = 0
    for idx, row in df.iterrows():
        bill_id = row["id"]
        if bill_id in lookup:
            info = lookup[bill_id]
            df.at[idx, "latest_action"] = info["latest_action"]
            df.at[idx, "latest_action_date"] = info["latest_action_date"]
            df.at[idx, "origin_chamber"] = info["origin_chamber"]
            updated_list += 1
    log.info(f"Merged list data for {updated_list}/{len(df)} bills")

    # Phase 2: Fetch detail for bills with policy_area
    df = phase2_detail_for_matched_bills(df)

    # Add related_sector column from policy_area
    df["related_sector"] = df["policy_area"].apply(_policy_area_to_sector)

    # Save updated CSV
    out_cols = ["id", "congress", "bill_number", "title", "introduced_date",
                "policy_area", "related_sector", "latest_action",
                "latest_action_date", "origin_chamber", "sponsor_bioguide", "url"]
    # Keep only columns that exist
    out_cols = [c for c in out_cols if c in df.columns]
    df[out_cols].to_csv(csv_path, index=False)
    log.info(f"Saved {len(df)} bills to {csv_path}")

    # Print summary
    print("\n=== Enrichment Summary ===")
    for col in ["latest_action", "latest_action_date", "origin_chamber",
                "sponsor_bioguide", "url", "policy_area"]:
        if col in df.columns:
            count = df[col].notna().sum()
            print(f"  {col:25s}: {count:>6}/{len(df)} non-null")

    # Phase 3: Load into MySQL
    log.info("Phase 3: Loading into MySQL...")
    engine = get_engine()
    load_bills(engine)
    log.info("Done! Bills loaded into MySQL.")

    # Verify
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT COUNT(*) as total, "
            "SUM(url IS NOT NULL AND url != '') as has_url, "
            "SUM(latest_action IS NOT NULL AND latest_action != '') as has_action, "
            "SUM(origin_chamber IS NOT NULL AND origin_chamber != '') as has_chamber, "
            "SUM(sponsor_bioguide IS NOT NULL AND sponsor_bioguide != '') as has_sponsor, "
            "SUM(policy_area IS NOT NULL AND policy_area != '') as has_policy "
            "FROM bills"
        )).fetchone()
    print(f"\n=== MySQL Verification ===")
    print(f"  Total:          {result[0]}")
    print(f"  Has URL:        {result[1]}")
    print(f"  Has action:     {result[2]}")
    print(f"  Has chamber:    {result[3]}")
    print(f"  Has sponsor:    {result[4]}")
    print(f"  Has policy:     {result[5]}")


if __name__ == "__main__":
    main()
