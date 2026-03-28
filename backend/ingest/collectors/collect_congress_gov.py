"""
Congress.gov API Collector — Politicians, Committees, Votes, Bills

Replaces the discontinued ProPublica Congress API.
API Docs: https://api.congress.gov/
Auth: api_key query parameter
Rate Limit: 5,000 requests/hour
"""
import logging
import pandas as pd
from .utils import get_env, rate_limited_get, DATA_RAW

log = logging.getLogger("collector.congress_gov")

BASE_URL = "https://api.congress.gov/v3"
CURRENT_CONGRESS = 119  # 2025–2027


def _params(**extra) -> dict:
    """Build query params with API key included."""
    p = {"api_key": get_env("CONGRESS_GOV_API_KEY"), "format": "json"}
    p.update(extra)
    return p


def _paginate(url: str, params: dict, result_key: str,
              max_pages: int = 100) -> list[dict]:
    """
    Follow Congress.gov pagination.
    The API returns a 'pagination' object with 'next' URL when more pages exist.
    """
    all_items = []
    current_url = url
    current_params = params.copy()

    for page in range(max_pages):
        resp = rate_limited_get(current_url, params=current_params, delay=1.5, max_retries=5)
        data = resp.json()

        items = data.get(result_key, [])
        if not items:
            break
        all_items.extend(items)

        pagination = data.get("pagination", {})
        next_url = pagination.get("next")
        if not next_url:
            break

        # Next URL does NOT include api_key, so carry it forward
        current_url = next_url
        current_params = {"api_key": params["api_key"], "format": "json"}

        log.info(f"  Page {page + 2}: {len(all_items)} items so far...")

    return all_items


# ── Politicians ───────────────────────────────────────────────

def collect_politicians() -> pd.DataFrame:
    """
    Collect all members of the current Congress (both chambers).
    Saves to data/raw/politicians_raw.csv
    """
    log.info(f"Collecting members of {CURRENT_CONGRESS}th Congress...")

    members = _paginate(
        f"{BASE_URL}/member/congress/{CURRENT_CONGRESS}",
        _params(limit=250),
        result_key="members",
    )

    records = []
    for m in members:
        # Fetch detail for each member to get full info
        bioguide_id = m.get("bioguideId", "")
        if not bioguide_id:
            continue

        terms = m.get("terms", {}).get("item", [])
        # Get the most recent term
        latest_term = terms[-1] if terms else {}
        chamber = latest_term.get("chamber", "").lower()
        if chamber == "house of representatives":
            chamber = "house"
        elif chamber == "senate":
            chamber = "senate"

        party_name = m.get("partyName", "")
        if "Republican" in party_name:
            party = "R"
        elif "Democrat" in party_name:
            party = "D"
        else:
            party = "I"

        records.append({
            "id": bioguide_id,
            "full_name": m.get("name", ""),
            "party": party,
            "chamber": chamber,
            "state": m.get("state", ""),
            "district": latest_term.get("district"),
            "photo_url": m.get("depiction", {}).get("imageUrl", ""),
            "in_office": True,
        })

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "politicians_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} politicians to {out_path}")
    return df


# ── Committees ────────────────────────────────────────────────

# Maps Congress.gov policyArea.name → model's 7 industry sectors
POLICY_AREA_SECTOR_MAP = {
    "Armed Forces and National Security": "defense",
    "Defense": "defense",
    "Emergency Management": "defense",
    "Immigration": "defense",
    "Crime and Law Enforcement": "defense",
    "Economics and Public Finance": "finance",
    "Finance and Financial Sector": "finance",
    "Taxation": "finance",
    "Housing and Community Development": "finance",
    "Foreign Trade and International Finance": "finance",
    "Health": "healthcare",
    "Social Welfare": "healthcare",
    "Energy": "energy",
    "Environmental Protection": "energy",
    "Public Lands and Natural Resources": "energy",
    "Water Resources Development": "energy",
    "Science, Technology, Communications": "tech",
    "Government Operations and Politics": "tech",
    "Commerce": "agriculture",
    "Agriculture and Food": "agriculture",
    "Animals": "agriculture",
    "Transportation and Public Works": "defense",
    "Education": "healthcare",
    "Labor and Employment": "agriculture",
    "International Affairs": "defense",
    "Native Americans": "agriculture",
    "Sports and Recreation": "telecom",
    "Arts, Culture, Religion": "telecom",
    "Civil Rights and Liberties, Minority Issues": "healthcare",
    "Families": "healthcare",
    "Congress": "finance",
    "Law": "finance",
}


