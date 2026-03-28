"""
GovInfo API Collector — Bill Full Text

Downloads full text of bills from the Government Publishing Office.
API: https://api.govinfo.gov
Auth: ?api_key= query param
Key: https://api.data.gov/signup (same registration as OpenFEC)
"""
import logging
import re
import time
import pandas as pd
from pathlib import Path
from .utils import get_env, rate_limited_get, DATA_RAW

log = logging.getLogger("collector.govinfo")

BASE_URL = "https://api.govinfo.gov"


def _govinfo_get(endpoint: str, params: dict | None = None, timeout: int = 30) -> dict:
    """Make authenticated GET to GovInfo API."""
    api_key = get_env("GOVINFO_API_KEY")
    url = f"{BASE_URL}{endpoint}"
    p = params or {}
    p["api_key"] = api_key
    resp = rate_limited_get(url, params=p, delay=1.0, timeout=timeout)
    return resp.json()


def collect_bills_text(
    congress: int = 119,
    bill_type: str = "hr",
    max_bills: int = 500,
    start_date: str = "2025-01-01T00:00:00Z",
) -> pd.DataFrame:
    """
    Fetch bill summaries / metadata from GovInfo BILLS collection.
    Saves: data/raw/govinfo_bills_raw.csv

    Parameters:
        congress: Congress number
        bill_type: hr, s, hjres, sjres
        max_bills: Maximum number of bills to retrieve
        start_date: ISO datetime for lastModifiedStartDate (required by API)
    """
    collection = "BILLS"
    page_size = 100
    records = []
    offset_mark = "*"  # GovInfo requires offsetMark; '*' = start

    log.info(f"Collecting {bill_type} bills from {congress}th Congress via GovInfo...")

    while len(records) < max_bills:
        data = _govinfo_get(
            f"/collections/{collection}/{start_date}",
            params={
                "offsetMark": offset_mark,
                "pageSize": min(page_size, max_bills - len(records)),
            },
        )

        packages = data.get("packages", [])
        if not packages:
            break

        for pkg in packages:
            pkg_id = pkg.get("packageId", "")

            # Filter to requested bill type and congress
            if bill_type.upper() not in pkg_id.upper():
                continue
            if f"-{congress}" not in pkg_id:
                continue

            bill_id = _package_id_to_bill_id(pkg_id)
            records.append({
                "package_id": pkg_id,
                "bill_id": bill_id,
                "title": pkg.get("title"),
                "congress": congress,
                "bill_type": bill_type,
                "last_modified": pkg.get("lastModified"),
                "date_issued": pkg.get("dateIssued"),
                "doc_class": pkg.get("docClass"),
                "category": pkg.get("category"),
                "download_url": pkg.get("packageLink"),
            })

        # Use nextPage cursor for pagination
        next_page = data.get("nextPage")
        if not next_page:
            break
        # Extract offsetMark from nextPage URL
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(next_page).query)
        offset_mark = qs.get("offsetMark", [None])[0]
        if not offset_mark:
            break
        log.info(f"  GovInfo: {len(records)} {bill_type} packages so far")

    df = pd.DataFrame(records)
    out_path = DATA_RAW / f"govinfo_bills_{bill_type}_{congress}_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} bill records to {out_path}")
    return df


_FORMAT_KEY_MAP = {"htm": "txtLink", "xml": "xmlLink", "pdf": "pdfLink", "txt": "txtLink"}


def download_bill_text(package_id: str, format: str = "htm") -> str | None:
    """
    Download the full text of a specific bill.
    Returns text content or None on failure.

    Supported formats: htm, xml, pdf, txt
    """
    try:
        data = _govinfo_get(f"/packages/{package_id}/summary")
        download_links = data.get("download", {})
        # GovInfo uses keys like 'txtLink', 'xmlLink', 'pdfLink'
        key = _FORMAT_KEY_MAP.get(format, f"{format}Link")
        text_url = download_links.get(key)

        if not text_url:
            log.warning(f"No {format} download (key={key}) for {package_id}")
            return None

        api_key = get_env("GOVINFO_API_KEY")
        resp = rate_limited_get(
            text_url,
            params={"api_key": api_key},
            delay=1.0,
            timeout=60,
        )
        return resp.text

    except Exception as e:
        log.error(f"Failed to download {package_id}: {e}")
        return None


