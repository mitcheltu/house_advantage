"""
GovInfo API Collector — Bill Full Text

Downloads full text of bills from the Government Publishing Office.
API: https://api.govinfo.gov
Auth: ?api_key= query param
Key: https://api.data.gov/signup (same registration as OpenFEC)
"""
import logging
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
    offset = 0
    page_size = 100
    records = []

    log.info(f"Collecting {bill_type} bills from {congress}th Congress via GovInfo...")

    while offset < max_bills:
        data = _govinfo_get(
            f"/collections/{collection}/{start_date}",
            params={
                "offset": offset,
                "pageSize": min(page_size, max_bills - offset),
                "congress": congress,
            },
        )

        packages = data.get("packages", [])
        if not packages:
            break

        for pkg in packages:
            pkg_id = pkg.get("packageId", "")

            # Filter to requested bill type
            if bill_type.upper() not in pkg_id.upper():
                continue

            records.append({
                "package_id": pkg_id,
                "title": pkg.get("title"),
                "congress": congress,
                "bill_type": bill_type,
                "last_modified": pkg.get("lastModified"),
                "date_issued": pkg.get("dateIssued"),
                "doc_class": pkg.get("docClass"),
                "category": pkg.get("category"),
                "download_url": pkg.get("packageLink"),
            })

        offset += page_size
        log.info(f"  GovInfo offset {offset}: {len(packages)} packages")

    df = pd.DataFrame(records)
    out_path = DATA_RAW / f"govinfo_bills_{bill_type}_{congress}_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} bill records to {out_path}")
    return df


def download_bill_text(package_id: str, format: str = "htm") -> str | None:
    """
    Download the full text of a specific bill.
    Returns text content or None on failure.

    Supported formats: htm, xml, pdf, txt
    """
    try:
        data = _govinfo_get(f"/packages/{package_id}/summary")
        download_links = data.get("download", {})
        text_url = download_links.get(f"{format}Url")

        if not text_url:
            log.warning(f"No {format} download for {package_id}")
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
    offset = 0
    page_size = 100
    records = []

    log.info(f"Collecting committee reports from {congress}th Congress...")

    while offset < max_reports:
        data = _govinfo_get(
            f"/collections/CRPT/{start_date}",
            params={
                "offset": offset,
                "pageSize": min(page_size, max_reports - offset),
                "congress": congress,
            },
        )

        packages = data.get("packages", [])
        if not packages:
            break

        for pkg in packages:
            records.append({
                "package_id": pkg.get("packageId"),
                "title": pkg.get("title"),
                "congress": congress,
                "last_modified": pkg.get("lastModified"),
                "date_issued": pkg.get("dateIssued"),
                "doc_class": pkg.get("docClass"),
            })

        offset += page_size

    df = pd.DataFrame(records)
    out_path = DATA_RAW / "govinfo_committee_reports_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} committee reports to {out_path}")
    return df


def collect_all(congress: int = 119):
    """Run full GovInfo collection."""
    dfs = []
    for bill_type in ["hr", "s"]:
        df = collect_bills_text(congress=congress, bill_type=bill_type)
        dfs.append(df)
    collect_committee_reports(congress=congress)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


if __name__ == "__main__":
    collect_all()