def _policy_area_to_sector(policy_area: str | None) -> str | None:
    """Map a Congress.gov policyArea name to a model sector."""
    if not policy_area:
        return None
    return POLICY_AREA_SECTOR_MAP.get(policy_area)


# Maps committee names to industry sectors for sector_overlap feature
COMMITTEE_SECTOR_MAP = {
    "Armed Services": "defense",
    "Defense": "defense",
    "Veterans' Affairs": "defense",
    "Banking": "finance",
    "Financial Services": "finance",
    "Finance": "finance",
    "Health": "healthcare",
    "Energy and Commerce": "energy",
    "Energy and Natural Resources": "energy",
    "Environment and Public Works": "energy",
    "Natural Resources": "energy",
    "Science, Space, and Technology": "tech",
    "Commerce, Science, and Transportation": "tech",
    "Agriculture": "agriculture",
    "Nutrition": "agriculture",
}


def _guess_sector(committee_name: str) -> str | None:
    """Map a committee name to an industry sector."""
    name_lower = committee_name.lower()
    for keyword, sector in COMMITTEE_SECTOR_MAP.items():
        if keyword.lower() in name_lower:
            return sector
    return None


def collect_committees() -> pd.DataFrame:
    """
    Collect all committees for the current Congress.
    Saves to data/raw/committees_raw.csv

    Note: Committee *memberships* are collected separately in step 2
    from the unitedstates/congress-legislators GitHub repo.
    """
    log.info(f"Collecting committees for {CURRENT_CONGRESS}th Congress...")

    committees_data = _paginate(
        f"{BASE_URL}/committee/{CURRENT_CONGRESS}",
        _params(limit=250),
        result_key="committees",
    )

    committee_records = []

    for c in committees_data:
        code = c.get("systemCode", "")
        name = c.get("name", "")
        chamber = c.get("chamber", "").lower()
        if chamber == "house of representatives":
            chamber = "house"
        elif chamber not in ("senate", "joint"):
            chamber = "joint"

        committee_records.append({
            "id": code,
            "name": name,
            "chamber": chamber,
            "industry_sector": _guess_sector(name),
        })

    committees_df = pd.DataFrame(committee_records)
    committees_df.to_csv(DATA_RAW / "committees_raw.csv", index=False)
    log.info(f"Saved {len(committees_df)} committees")
    return committees_df


# ── Votes ─────────────────────────────────────────────────────

