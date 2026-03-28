"""
OpenFEC API Collector — Campaign Finance Data

Downloads candidate filings, top donors, and PAC contributions.
API: https://api.open.fec.gov/v1
Auth: ?api_key= query param
Rate limit: 1000 requests/hour
Key: https://api.data.gov/signup
"""
import logging
import pandas as pd
from .utils import get_env, rate_limited_get, DATA_RAW

log = logging.getLogger("collector.openfec")

BASE_URL = "https://api.open.fec.gov/v1"


def _fec_get(endpoint: str, params: dict | None = None) -> dict:
    """Make authenticated GET to OpenFEC."""
    api_key = get_env("FEC_API_KEY")
    url = f"{BASE_URL}{endpoint}"
    p = params or {}
    p["api_key"] = api_key
    p.setdefault("per_page", 100)
    resp = rate_limited_get(url, params=p, delay=3.6, timeout=60)
    return resp.json()


def _paginate_fec(endpoint: str, params: dict | None = None, max_pages: int = 50) -> list:
    """
    Paginate OpenFEC results using last_index cursor.
    Returns list of all result rows.
    """
    params = params or {}
    all_results = []
    for page in range(1, max_pages + 1):
        data = _fec_get(endpoint, params)
        results = data.get("results", [])
        all_results.extend(results)

        pagination = data.get("pagination", {})
        last_indexes = pagination.get("last_indexes", {})
        if not last_indexes or not results:
            break

        # OpenFEC uses cursor-based pagination
        for key, val in last_indexes.items():
            params[key] = val

        log.info(f"  FEC {endpoint} page {page}: {len(results)} results")

    return all_results


def collect_candidates(election_year: int = 2024) -> pd.DataFrame:
    """
    Get FEC candidate records for House & Senate.
    Outputs: data/raw/fec_candidates_raw.csv
    """
    log.info(f"Collecting FEC candidates for {election_year}...")

    records = []
    for office in ["H", "S"]:
        params = {
            "election_year": election_year,
            "office": office,
            "is_active_candidate": True,
            "sort": "name",
        }
        results = _paginate_fec("/candidates/search/", params)
        for c in results:
            records.append({
                "candidate_id": c.get("candidate_id"),
                "name": c.get("name"),
                "party": c.get("party_full"),
                "state": c.get("state"),
                "district": c.get("district"),
                "office": "House" if office == "H" else "Senate",
                "incumbent_challenge": c.get("incumbent_challenge_full"),
                "election_year": election_year,
                "principal_committee_id": (c.get("principal_committees") or [{}])[0].get("committee_id")
                if c.get("principal_committees") else None,
            })

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "fec_candidates_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} FEC candidates to {out_path}")
    return df


def collect_candidate_totals(candidate_ids: list[str] | None = None,
                              election_year: int = 2024) -> pd.DataFrame:
    """
    Financial summary per candidate: receipts, disbursements, cash on hand.
    Outputs: data/raw/fec_candidate_totals_raw.csv
    """
    if candidate_ids is None:
        cand_path = DATA_RAW / "fec_candidates_raw.csv"
        if cand_path.exists():
            cand_df = pd.read_csv(cand_path)
            candidate_ids = cand_df["candidate_id"].dropna().tolist()
        else:
            log.warning("No candidate file found. Run collect_candidates first.")
            return pd.DataFrame()

    log.info(f"Collecting financial totals for {len(candidate_ids)} candidates...")

    records = []
    # Process in batches of 10 (FEC allows multi-id queries)
    for i in range(0, len(candidate_ids), 10):
        batch = candidate_ids[i:i + 10]
        params = {
            "election_year": election_year,
            "candidate_id": batch,
        }
        results = _paginate_fec("/candidates/totals/", params, max_pages=5)
        for r in results:
            records.append({
                "candidate_id": r.get("candidate_id"),
                "name": r.get("name"),
                "party": r.get("party_full"),
                "total_receipts": r.get("receipts"),
                "total_disbursements": r.get("disbursements"),
                "cash_on_hand": r.get("cash_on_hand_end_period"),
                "total_individual_contributions": r.get("individual_contributions"),
                "total_pac_contributions": r.get("other_political_committee_contributions"),
                "election_year": election_year,
            })

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "fec_candidate_totals_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} candidate finance summaries to {out_path}")
    return df


def collect_top_donors(committee_id: str, limit: int = 200) -> list[dict]:
    """
    Get top individual contributors to a given committee.
    """
    params = {
        "sort": "-total",
        "per_page": min(limit, 100),
    }
    results = _paginate_fec(f"/schedules/schedule_a/by_contributor/", {
        **params, "committee_id": committee_id
    }, max_pages=max(1, limit // 100))
    return results[:limit]


def collect_pac_contributions(election_year: int = 2024) -> pd.DataFrame:
    """
    Get PAC-to-candidate contributions (Schedule B).
    Outputs: data/raw/fec_pac_contributions_raw.csv
    """
    log.info(f"Collecting PAC contributions for {election_year}...")

    params = {
        "two_year_transaction_period": election_year,
        "sort": "-contribution_receipt_amount",
        "per_page": 100,
    }
    results = _paginate_fec("/schedules/schedule_a/", params, max_pages=100)

    records = []
    for r in results:
        records.append({
            "contributor_name": r.get("contributor_name"),
            "contributor_type": r.get("contributor_type"),
            "contributor_employer": r.get("contributor_employer"),
            "contributor_occupation": r.get("contributor_occupation"),
            "committee_id": r.get("committee_id"),
            "committee_name": r.get("committee", {}).get("name") if r.get("committee") else None,
            "candidate_id": r.get("candidate_id"),
            "amount": r.get("contribution_receipt_amount"),
            "receipt_date": r.get("contribution_receipt_date"),
            "state": r.get("contributor_state"),
        })

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "fec_pac_contributions_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} PAC contributions to {out_path}")
    return df


def collect_all(election_year: int = 2024):
    """Run full FEC collection pipeline."""
    cand_df = collect_candidates(election_year)
    collect_candidate_totals(election_year=election_year)
    collect_pac_contributions(election_year)
    return cand_df


if __name__ == "__main__":
    collect_all()
