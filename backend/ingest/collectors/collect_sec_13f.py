"""
SEC 13-F Bulk Collector — Institutional Holdings

Downloads quarterly 13-F bulk data sets from SEC EDGAR.
Infers trades from quarter-over-quarter position changes.
No API key needed — User-Agent header required.

Data: https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets
"""
import logging
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from .utils import get_env, DATA_RAW

log = logging.getLogger("collector.sec_13f")

SEC_BASE = "https://efts.sec.gov/LATEST/search-index"
SEC_BULK_BASE = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"
SEC_INDEX_PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"

# Major institutional funds we track (CIK numbers)
TRACKED_FUNDS = {
    "102909":  "VANGUARD GROUP INC",
    "1364742": "BLACKROCK INC",
    "315066":  "FIDELITY MANAGEMENT & RESEARCH",
    "93751":   "STATE STREET CORP",
    "1038133": "T. ROWE PRICE ASSOCIATES INC",
    "1037389": "BERKSHIRE HATHAWAY INC",
    "1350694": "CITADEL ADVISORS LLC",
    "1061768": "RENAISSANCE TECHNOLOGIES LLC",
    "1336528": "BRIDGEWATER ASSOCIATES LP",
    "1535392": "TWO SIGMA INVESTMENTS LP",
}


def _get_sec_headers() -> dict:
    """Return SEC-compliant request headers."""
    agent = get_env("SEC_USER_AGENT", default="CorruptionPulse admin@corruptionpulse.com")
    return {
        "User-Agent": agent,
        "Accept-Encoding": "gzip, deflate",
    }


def _scrape_zip_urls() -> dict[str, str]:
    """
    Scrape the SEC 13-F data sets page to find all available ZIP download URLs.
    Returns a dict mapping a label (e.g. '2024q3') to the full URL.
    """
    headers = _get_sec_headers()
    try:
        resp = requests.get(SEC_INDEX_PAGE, headers=headers, timeout=30)
        if resp.status_code != 200:
            log.warning(f"SEC index page returned {resp.status_code}")
            return {}
    except requests.RequestException as e:
        log.warning(f"Failed to fetch SEC index page: {e}")
        return {}

    import re
    urls = {}
    # Find all ZIP links — both old format (2023q4.zip) and new (01sep2024-30nov2024_form13f.zip)
    for match in re.finditer(r'href="([^"]*form-13f-data-sets/[^"]*\.zip)"', resp.text, re.IGNORECASE):
        url = match.group(1)
        if url.startswith("/"):
            url = f"https://www.sec.gov{url}"
        # Try to extract year/quarter from filename
        fname = url.rsplit("/", 1)[-1].lower()
        urls[fname] = url
    log.info(f"Found {len(urls)} 13-F ZIP files on SEC index page")
    return urls


# Map quarter numbers to month ranges used in newer SEC filenames.
# Pre-2024: `2023q4_form13f.zip`
# 2024+: rolling 3-month windows that DON'T align to calendar quarters:
#   01jan-29feb, 01mar-31may, 01jun-31aug, 01sep-30nov, 01dec-28feb(next year)
# We map each calendar quarter to the SEC window whose start month falls in it.
_Q_MONTH_RANGES = {
    1: ("01jan", "29feb"),   # Jan window → covers Q1 start
    2: ("01mar", "31may"),   # Mar window → covers Q2 start
    3: ("01jun", "31aug"),   # Jun window → covers Q3 start
    4: ("01sep", "30nov"),   # Sep window → covers Q4 start
}