def collect_votes(congress: int = CURRENT_CONGRESS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Collect floor votes and individual member positions.
    Saves to data/raw/votes_raw.csv and data/raw/politician_votes_raw.csv

    Note: Congress.gov API only provides house-vote endpoint.
    There is no senate-vote endpoint.
    """
    vote_records = []
    position_records = []

    # Congress.gov API only has /house-vote — no /senate-vote endpoint exists
    log.info(f"Collecting house votes for {congress}th Congress...")

    votes = _paginate(
        f"{BASE_URL}/house-vote/{congress}",
        _params(limit=250),
        result_key="houseRollCallVotes",
    )

    for v in votes:
        vote_url = v.get("url", "")
        vote_number = v.get("rollCallNumber", "")
        vote_date = v.get("startDate", "")
        question = v.get("voteQuestion", "")
        result = v.get("result", "")
        leg_type = v.get("legislationType", "")
        leg_num = v.get("legislationNumber", "")
        bill_id = f"{leg_type}{leg_num}-{congress}" if leg_type and leg_num else ""

        vote_records.append({
            "id": f"house-{congress}-{vote_number}",
            "bill_id": bill_id,
            "vote_date": vote_date,
            "chamber": "house",
            "vote_question": question,
            "description": result,
            "related_sector": None,  # filled during feature engineering
        })

        # Get individual member positions from vote detail /members sub-endpoint
        if vote_url:
            try:
                members_url = f"{vote_url}/members"
                detail_resp = rate_limited_get(
                    members_url,
                    params=_params(),
                    delay=1.5,
                    max_retries=5,
                )
                vote_member_data = detail_resp.json().get("houseRollCallVoteMemberVotes", {})
                members_data = vote_member_data.get("results", [])

                for pos in members_data:
                    member_id = pos.get("bioguideID", "")
                    vote_cast = pos.get("voteCast", "").lower()

                    position_map = {
                        "yea": "yes", "yes": "yes", "aye": "yes",
                        "nay": "no", "no": "no",
                        "not voting": "not_voting",
                        "present": "abstain",
                    }
                    mapped = position_map.get(vote_cast, "not_voting")

                    if member_id:
                        position_records.append({
                            "politician_id": member_id,
                            "vote_id": f"house-{congress}-{vote_number}",
                            "position": mapped,
                        })
            except Exception as e:
                log.warning(f"  Could not fetch positions for vote "
                            f"{vote_number}: {e}")

    votes_df = pd.DataFrame(vote_records)
    positions_df = pd.DataFrame(position_records)

    votes_df.to_csv(DATA_RAW / "votes_raw.csv", index=False)
    positions_df.to_csv(DATA_RAW / "politician_votes_raw.csv", index=False)

    log.info(f"Saved {len(votes_df)} votes, {len(positions_df)} positions")
    return votes_df, positions_df


# ── Bills ─────────────────────────────────────────────────────

def collect_bills(congress: int = CURRENT_CONGRESS,
                   fetch_policy_areas: bool = True) -> pd.DataFrame:
    """
    Collect bills for the current Congress.
    Saves to data/raw/bills_raw.csv

    If fetch_policy_areas=True, fetches bill detail for each bill to capture
    policyArea (needed for vote sector mapping). This is slower (~1.5s/bill).
    """
    log.info(f"Collecting bills for {congress}th Congress...")

    records = []
    for bill_type in ["hr", "s", "hjres", "sjres"]:
        log.info(f"  Fetching {bill_type} bills...")
        bills = _paginate(
            f"{BASE_URL}/bill/{congress}/{bill_type}",
            _params(limit=250),
            result_key="bills",
        )

        for b in bills:
            bill_number = b.get("number", "")
            policy_area = None
            latest_action = None
            latest_action_date = None
            origin_chamber = None
            sponsor_bioguide = None
            legislation_url = None
            introduced_date = b.get("introducedDate", "")

            # Fetch bill detail for all enrichment fields
            if fetch_policy_areas and bill_number:
                try:
                    detail_resp = rate_limited_get(
                        f"{BASE_URL}/bill/{congress}/{bill_type}/{bill_number}",
                        params=_params(),
                        delay=1.5,
                        max_retries=3,
                    )
                    bill_detail = detail_resp.json().get("bill", {})
                    policy_area = bill_detail.get("policyArea", {}).get("name")
                    latest_action_obj = bill_detail.get("latestAction", {})
                    latest_action = latest_action_obj.get("text")
                    latest_action_date = latest_action_obj.get("actionDate")
                    origin_chamber = bill_detail.get("originChamber")
                    sponsors = bill_detail.get("sponsors", [])
                    if sponsors:
                        sponsor_bioguide = sponsors[0].get("bioguideId")
                    legislation_url = bill_detail.get("legislationUrl")
                    if not introduced_date:
                        introduced_date = bill_detail.get("introducedDate", "")
                except Exception as e:
                    log.debug(f"    Could not fetch detail for {bill_type}{bill_number}: {e}")

            records.append({
                "id": f"{bill_type}{bill_number}-{congress}",
                "congress": congress,
                "bill_number": f"{bill_type.upper()}{bill_number}",
                "title": b.get("title", ""),
                "introduced_date": introduced_date,
                "policy_area": policy_area,
                "related_sector": _policy_area_to_sector(policy_area),
                "latest_action": latest_action,
                "latest_action_date": latest_action_date,
                "origin_chamber": origin_chamber,
                "sponsor_bioguide": sponsor_bioguide,
                "url": legislation_url,
            })

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "bills_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} bills to {out_path}")
    policy_count = df["policy_area"].notna().sum()
    log.info(f"  {policy_count}/{len(df)} bills have policyArea tags")
    return df


def enrich_bills_policy_area(congress: int = CURRENT_CONGRESS) -> pd.DataFrame:
    """
    Backfill policyArea on existing bills_raw.csv by fetching bill detail
    only for rows missing policy_area. Much faster than re-collecting all bills.
    """
    csv_path = DATA_RAW / "bills_raw.csv"
    if not csv_path.exists():
        log.warning("bills_raw.csv not found — run collect_bills first")
        return pd.DataFrame()

    df = pd.read_csv(csv_path)
    missing = df["policy_area"].isna() if "policy_area" in df.columns else pd.Series([True] * len(df))
    to_fetch = df[missing]
    log.info(f"Enriching {len(to_fetch)}/{len(df)} bills missing policyArea...")

    enriched = 0
    for idx, row in to_fetch.iterrows():
        bill_id = str(row.get("id", ""))
        # Parse bill_type and number from id like "hr123-119"
        parts = bill_id.rsplit("-", 1)
        if len(parts) != 2:
            continue
        type_num = parts[0]
        import re as _re
        m = _re.match(r"([a-z]+)(\d+)", type_num)
        if not m:
            continue
        bill_type, bill_number = m.group(1), m.group(2)
        try:
            detail_resp = rate_limited_get(
                f"{BASE_URL}/bill/{congress}/{bill_type}/{bill_number}",
                params=_params(),
                delay=1.5,
                max_retries=3,
            )
            bill_detail = detail_resp.json().get("bill", {})
            pa = bill_detail.get("policyArea", {}).get("name")
            if pa:
                df.at[idx, "policy_area"] = pa
                df.at[idx, "related_sector"] = _policy_area_to_sector(pa)
                enriched += 1
        except Exception as e:
            log.debug(f"  Could not fetch detail for {bill_type}{bill_number}: {e}")

    df.to_csv(csv_path, index=False)
    log.info(f"Enriched {enriched} bills with policyArea")
    return df


def enrich_votes_with_sectors() -> pd.DataFrame:
    """
    Propagate bill policyArea sectors to votes via bill_id linkage.
    Updates votes_raw.csv with related_sector populated from bills_raw.csv.
    """
    votes_path = DATA_RAW / "votes_raw.csv"
    bills_path = DATA_RAW / "bills_raw.csv"

    if not votes_path.exists() or not bills_path.exists():
        log.warning("votes_raw.csv or bills_raw.csv not found — skipping")
        return pd.DataFrame()

    votes_df = pd.read_csv(votes_path)
    bills_df = pd.read_csv(bills_path)

    # Build bill_id → related_sector map
    if "related_sector" not in bills_df.columns:
        log.warning("bills_raw.csv has no related_sector — run enrich_bills_policy_area first")
        return votes_df

    bill_sector = bills_df.set_index(bills_df["id"].str.lower())["related_sector"].dropna().to_dict()
    before_count = votes_df["related_sector"].notna().sum() if "related_sector" in votes_df.columns else 0

    # Normalize vote bill_id to lowercase for matching
    votes_df["related_sector"] = votes_df["bill_id"].str.lower().map(bill_sector)

    after_count = votes_df["related_sector"].notna().sum()
    votes_df.to_csv(votes_path, index=False)
    log.info(f"Vote sectors: {before_count} → {after_count} / {len(votes_df)} populated")
    return votes_df


# ── Main ──────────────────────────────────────────────────────

def collect_all():
    """
    Run Congress.gov collectors: politicians, committees, bills.

    Committee memberships and votes are handled by separate steps:
      - Step 2: Committee memberships from unitedstates/congress-legislators
      - Step 3: Senate votes from senate.gov XML
    """
    log.info("=" * 60)
    log.info("Starting Congress.gov data collection")
    log.info("=" * 60)

    politicians = collect_politicians()
    committees = collect_committees()
    bills = collect_bills()

    log.info("=" * 60)
    log.info("Congress.gov collection complete!")
    log.info(f"  Politicians:  {len(politicians)}")
    log.info(f"  Committees:   {len(committees)}")
    log.info(f"  Bills:        {len(bills)}")
    log.info("=" * 60)


if __name__ == "__main__":
    collect_all()
