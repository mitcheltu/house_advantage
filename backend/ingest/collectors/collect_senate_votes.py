"""
Senate Vote Collector — senate.gov XML roll-call data

Scrapes Senate roll-call vote XML files from the official senate.gov website.
No API key required — publicly available data.

URL pattern:
  https://www.senate.gov/legislative/LIS/roll_call_votes/
  vote{congress}{session}/vote_{congress}_{session}_{voteNumber:05d}.xml

XML structure per vote:
  <roll_call_vote>
    <congress>, <session>, <vote_number>, <vote_date>,
    <vote_question_text>, <vote_result_text>, <question>, <vote_title>,
    <members>
      <member>
        <member_full>, <last_name>, <first_name>,
        <party>, <state>, <vote_cast>, <lis_member_id>
      </member>
      ...
    </members>
  </roll_call_vote>
"""
import logging
import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from .utils import DATA_RAW

log = logging.getLogger("collector.senate_votes")

SENATE_VOTE_URL = (
    "https://www.senate.gov/legislative/LIS/roll_call_votes/"
    "vote{congress}{session}/vote_{congress}_{session}_{vote_num}.xml"
)

LEGISLATORS_CSV_URL = (
    "https://raw.githubusercontent.com/unitedstates/"
    "congress-legislators/gh-pages/legislators-current.csv"
)

# Current Congress — must match collect_congress_gov.py
CURRENT_CONGRESS = 119


def _build_lis_to_bioguide_map() -> dict[str, str]:
    """Download current legislators CSV and build LIS ID → bioguide ID map."""
    df = pd.read_csv(LEGISLATORS_CSV_URL)
    mapping = {}
    for _, row in df.iterrows():
        lis = row.get("lis_id", "")
        bioguide = row.get("bioguide_id", "")
        if pd.notna(lis) and pd.notna(bioguide) and lis and bioguide:
            mapping[str(lis).strip()] = str(bioguide).strip()
    return mapping


def _fetch_vote_xml(congress: int, session: int, vote_num: int,
                    max_retries: int = 3) -> ET.Element | None:
    """Fetch a single Senate vote XML. Returns None if the vote doesn't exist.
    Retries with exponential backoff on connection errors."""
    padded = str(vote_num).zfill(5)
    url = SENATE_VOTE_URL.format(
        congress=congress, session=session, vote_num=padded,
    )
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                return None
            # senate.gov returns HTML (not XML) for non-existent votes with 200
            if not resp.text.startswith("<?xml"):
                return None
            return ET.fromstring(resp.text)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            wait = 2 ** (attempt + 1)  # 2, 4, 8 seconds
            log.warning(f"  Connection error fetching vote {vote_num} "
                        f"(attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait}s: {e}")
            time.sleep(wait)
        except Exception as e:
            log.warning(f"  Error fetching vote {vote_num}: {e}")
            return None
    log.warning(f"  Failed to fetch vote {vote_num} after {max_retries} retries")
    return None


def _find_max_vote(congress: int, session: int) -> int:
    """Binary search for the highest vote number available."""
    lo, hi = 1, 1000
    # First, find an upper bound
    while _fetch_vote_xml(congress, session, hi) is not None:
        time.sleep(0.3)
        hi *= 2
    # Binary search between lo and hi
    while lo < hi:
        mid = (lo + hi + 1) // 2
        time.sleep(0.3)
        if _fetch_vote_xml(congress, session, mid) is not None:
            lo = mid
        else:
            hi = mid - 1
    return lo