def _try_download_quarter(year: int, quarter: int) -> bytes | None:
    """
    Try multiple URL patterns for SEC 13-F bulk zips.
    Since 2024 SEC uses date-range filenames; for 2023 and earlier the old
    quarterly format still works.  We first try static patterns, then fall
    back to scraping the index page for the actual link.
    """
    headers = _get_sec_headers()

    # Build candidate patterns
    start_m, end_m = _Q_MONTH_RANGES[quarter]
    patterns = [
        f"{SEC_BULK_BASE}/{year}q{quarter}.zip",
        f"{SEC_BULK_BASE}/{year}q{quarter}_form13f.zip",
        f"{SEC_BULK_BASE}/{start_m}{year}-{end_m}{year}_form13f.zip",
    ]

    for url in patterns:
        try:
            resp = requests.get(url, headers=headers, timeout=120)
            if resp.status_code == 200:
                log.info(f"Downloaded {url} ({len(resp.content) / 1e6:.1f} MB)")
                return resp.content
            log.debug(f"  {url} → HTTP {resp.status_code}")
        except requests.RequestException as e:
            log.debug(f"  {url} → {e}")

    # Fallback: scrape the index page and find any file containing the year
    # and the start month abbreviation from _Q_MONTH_RANGES
    log.info(f"Static URLs failed for {year}Q{quarter}, scraping index page...")
    zip_urls = _scrape_zip_urls()
    start_month_abbr = start_m[2:]  # e.g. "jan" from "01jan"
    for fname, url in zip_urls.items():
        # Match old format: "2024q3"
        if f"{year}q{quarter}" in fname:
            return _download_url(url, headers)
        # Match new format: file starts with the window start month and contains the year
        if fname.startswith(start_m) and str(year) in fname:
            return _download_url(url, headers)

    log.warning(f"Could not download 13-F data for {year}Q{quarter}")
    return None


def _download_latest() -> bytes | None:
    """Download the most recent available 13-F bulk ZIP file."""
    headers = _get_sec_headers()
    zip_urls = _scrape_zip_urls()
    if not zip_urls:
        return None
    # The first entry is the most recent
    fname, url = next(iter(zip_urls.items()))
    log.info(f"Downloading latest 13-F: {fname}")
    return _download_url(url, headers)


def _download_url(url: str, headers: dict) -> bytes | None:
    """Download a URL and return bytes, or None on failure."""
    try:
        resp = requests.get(url, headers=headers, timeout=120)
        if resp.status_code == 200:
            log.info(f"Downloaded {url} ({len(resp.content) / 1e6:.1f} MB)")
            return resp.content
    except requests.RequestException as e:
        log.debug(f"  {url} → {e}")
    return None


def _find_in_zip(zf: zipfile.ZipFile, keyword: str) -> str | None:
    """Find a file in a ZIP whose name contains *keyword* (case-insensitive)."""
    for name in zf.namelist():
        if keyword in name.lower() and (name.lower().endswith(".tsv")
                                        or name.lower().endswith(".csv")):
            return name
    return None


