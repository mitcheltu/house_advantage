"""
Database Setup & CSV Loader

- Creates the database and tables from schema.sql
- Loads CSV data from data/raw/ into MySQL tables
- Handles FK resolution (bioguide IDs / names → integer PKs)
- Handles ENUM capitalization (house → House, yes → Yes, etc.)
"""
import ast
import json
import logging
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from .connection import get_engine

log = logging.getLogger("db.setup")

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


# ── Helpers ───────────────────────────────────────────────────

_STATE_ABBREV = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "american samoa": "AS", "guam": "GU",
    "northern mariana islands": "MP", "puerto rico": "PR",
    "u.s. virgin islands": "VI",
}


def _state_to_abbrev(val):
    """Convert full state name to 2-letter abbreviation."""
    if not isinstance(val, str):
        return val
    val = val.strip()
    if len(val) <= 2:
        return val.upper()
    return _STATE_ABBREV.get(val.lower(), val[:2].upper())


def _capitalize_chamber(val):
    """Normalize chamber values for MySQL ENUM('House','Senate','Joint')."""
    if not isinstance(val, str):
        return val
    m = {"house": "House", "senate": "Senate", "joint": "Joint"}
    return m.get(val.strip().lower(), val)


def _truncate(engine, table_name: str):
    """Truncate a table with FK checks disabled."""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        conn.execute(text(f"TRUNCATE TABLE `{table_name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    log.info(f"  Truncated {table_name}")


def _insert_df(df: pd.DataFrame, table_name: str, engine):
    """Insert a DataFrame into a table. Returns row count."""
    if df.empty:
        return 0
    df.to_sql(table_name, engine, if_exists="append", index=False,
              method="multi", chunksize=500)
    return len(df)


def run_schema():
    """Execute schema.sql to create database and tables."""
    log.info("Creating database schema...")

    # First create the database (connect without specifying one)
    engine_no_db = get_engine(database="")
    with engine_no_db.connect() as conn:
        conn.execute(text(
            "CREATE DATABASE IF NOT EXISTS house_advantage "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
        conn.commit()

    # Now run the full schema
    engine = get_engine()
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # Remove full-line SQL comments so statements are not dropped when a
    # comment block appears before CREATE TABLE.
    cleaned_lines = []
    for line in schema_sql.splitlines():
        if line.lstrip().startswith("--"):
            continue
        cleaned_lines.append(line)

    cleaned_sql = "\n".join(cleaned_lines)

    # Split on semicolons and execute each statement.
    statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                log.warning(f"Schema statement warning: {e}")
        conn.commit()

    log.info("Schema created successfully")


# ── Individual Table Loaders ──────────────────────────────────

def load_politicians(engine) -> dict[str, int]:
    """
    Load politicians and return bioguide_id → auto-increment id mapping.
    Also returns a name → id mapping for trade FK resolution.
    """
    csv_path = DATA_RAW / "politicians_raw.csv"
    if not csv_path.exists():
        log.warning("politicians_raw.csv not found — skipping")
        return {}

    df = pd.read_csv(csv_path)
    # CSV columns: id (bioguide), full_name, party, chamber, state, district,
    #              photo_url, in_office
    # DB columns:  bioguide_id, first_name, last_name, full_name, party, state,
    #              district, chamber, start_date, end_date, url
    df = df.rename(columns={"id": "bioguide_id"})
    df["chamber"] = df["chamber"].apply(_capitalize_chamber)
    df["state"] = df["state"].apply(_state_to_abbrev)

    # Keep only columns the DB table accepts
    keep = ["bioguide_id", "full_name", "party", "state", "district", "chamber"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.drop_duplicates(subset=["bioguide_id"])

    _truncate(engine, "politicians")
    count = _insert_df(df, "politicians", engine)
    log.info(f"  Loaded {count} politicians")

    # Build bioguide → auto-id mapping
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, bioguide_id, full_name FROM politicians"
        )).fetchall()
    mapping = {r[1]: r[0] for r in rows}  # bioguide → id
    log.info(f"  Built bioguide→id mapping ({len(mapping)} entries)")
    return mapping


def load_committees(engine) -> dict[str, int]:
    """
    Load committees and return committee_code → auto-increment id mapping.
    """
    csv_path = DATA_RAW / "committees_raw.csv"
    if not csv_path.exists():
        log.warning("committees_raw.csv not found — skipping")
        return {}

    df = pd.read_csv(csv_path)
    # CSV: id (code), name, chamber, industry_sector
    # DB:  committee_id, name, chamber, committee_type, sector_tag, url
    df = df.rename(columns={"id": "committee_id", "industry_sector": "sector_tag"})
    df["chamber"] = df["chamber"].apply(_capitalize_chamber)

    keep = ["committee_id", "name", "chamber", "sector_tag"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.drop_duplicates(subset=["committee_id"])

    _truncate(engine, "committees")
    count = _insert_df(df, "committees", engine)
    log.info(f"  Loaded {count} committees")

    # Build code → id mapping
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, committee_id FROM committees"
        )).fetchall()
    mapping = {r[1]: r[0] for r in rows}
    log.info(f"  Built committee_code→id mapping ({len(mapping)} entries)")
    return mapping


def load_committee_memberships(engine, bioguide_map: dict, committee_map: dict):
    """Load committee memberships with FK resolution."""
    csv_path = DATA_RAW / "committee_memberships_raw.csv"
    if not csv_path.exists():
        log.warning("committee_memberships_raw.csv not found — skipping")
        return

    df = pd.read_csv(csv_path)
    # CSV: politician_id (bioguide), committee_id (code), role, ...
    # DB:  politician_id (int FK), committee_id (int FK), role, start_date, end_date

    # Resolve FKs
    df["politician_id"] = df["politician_id"].map(bioguide_map)

    # Normalize committee_id: memberships CSV uses uppercase codes (e.g.
    # "SSAF", "SSAF13") while committees CSV uses lowercase with a "00" suffix
    # for main committees (e.g. "ssaf00", "ssaf13").  Lowercase the code and
    # append "00" only when it has no trailing digits already.
    import re as _re

    def _normalize_committee_id(cid):
        if pd.isna(cid):
            return None
        cid = str(cid).strip().lower()
        if not _re.search(r'\d', cid):
            cid = cid + "00"
        return committee_map.get(cid)

    df["committee_id"] = df["committee_id"].apply(_normalize_committee_id)

    # Drop rows where FK resolution failed
    before = len(df)
    df = df.dropna(subset=["politician_id", "committee_id"])
    df["politician_id"] = df["politician_id"].astype(int)
    df["committee_id"] = df["committee_id"].astype(int)
    dropped = before - len(df)
    if dropped:
        log.info(f"  Dropped {dropped} memberships (unresolved FKs)")

    # Deduplicate on (politician_id, committee_id) — schema has UNIQUE constraint
    df = df.drop_duplicates(subset=["politician_id", "committee_id"])

    keep = ["politician_id", "committee_id", "role"]
    df = df[[c for c in keep if c in df.columns]]

    _truncate(engine, "committee_memberships")
    count = _insert_df(df, "committee_memberships", engine)
    log.info(f"  Loaded {count} committee memberships")


def load_trades(engine, bioguide_map: dict):
    """Load congressional trades with politician FK resolution by name."""
    csv_path = DATA_RAW / "congressional_trades_raw.csv"
    if not csv_path.exists():
        log.warning("congressional_trades_raw.csv not found — skipping")
        return

    df = pd.read_csv(csv_path)
    # CSV: politician_id (name!), ticker, company_name, trade_type, trade_date,
    #      disclosure_date, disclosure_lag_days, amount_lower, amount_upper,
    #      amount_midpoint, asset_type, industry_sector, source_url, chamber,
    #      first_name, last_name, source

    # Build name → DB-id mappings for FK resolution.
    # Politicians CSV uses "Last, First" format; trades CSV uses "First Last".
    pol_path = DATA_RAW / "politicians_raw.csv"
    name_to_id = {}       # multiple formats → DB id
    last_name_to_id = {}  # last-name-only fallback (lower)
    if pol_path.exists():
        pol_df = pd.read_csv(pol_path)
        for _, row in pol_df.iterrows():
            bioguide = row.get("id", "")
            full_name = str(row.get("full_name", "")).strip()
            db_id = bioguide_map.get(bioguide)
            if not db_id or not full_name:
                continue

            # "Last, First" format (as-is from politicians CSV)
            name_to_id[full_name] = db_id

            parts = full_name.split(",", 1)
            if len(parts) == 2:
                last = parts[0].strip()
                first = parts[1].strip()
                # Build reverse "First Last" key (matches trades CSV)
                name_to_id[f"{first} {last}"] = db_id
                # Last-name-only fallback (lower-cased for fuzzy match)
                last_name_to_id[last.lower()] = db_id

    def _resolve_politician(row):
        name = row.get("politician_id")
        if pd.isna(name):
            return None
        name = str(name).strip()
        # Direct lookup (covers both "Last, First" and "First Last")
        if name in name_to_id:
            return name_to_id[name]
        # Bioguide ID lookup
        if name in bioguide_map:
            return bioguide_map[name]
        # Fallback: use the separate last_name column from trades CSV
        last = row.get("last_name")
        if pd.notna(last):
            key = str(last).strip().lower()
            if key in last_name_to_id:
                return last_name_to_id[key]
        return None

    df["politician_id"] = df.apply(_resolve_politician, axis=1)

    keep = ["politician_id", "ticker", "company_name", "trade_type", "trade_date",
            "disclosure_date", "disclosure_lag_days", "amount_lower", "amount_upper",
            "amount_midpoint", "asset_type", "industry_sector", "source_url"]
    df = df[[c for c in keep if c in df.columns]]

    # trade_date is NOT NULL in schema — drop rows missing it
    before = len(df)
    df = df.dropna(subset=["trade_date"])
    if before - len(df):
        log.info(f"  Dropped {before - len(df)} rows with missing trade_date")

    # Replace NaN with None so MySQL receives NULLs for nullable columns
    df = df.where(pd.notna(df), None)

    _truncate(engine, "trades")
    resolved = df["politician_id"].notna().sum()
    count = _insert_df(df, "trades", engine)
    log.info(f"  Loaded {count} trades ({resolved} linked to politicians)")


def _parse_sector_value(raw) -> list[str]:
    """Parse an industry_sector CSV/DB value into a list of sector strings."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    s = str(raw).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (ValueError, SyntaxError):
            pass
    return [s]


def _populate_trade_sectors(engine):
    """Populate trade_sectors junction table from ticker→sector map + trades.industry_sector."""
    # Load the authoritative ticker→sector map (includes multi-sector overrides)
    sector_map_path = DATA_RAW / "_combined_sector_map.json"
    ticker_sector_map = {}
    if sector_map_path.exists():
        ticker_sector_map = json.load(open(sector_map_path))

    _truncate(engine, "trade_sectors")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, ticker, industry_sector FROM trades"
        )).fetchall()

    insert_rows = []
    multi_count = 0
    for trade_id, ticker, raw_sector in rows:
        # Prefer ticker map (has multi-sector overrides), fall back to DB column
        map_val = ticker_sector_map.get(ticker) if ticker else None
        if map_val is not None:
            sectors = map_val if isinstance(map_val, list) else [str(map_val)]
        elif raw_sector:
            sectors = _parse_sector_value(raw_sector)
        else:
            continue

        if len(sectors) > 1:
            multi_count += 1
        for sector in sectors:
            insert_rows.append({"trade_id": trade_id, "sector": sector})

    if insert_rows:
        insert_df = pd.DataFrame(insert_rows)
        _insert_df(insert_df, "trade_sectors", engine)

    log.info(f"  Populated {len(insert_rows)} trade_sector rows "
             f"({multi_count} trades have multiple sectors)")


def load_votes(engine) -> dict[str, int]:
    """Load votes and return vote string ID → auto-increment id mapping."""
    csv_path = DATA_RAW / "votes_raw.csv"
    if not csv_path.exists():
        log.warning("votes_raw.csv not found — skipping")
        return {}

    df = pd.read_csv(csv_path)
    # CSV: id (string like house-119-42), bill_id, vote_date, chamber,
    #      vote_question, description, related_sector
    # DB:  roll_call_id, chamber, congress, session, roll_number,
    #      question, result, vote_date, url

    df = df.rename(columns={
        "id": "roll_call_id",
        "vote_question": "question",
        "description": "result",
    })
    df["chamber"] = df["chamber"].apply(_capitalize_chamber)

    # Extract congress from roll_call_id (e.g. "house-119-42" → 119)
    def _extract_congress(rc_id):
        try:
            parts = str(rc_id).split("-")
            return int(parts[1]) if len(parts) >= 2 else None
        except (ValueError, IndexError):
            return None
    df["congress"] = df["roll_call_id"].apply(_extract_congress)

    # Parse vote_date: "January 9, 2025,  02:54 PM" → DATE
    if "vote_date" in df.columns:
        df["vote_date"] = pd.to_datetime(
            df["vote_date"], format="mixed", dayfirst=False, utc=True
        ).dt.date

    # Truncate result to fit VARCHAR(100)
    if "result" in df.columns:
        df["result"] = df["result"].str[:100]

    keep = ["roll_call_id", "chamber", "congress", "question", "result", "vote_date"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.drop_duplicates(subset=["roll_call_id"])

    _truncate(engine, "votes")
    count = _insert_df(df, "votes", engine)
    log.info(f"  Loaded {count} votes")

    # Build string_id → auto-id mapping
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, roll_call_id FROM votes"
        )).fetchall()
    mapping = {r[1]: r[0] for r in rows}
    return mapping


def load_politician_votes(engine, bioguide_map: dict, vote_map: dict):
    """Load politician vote positions with FK resolution."""
    # House positions
    house_path = DATA_RAW / "politician_votes_raw.csv"
    # Senate positions
    senate_path = DATA_RAW / "senate_politician_votes_raw.csv"

    frames = []
    for path in [house_path, senate_path]:
        if path.exists():
            frames.append(pd.read_csv(path))
    if not frames:
        log.warning("No politician_votes CSVs found — skipping")
        return

    df = pd.concat(frames, ignore_index=True)
    # CSV: politician_id (bioguide), vote_id (string), position (lowercase)

    # Resolve FKs
    df["politician_id"] = df["politician_id"].map(bioguide_map)
    df["vote_id"] = df["vote_id"].map(vote_map)

    # Map position values to ENUM: Yes, No, Not Voting, Present
    pos_map = {
        "yes": "Yes", "no": "No",
        "not_voting": "Not Voting", "abstain": "Present",
    }
    df["position"] = df["position"].map(pos_map).fillna("Not Voting")

    # Drop unresolved FKs
    before = len(df)
    df = df.dropna(subset=["politician_id", "vote_id"])
    df["politician_id"] = df["politician_id"].astype(int)
    df["vote_id"] = df["vote_id"].astype(int)
    dropped = before - len(df)
    if dropped:
        log.info(f"  Dropped {dropped} vote positions (unresolved FKs)")

    df = df.drop_duplicates(subset=["politician_id", "vote_id"])
    keep = ["politician_id", "vote_id", "position"]
    df = df[keep]

    _truncate(engine, "politician_votes")
    count = _insert_df(df, "politician_votes", engine)
    log.info(f"  Loaded {count} politician vote positions")


def _log_bills_quality(engine, total_count: int):
    """Log quality metrics for the bills table after loading."""
    try:
        with engine.connect() as conn:
            metrics = conn.execute(text(
                "SELECT "
                "  SUM(policy_area IS NOT NULL AND policy_area != '') as has_policy, "
                "  SUM(latest_action_date IS NOT NULL) as has_action_date, "
                "  SUM(origin_chamber IS NOT NULL) as has_chamber, "
                "  SUM(sponsor_bioguide IS NOT NULL AND sponsor_bioguide != '') as has_sponsor, "
                "  SUM(url IS NOT NULL AND url != '') as has_url "
                "FROM bills"
            )).fetchone()
            log.info(f"  Bills quality metrics ({total_count} total):")
            labels = ["policy_area", "latest_action_date", "origin_chamber",
                      "sponsor_bioguide", "url"]
            for i, label in enumerate(labels):
                val = metrics[i] or 0
                pct = val / total_count * 100 if total_count else 0
                log.info(f"    {label:25s}: {val:>5}/{total_count} ({pct:.1f}%)")
    except Exception as e:
        log.warning(f"  Could not compute bills quality metrics: {e}")


def load_bills(engine):
    """Load bills data and log quality metrics."""
    csv_path = DATA_RAW / "bills_raw.csv"
    if not csv_path.exists():
        log.debug("bills_raw.csv not found — skipping")
        return

    df = pd.read_csv(csv_path)
    # CSV: id, congress, bill_number, title, introduced_date, ...
    # DB:  bill_id, congress, bill_type, bill_number, title, ...
    df = df.rename(columns={"id": "bill_id"})
    if "id" in df.columns:
        df = df.drop(columns=["id"])

    # Split bill_number "HR144" → bill_type="HR", bill_number=144
    if "bill_number" in df.columns:
        import re as _re
        df["bill_type"] = df["bill_number"].apply(
            lambda x: _re.match(r'([A-Za-z]+)', str(x)).group(1).upper()
            if pd.notna(x) and _re.match(r'([A-Za-z]+)', str(x)) else None
        )
        df["bill_number"] = df["bill_number"].apply(
            lambda x: int(m.group(1)) if pd.notna(x) and (m := _re.search(r'(\d+)', str(x))) else None
        )

    keep = ["bill_id", "congress", "bill_type", "bill_number", "title",
            "policy_area", "latest_action", "latest_action_date",
            "origin_chamber", "sponsor_bioguide", "url"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.drop_duplicates(subset=["bill_id"])

    _truncate(engine, "bills")
    count = _insert_df(df, "bills", engine)
    log.info(f"  Loaded {count} bills")

    # Quality metrics
    if count > 0:
        _log_bills_quality(engine, count)


def load_fec(engine):
    """Load FEC candidates and financial totals."""
    # Candidates
    cand_path = DATA_RAW / "fec_candidates_raw.csv"
    if cand_path.exists():
        df = pd.read_csv(cand_path)
        # Map 'office' column: H → House, S → Senate
        if "office" in df.columns:
            office_map = {"H": "House", "S": "Senate"}
            df["office"] = df["office"].map(office_map)
        df = df.drop_duplicates(subset=["candidate_id"])
        _truncate(engine, "fec_candidates")
        count = _insert_df(df, "fec_candidates", engine)
        log.info(f"  Loaded {count} FEC candidates")

    # Totals
    totals_path = DATA_RAW / "fec_candidate_totals_raw.csv"
    if totals_path.exists():
        df = pd.read_csv(totals_path)
        # Drop 'name' and 'party' — those are on fec_candidates, not totals
        df = df.drop(columns=[c for c in ["name", "party"] if c in df.columns],
                     errors="ignore")
        _truncate(engine, "fec_candidate_totals")
        count = _insert_df(df, "fec_candidate_totals", engine)
        log.info(f"  Loaded {count} FEC financial totals")


def load_cusip_map(engine):
    """Load CUSIP→ticker map from OpenFIGI."""
    csv_path = DATA_RAW / "cusip_ticker_map.csv"
    if not csv_path.exists():
        log.debug("cusip_ticker_map.csv not found — skipping")
        return
    df = pd.read_csv(csv_path)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df = df.drop_duplicates(subset=["cusip"])

    _truncate(engine, "cusip_ticker_map")
    count = _insert_df(df, "cusip_ticker_map", engine)
    log.info(f"  Loaded {count} CUSIP→ticker mappings")


# Keyword→sector mapping for PAC contributor employer names
_EMPLOYER_SECTOR_KEYWORDS = {
    "defense": ["defense", "military", "lockheed", "raytheon", "northrop", "boeing",
                "general dynamics", "l3harris", "bae systems"],
    "finance": ["bank", "capital", "financ", "invest", "insurance", "credit",
                "goldman", "morgan", "jpmorgan", "citigroup", "fidelity", "blackrock",
                "securities", "hedge", "asset management", "wells fargo"],
    "healthcare": ["health", "pharma", "medical", "hospital", "biotech", "pfizer",
                   "johnson & johnson", "merck", "abbott", "unitedhealth", "humana",
                   "anthem", "cigna", "aetna"],
    "energy": ["energy", "oil", "gas", "petroleum", "exxon", "chevron", "solar",
               "electric", "utility", "power", "mining", "coal", "nuclear"],
    "tech": ["tech", "software", "google", "microsoft", "apple", "amazon", "meta",
             "nvidia", "intel", "cisco", "oracle", "ibm", "semiconductor", "cyber",
             "data", "cloud", "ai ", "artificial intelligence"],
    "telecom": ["telecom", "media", "broadcast", "comcast", "verizon", "at&t",
                "disney", "netflix", "entertainment", "communications"],
    "agriculture": ["farm", "agri", "food", "beverage", "restaurant", "retail",
                    "grocery", "consumer", "tobacco", "alcohol", "wine", "beer"],
}


def _employer_to_sector(employer: str | None) -> str | None:
    """Map employer name to sector via keyword matching."""
    if not isinstance(employer, str):
        return None
    emp_lower = employer.lower()
    for sector, keywords in _EMPLOYER_SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in emp_lower:
                return sector
    return None


def load_pac_contributions(engine):
    """Load PAC contributions with employer→sector tagging."""
    csv_path = DATA_RAW / "fec_pac_contributions_raw.csv"
    if not csv_path.exists():
        log.debug("fec_pac_contributions_raw.csv not found — skipping")
        return

    df = pd.read_csv(csv_path)
    # Infer sector from employer name
    df["sector_tag"] = df["contributor_employer"].apply(_employer_to_sector)

    keep = ["contributor_name", "contributor_employer", "committee_name",
            "candidate_id", "amount", "receipt_date", "state", "sector_tag"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.where(pd.notna(df), None)

    _truncate(engine, "pac_contributions")
    count = _insert_df(df, "pac_contributions", engine)
    tagged = df["sector_tag"].notna().sum()
    log.info(f"  Loaded {count} PAC contributions ({tagged} sector-tagged)")


def load_prices(engine):
    """Load price CSVs from data/raw/prices/ into stock_prices table."""
    price_dir = DATA_RAW / "prices"
    if not price_dir.exists():
        log.debug("No price data directory found")
        return

    total = 0
    _truncate(engine, "stock_prices")

    for csv_file in price_dir.glob("*.csv"):
        if csv_file.name.startswith("_"):
            continue  # Skip manifest

        ticker = csv_file.stem.upper()
        df = pd.read_csv(csv_file)
        if df.empty:
            continue

        # Standardize columns
        col_map = {}
        for col in df.columns:
            lower = col.lower()
            if "date" in lower:
                col_map[col] = "price_date"
            elif lower == "open":
                col_map[col] = "open_price"
            elif lower == "high":
                col_map[col] = "high"
            elif lower == "low":
                col_map[col] = "low"
            elif lower == "close":
                col_map[col] = "close"
            elif lower == "volume":
                col_map[col] = "volume"

        df = df.rename(columns=col_map)
        df["ticker"] = ticker

        keep_cols = ["ticker", "price_date", "open_price", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]]

        try:
            _insert_df(df, "stock_prices", engine)
            total += len(df)
        except Exception as e:
            log.warning(f"Price load error for {ticker}: {e}")
            # Reset engine connection pool after error to avoid cascading failures
            engine.dispose()

    log.info(f"  Loaded {total} price rows total")


def load_13f_holdings(engine):
    """Load 13-F holdings and inferred trades into MySQL."""
    thirteenf_dir = DATA_RAW / "13f"
    if not thirteenf_dir.exists():
        return

    _truncate(engine, "institutional_holdings")
    _truncate(engine, "institutional_trades")

    # Load holdings
    for csv_file in thirteenf_dir.glob("*_holdings.csv"):
        df = pd.read_csv(csv_file, dtype=str)
        if df.empty:
            continue
        # Map CSV uppercase columns to DB schema columns
        col_map = {
            "ACCESSION_NUMBER": "fund_cik",
            "issuer_name": "issuer_name",
            "cusip": "cusip",
            "FIGI": "ticker",
            "value_x1000": "value_x1000",
            "shares": "shares",
            "year": "year",
            "quarter": "quarter",
        }
        df = df.rename(columns=col_map)
        keep = ["fund_cik", "cusip", "ticker", "issuer_name", "shares",
                "value_x1000", "year", "quarter"]
        df = df[[c for c in keep if c in df.columns]]
        try:
            _insert_df(df, "institutional_holdings", engine)
            log.info(f"  Loaded {len(df)} 13-F holdings from {csv_file.name}")
        except Exception as e:
            log.warning(f"13-F holdings load error for {csv_file.name}: {e}")
            engine.dispose()

    # Load inferred trades
    trades_path = thirteenf_dir / "institutional_trades_inferred.csv"
    if trades_path.exists():
        df = pd.read_csv(trades_path)
        # CSV has shares_curr; DB schema expects shares_current
        df = df.rename(columns={"shares_curr": "shares_current"})
        try:
            _insert_df(df, "institutional_trades", engine)
            log.info(f"  Loaded {len(df)} inferred institutional trades")
        except Exception as e:
            engine.dispose()
            log.warning(f"13-F trades load error: {e}")


# ── Main Entry Points ────────────────────────────────────────

def load_all():
    """
    Load all CSV data into MySQL tables in dependency order.
    Tables with FK dependencies are loaded after their parents.
    """
    log.info("Loading all CSV data into MySQL...")
    engine = get_engine()

    # 1. Load independent parent tables (build FK mappings)
    log.info("[1/7] Politicians...")
    bioguide_map = load_politicians(engine)

    log.info("[2/7] Committees...")
    committee_map = load_committees(engine)

    # 2. Load FK-dependent tables
    log.info("[3/7] Committee Memberships...")
    load_committee_memberships(engine, bioguide_map, committee_map)

    log.info("[4/7] Trades...")
    load_trades(engine, bioguide_map)
    _populate_trade_sectors(engine)

    log.info("[5/7] Votes & Politician Votes...")
    vote_map = load_votes(engine)
    load_politician_votes(engine, bioguide_map, vote_map)

    # 3. Load standalone tables
    log.info("[6/8] FEC, Bills, CUSIP map...")
    load_bills(engine)
    load_fec(engine)
    load_pac_contributions(engine)
    load_cusip_map(engine)

    log.info("[8/8] Prices & 13-F Holdings...")
    load_prices(engine)
    load_13f_holdings(engine)

    log.info("=" * 50)
    log.info("Data loading complete!")


def setup_all():
    """Full setup: create schema + load data."""
    run_schema()
    load_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup_all()