def collect_senate_votes(
    congress: int = CURRENT_CONGRESS,
    sessions: tuple[int, ...] = (1, 2),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Collect all Senate roll-call votes for the given congress.
    Saves to data/raw/senate_votes_raw.csv and
    data/raw/senate_politician_votes_raw.csv
    """
    vote_records = []
    position_records = []

    # Build LIS → bioguide mapping for cross-referencing
    log.info("Building LIS-to-bioguide ID mapping...")
    lis_to_bioguide = _build_lis_to_bioguide_map()
    log.info(f"  Mapped {len(lis_to_bioguide)} senators (LIS → bioguide)")

    for session in sessions:
        log.info(f"Collecting Senate votes: congress={congress}, session={session}")

        max_vote = _find_max_vote(congress, session)
        log.info(f"  Found {max_vote} votes for session {session}")

        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 10

        for vote_num in range(1, max_vote + 1):
            if vote_num % 50 == 0:
                log.info(f"  Processing vote {vote_num}/{max_vote}...")

            time.sleep(0.5)  # polite rate limiting
            root = _fetch_vote_xml(congress, session, vote_num)
            if root is None:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.error(f"  {MAX_CONSECUTIVE_FAILURES} consecutive "
                              f"failures — aborting session {session} "
                              f"at vote {vote_num}")
                    break
                continue
            consecutive_failures = 0

            vote_date = (root.findtext("vote_date") or "").strip()
            question = (root.findtext("question") or "").strip()
            result = (root.findtext("vote_result") or "").strip()
            title = (root.findtext("vote_title") or "").strip()

            vote_id = f"senate-{congress}-{session}-{vote_num}"

            vote_records.append({
                "id": vote_id,
                "bill_id": "",  # not always available; filled in feature engineering
                "vote_date": vote_date,
                "chamber": "senate",
                "vote_question": question,
                "description": title or result,
                "related_sector": None,
            })

            # Parse member positions
            members_el = root.find("members")
            if members_el is not None:
                for mem in members_el.findall("member"):
                    lis_id = (mem.findtext("lis_member_id") or "").strip()
                    last_name = (mem.findtext("last_name") or "").strip()
                    first_name = (mem.findtext("first_name") or "").strip()
                    party = (mem.findtext("party") or "").strip()
                    state = (mem.findtext("state") or "").strip()
                    vote_cast = (mem.findtext("vote_cast") or "").lower().strip()

                    position_map = {
                        "yea": "yes", "yes": "yes", "aye": "yes",
                        "nay": "no", "no": "no",
                        "not voting": "not_voting",
                        "present": "abstain",
                    }
                    mapped = position_map.get(vote_cast, "not_voting")

                    # Senate XML uses lis_member_id (e.g. S123) not bioguide
                    # Resolve to bioguide using the mapping
                    bioguide = lis_to_bioguide.get(lis_id, "")

                    position_records.append({
                        "politician_id": bioguide,
                        "lis_member_id": lis_id,
                        "last_name": last_name,
                        "first_name": first_name,
                        "party": party,
                        "state": state,
                        "vote_id": vote_id,
                        "position": mapped,
                    })

    votes_df = pd.DataFrame(vote_records)
    positions_df = pd.DataFrame(position_records)

    # Merge with existing House votes if present
    house_votes_path = DATA_RAW / "votes_raw.csv"
    if house_votes_path.exists():
        house_votes = pd.read_csv(house_votes_path)
        combined_votes = pd.concat([house_votes, votes_df], ignore_index=True)
        combined_votes.drop_duplicates(subset=["id"], keep="last", inplace=True)
        combined_votes.to_csv(DATA_RAW / "votes_raw.csv", index=False)
        log.info(f"Merged senate votes into votes_raw.csv "
                 f"({len(house_votes)} house + {len(votes_df)} senate = "
                 f"{len(combined_votes)} total)")
    else:
        votes_df.to_csv(DATA_RAW / "votes_raw.csv", index=False)

    # Also save senate-only files for debugging
    votes_df.to_csv(DATA_RAW / "senate_votes_raw.csv", index=False)
    positions_df.to_csv(DATA_RAW / "senate_politician_votes_raw.csv", index=False)

    log.info(f"Saved {len(votes_df)} senate votes, "
             f"{len(positions_df)} senate positions")
    return votes_df, positions_df


if __name__ == "__main__":
    collect_senate_votes()


# ── Bill-ID extraction from Senate vote descriptions ──────────────────
# Regex to find bill references like "S. 5", "H.R. 23", "S.J.Res. 18"
_BILL_PAT = re.compile(
    r'(?:^|[\s:])(?P<type>S\.|H\.R\.|S\.J\.Res\.|H\.J\.Res\.'
    r'|S\.Con\.Res\.|H\.Con\.Res\.|H\.Res\.|S\.Res\.)\s*(?P<num>\d+)',
    re.IGNORECASE,
)

_TYPE_MAP = {
    's.': 's', 'h.r.': 'hr',
    's.j.res.': 'sjres', 'h.j.res.': 'hjres',
    's.con.res.': 'sconres', 'h.con.res.': 'hconres',
    'h.res.': 'hres', 's.res.': 'sres',
}


def enrich_senate_bill_ids(congress: int = CURRENT_CONGRESS) -> pd.DataFrame:
    """Parse bill references from Senate vote descriptions and write back.

    Updates senate_votes_raw.csv and votes_raw.csv with extracted bill_ids.
    Returns the updated Senate votes DataFrame.
    """
    path = DATA_RAW / "senate_votes_raw.csv"
    df = pd.read_csv(path)
    df["bill_id"] = df["bill_id"].astype(object)
    filled = 0

    for i, row in df.iterrows():
        desc = str(row.get("description", ""))
        m = _BILL_PAT.search(desc)
        if m:
            prefix = _TYPE_MAP[m.group("type").lower()]
            bill_id = f"{prefix}{m.group('num')}-{congress}"
            df.at[i, "bill_id"] = bill_id
            filled += 1

    df.to_csv(path, index=False)
    log.info(f"Extracted bill_id for {filled}/{len(df)} senate votes")

    # Merge back into votes_raw.csv
    votes_path = DATA_RAW / "votes_raw.csv"
    if votes_path.exists():
        all_votes = pd.read_csv(votes_path)
        senate_mask = all_votes["chamber"] == "senate"
        # Update bill_id for senate votes using id as key
        id_to_bill = df.set_index("id")["bill_id"].to_dict()
        all_votes.loc[senate_mask, "bill_id"] = (
            all_votes.loc[senate_mask, "id"].map(id_to_bill)
        )
        all_votes.to_csv(votes_path, index=False)
        log.info(f"Updated votes_raw.csv with senate bill_ids")

    return df
