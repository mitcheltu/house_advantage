"""
Committee Membership Collector — unitedstates/congress-legislators

Downloads current committee membership data from the public-domain
unitedstates/congress-legislators GitHub repo (CC0 license).

Source: https://github.com/unitedstates/congress-legislators
Data:   committee-membership-current.csv on gh-pages branch

CSV columns: bioguide, name, committee_id, committee_type,
             committee_name, committee_subcommittee_name,
             party, title, rank, chamber
"""
import logging
import pandas as pd
from .utils import DATA_RAW

log = logging.getLogger("collector.committee_memberships")

MEMBERSHIP_CSV_URL = (
    "https://raw.githubusercontent.com/unitedstates/"
    "congress-legislators/gh-pages/committee-membership-current.csv"
)


def collect_committee_memberships() -> pd.DataFrame:
    """
    Download current committee memberships from the
    unitedstates/congress-legislators repo and save to CSV.
    """
    log.info("Downloading committee memberships from congress-legislators repo...")
    df = pd.read_csv(MEMBERSHIP_CSV_URL)
    log.info(f"  Downloaded {len(df)} membership records")

    # Map title to a normalised role
    def _normalise_role(title: str | None) -> str:
        if not isinstance(title, str):
            return "member"
        t = title.lower()
        if "chairman" in t or "chair" in t and "vice" not in t:
            return "chair"
        if "ranking" in t:
            return "ranking_member"
        if "vice" in t:
            return "vice_chair"
        if "ex officio" in t:
            return "ex_officio"
        return "member"

    records = []
    for _, row in df.iterrows():
        bioguide = row.get("bioguide", "")
        if not bioguide:
            continue
        records.append({
            "politician_id": bioguide,
            "committee_id": row.get("committee_id", ""),
            "committee_name": row.get("committee_name", ""),
            "subcommittee_name": row.get("committee_subcommittee_name", ""),
            "role": _normalise_role(row.get("title")),
            "party": row.get("party", ""),
            "rank": row.get("rank", ""),
            "chamber": row.get("committee_type", ""),
        })

    out_df = pd.DataFrame(records)
    out_path = DATA_RAW / "committee_memberships_raw.csv"
    out_df.to_csv(out_path, index=False)
    log.info(f"Saved {len(out_df)} memberships to {out_path}")
    return out_df


if __name__ == "__main__":
    collect_committee_memberships()