def _extract_infotable(zip_bytes: bytes) -> pd.DataFrame:
    """
    Extract INFOTABLE.tsv from the 13-F zip file and derive CIK from
    the ACCESSION_NUMBER column (format: {CIK_padded}-YY-SEQ).
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        info_name = _find_in_zip(zf, "infotable")
        if not info_name:
            log.warning(f"No INFOTABLE file found in zip. Files: {zf.namelist()}")
            return pd.DataFrame()

        sep = "\t" if info_name.endswith(".tsv") else ","
        with zf.open(info_name) as f:
            df = pd.read_csv(f, sep=sep, low_memory=False, dtype=str)

    # Derive CIK from ACCESSION_NUMBER (e.g. "0001971024-23-000012" → "1971024")
    acc_col = next((c for c in df.columns if "accession" in c.lower()), None)
    if acc_col:
        df["CIK"] = (df[acc_col].astype(str)
                      .str.split("-").str[0]
                      .str.lstrip("0"))
        log.info(f"Derived CIK from {acc_col} for {df['CIK'].notna().sum()} rows")
    else:
        log.warning(f"No ACCESSION column found. Columns: {df.columns.tolist()}")

    return df


def _filter_tracked_funds(df: pd.DataFrame) -> pd.DataFrame:
    """Filter infotable to only tracked funds by CIK."""
    # Prefer the joined CIK column; fall back to scanning for one
    if "CIK" in df.columns:
        cik_col = "CIK"
    else:
        cik_col = next((c for c in df.columns if c.lower() == "cik"), None)

    if cik_col is None:
        log.warning(f"No CIK column found. Columns: {df.columns.tolist()}")
        return df

    # Normalize CIK values (strip leading zeros to match TRACKED_FUNDS keys)
    df[cik_col] = df[cik_col].astype(str).str.strip().str.lstrip("0")
    tracked_ciks = set(TRACKED_FUNDS.keys())

    filtered = df[df[cik_col].isin(tracked_ciks)].copy()
    log.info(f"Filtered to {len(filtered)} rows from tracked funds")
    return filtered


def collect_quarter(year: int, quarter: int) -> pd.DataFrame:
    """
    Download and process one quarter of 13-F data.
    Saves to data/raw/13f/{year}q{quarter}_holdings.csv
    """
    log.info(f"Collecting 13-F data for {year}Q{quarter}...")

    zip_bytes = _try_download_quarter(year, quarter)
    if zip_bytes is None:
        return pd.DataFrame()

    df = _extract_infotable(zip_bytes)
    if df.empty:
        return df

    # Filter to tracked funds
    df = _filter_tracked_funds(df)

    # Standardize column names
    col_map = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower == "cusip":
            col_map[col] = "cusip"
        elif lower == "nameofissuer":
            col_map[col] = "issuer_name"
        elif lower == "value":
            col_map[col] = "value_x1000"
        elif lower == "sshprnamt":
            col_map[col] = "shares"
        elif lower == "sshprnamttype":
            col_map[col] = "share_type"
        elif lower == "titleofclass":
            col_map[col] = "title_of_class"
        elif lower == "putcall":
            col_map[col] = "put_call"

    if col_map:
        df = df.rename(columns=col_map)

    df["year"] = year
    df["quarter"] = quarter

    out_dir = DATA_RAW / "13f"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{year}q{quarter}_holdings.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} positions to {out_path}")
    return df


def infer_trades(current_q: pd.DataFrame, prior_q: pd.DataFrame) -> pd.DataFrame:
    """
    Infer institutional trades by comparing quarter-over-quarter positions.
    Returns DataFrame of inferred trades with direction (buy/sell/new/exit).
    """
    if current_q.empty or prior_q.empty:
        return pd.DataFrame()

    if "cusip" not in current_q.columns or "cusip" not in prior_q.columns:
        log.warning("Missing cusip column for trade inference")
        return pd.DataFrame()

    # Ensure numeric shares
    for df in [current_q, prior_q]:
        if "shares" in df.columns:
            df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)

    # Aggregate by cusip (a fund may have multiple entries)
    curr_agg = current_q.groupby("cusip").agg({
        "shares": "sum",
        "issuer_name": "first",
    }).reset_index()
    prior_agg = prior_q.groupby("cusip").agg({
        "shares": "sum",
        "issuer_name": "first",
    }).reset_index()

    merged = curr_agg.merge(
        prior_agg, on="cusip", how="outer", suffixes=("_curr", "_prior")
    )
    merged["shares_curr"] = merged["shares_curr"].fillna(0)
    merged["shares_prior"] = merged["shares_prior"].fillna(0)
    merged["share_change"] = merged["shares_curr"] - merged["shares_prior"]

    # Classify
    def classify(row):
        if row["shares_prior"] == 0 and row["shares_curr"] > 0:
            return "new_position"
        elif row["shares_curr"] == 0 and row["shares_prior"] > 0:
            return "exit_position"
        elif row["share_change"] > 0:
            return "increase"
        elif row["share_change"] < 0:
            return "decrease"
        return "unchanged"

    merged["trade_direction"] = merged.apply(classify, axis=1)

    # Filter out unchanged
    trades = merged[merged["trade_direction"] != "unchanged"].copy()
    trades["issuer_name"] = trades["issuer_name_curr"].fillna(trades["issuer_name_prior"])
    trades = trades[["cusip", "issuer_name", "shares_curr", "shares_prior",
                      "share_change", "trade_direction"]]

    return trades


def collect_all(start_year: int = 2023, end_year: int = 2025):
    """
    Download 13-F data for a range of quarters and infer trades.
    """
    all_quarters = []
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            df = collect_quarter(year, quarter)
            if not df.empty:
                all_quarters.append((year, quarter, df))

    # Infer trades between consecutive quarters
    all_trades = []
    for i in range(1, len(all_quarters)):
        prior_y, prior_q, prior_df = all_quarters[i - 1]
        curr_y, curr_q, curr_df = all_quarters[i]

        trades = infer_trades(curr_df, prior_df)
        if not trades.empty:
            trades["from_period"] = f"{prior_y}Q{prior_q}"
            trades["to_period"] = f"{curr_y}Q{curr_q}"
            all_trades.append(trades)

    if all_trades:
        trades_df = pd.concat(all_trades, ignore_index=True)
        out_path = DATA_RAW / "13f" / "institutional_trades_inferred.csv"
        trades_df.to_csv(out_path, index=False)
        log.info(f"Saved {len(trades_df)} inferred institutional trades to {out_path}")
        return trades_df

    return pd.DataFrame()


if __name__ == "__main__":
    collect_all()