def collect_committee_reports(
    congress: int = 119,
    max_reports: int = 200,
    start_date: str = "2025-01-01T00:00:00Z",
) -> pd.DataFrame:
    """
    Fetch committee reports from GovInfo CRPT collection.
    Saves: data/raw/govinfo_committee_reports_raw.csv
    """
    page_size = 100
    records = []
    offset_mark = "*"

    log.info(f"Collecting committee reports from {congress}th Congress...")

    while len(records) < max_reports:
        data = _govinfo_get(
            f"/collections/CRPT/{start_date}",
            params={
                "offsetMark": offset_mark,
                "pageSize": min(page_size, max_reports - len(records)),
            },
        )

        packages = data.get("packages", [])
        if not packages:
            break

        for pkg in packages:
            pkg_id = pkg.get("packageId", "")
            # Filter to requested congress
            if f"-{congress}" not in pkg_id:
                continue
            records.append({
                "package_id": pkg_id,
                "title": pkg.get("title"),
                "congress": congress,
                "last_modified": pkg.get("lastModified"),
                "date_issued": pkg.get("dateIssued"),
                "doc_class": pkg.get("docClass"),
            })

        next_page = data.get("nextPage")
        if not next_page:
            break
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(next_page).query)
        offset_mark = qs.get("offsetMark", [None])[0]
        if not offset_mark:
            break

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "govinfo_committee_reports_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} committee reports to {out_path}")
    return df


def _package_id_to_bill_id(package_id: str) -> str | None:
    """Convert GovInfo packageId to Congress.gov bill_id format.

    Examples:
        'BILLS-119hr7147eas' -> 'hr7147-119'
        'BILLS-119s100is'    -> 's100-119'
        'BILLS-119hjres1ih'  -> 'hjres1-119'
    """
    m = re.match(r"BILLS-(\d+)([a-z]+?)(\d+)([a-z]+)$", package_id, re.IGNORECASE)
    if not m:
        return None
    congress, bill_type, bill_number, _version = m.groups()
    return f"{bill_type.lower()}{bill_number}-{congress}"


def merge_govinfo_to_bills(congress: int = 119) -> pd.DataFrame | None:
    """Merge GovInfo metadata into the Congress.gov bills_raw.csv.

    Links bills by matching bill_id (e.g. 'hr1-119') derived from the
    GovInfo packageId.  Adds columns: govinfo_package_id, govinfo_url,
    date_issued.

    Returns the merged DataFrame, or None if bills_raw.csv doesn't exist.
    """
    bills_path = DATA_RAW / "bills_raw.csv"
    if not bills_path.exists():
        log.warning("bills_raw.csv not found — skipping GovInfo merge")
        return None

    bills_df = pd.read_csv(bills_path)
    if "id" not in bills_df.columns:
        log.warning("bills_raw.csv missing 'id' column — skipping merge")
        return None

    # Drop any existing GovInfo columns from a prior merge (idempotent)
    for col in ["govinfo_package_id", "govinfo_url", "date_issued", "bill_id"]:
        if col in bills_df.columns:
            bills_df.drop(columns=[col], inplace=True)

    # Collect GovInfo CSVs for all bill types
    govinfo_frames = []
    for bt in ["hr", "s", "hjres", "sjres"]:
        gp = DATA_RAW / f"govinfo_bills_{bt}_{congress}_raw.csv"
        if gp.exists():
            govinfo_frames.append(pd.read_csv(gp))

    if not govinfo_frames:
        log.info("No GovInfo bill CSVs found — nothing to merge")
        return bills_df

    gov_df = pd.concat(govinfo_frames, ignore_index=True)

    if "bill_id" not in gov_df.columns:
        # Older CSVs may not have bill_id — derive it
        gov_df["bill_id"] = gov_df["package_id"].apply(_package_id_to_bill_id)

    # Keep only the latest version per bill (highest lastModified)
    gov_df = gov_df.sort_values("last_modified", ascending=False)
    gov_df = gov_df.drop_duplicates(subset="bill_id", keep="first")

    # Rename for merge
    merge_cols = gov_df[["bill_id", "package_id", "download_url", "date_issued"]].copy()
    merge_cols = merge_cols.rename(columns={
        "package_id": "govinfo_package_id",
        "download_url": "govinfo_url",
    })

    before = len(bills_df)
    bills_df = bills_df.merge(merge_cols, left_on="id", right_on="bill_id",
                              how="left")
    # Drop redundant bill_id column from merge
    bills_df.drop(columns=["bill_id"], errors="ignore", inplace=True)

    matched = bills_df["govinfo_package_id"].notna().sum()
    log.info(f"GovInfo merge: {matched}/{before} bills matched ({matched/before*100:.1f}%)")

    bills_df.to_csv(bills_path, index=False)
    log.info(f"Updated {bills_path} with GovInfo columns")
    return bills_df


def collect_all(congress: int = 119):
    """Run full GovInfo collection and merge into bills_raw.csv."""
    dfs = []
    for bill_type in ["hr", "s"]:
        df = collect_bills_text(congress=congress, bill_type=bill_type)
        dfs.append(df)
    collect_committee_reports(congress=congress)

    # Merge GovInfo data into Congress.gov bills
    merge_govinfo_to_bills(congress=congress)

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


if __name__ == "__main__":
    collect_all()
