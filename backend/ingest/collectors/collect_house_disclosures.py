"""
House Financial Disclosure Scraper — Congressional Stock Trades (House)

Downloads annual ZIP files from the House Clerk's disclosure site,
parses the XML index for filing metadata, then extracts trade details
from PTR (Periodic Transaction Report) PDFs.

Source: https://disclosures-clerk.house.gov/PublicDisclosure/FinancialDisclosure
ZIPs:   https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.zip
"""
import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd
import requests

from .utils import DATA_RAW

log = logging.getLogger("collector.house_disclosures")

HOUSE_ZIP_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
HOUSE_PTR_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"

# Where we store downloaded/extracted data
DISC_DIR = DATA_RAW / "disclosures" / "house"
ZIP_DIR = DISC_DIR / "zips"
EXTRACT_DIR = DISC_DIR / "extracted"

# Amount range parsing — matches ranges in House PTR PDFs
AMOUNT_PATTERNS = [
    (r"\$1,001\s*[-–]\s*\$15,000",       1_001,    15_000),
    (r"\$15,001\s*[-–]\s*\$50,000",       15_001,   50_000),
    (r"\$50,001\s*[-–]\s*\$100,000",      50_001,   100_000),
    (r"\$100,001\s*[-–]\s*\$250,000",     100_001,  250_000),
    (r"\$250,001\s*[-–]\s*\$500,000",     250_001,  500_000),
    (r"\$500,001\s*[-–]\s*\$1,000,000",   500_001,  1_000_000),
    (r"\$1,000,001\s*[-–]\s*\$5,000,000", 1_000_001, 5_000_000),
    (r"Over\s*\$5,000,000",               5_000_001, 50_000_000),
    (r"\$5,000,001\s*[-–]\s*\$25,000,000", 5_000_001, 25_000_000),
    (r"\$25,000,001\s*[-–]\s*\$50,000,000", 25_000_001, 50_000_000),
]

# Ticker extraction pattern - matches stock tickers in parentheses or after common markers
TICKER_RE = re.compile(
    r"(?:\(([A-Z]{1,5})\))"           # (AAPL) in parentheses
    r"|(?:\[([A-Z]{1,5})\])"          # [AAPL] in brackets
    r"|(?:ticker:\s*([A-Z]{1,5}))"    # ticker: AAPL
    r"|(?:Stock\s*[-–]\s*([A-Z]{1,5}))",  # Stock - AAPL
    re.IGNORECASE
)

TRANSACTION_TYPE_MAP = {
    "p": "buy", "purchase": "buy", "buy": "buy",
    "s": "sell", "sale": "sell", "sell": "sell",
    "s (partial)": "sell", "sale (partial)": "sell",
    "s (full)": "sell", "sale (full)": "sell",
    "e": "exchange", "exchange": "exchange",
}


def _ensure_dirs():
    """Create local storage directories."""
    for d in [ZIP_DIR, EXTRACT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def download_zip(year: int) -> Path | None:
    """
    Download the annual House FD ZIP if not already cached.
    Returns path to the local ZIP file.
    """
    _ensure_dirs()
    local_path = ZIP_DIR / f"{year}FD.zip"

    if local_path.exists() and local_path.stat().st_size > 1000:
        log.info(f"Using cached ZIP: {local_path.name} ({local_path.stat().st_size / 1e6:.1f} MB)")
        return local_path

    url = HOUSE_ZIP_URL.format(year=year)
    log.info(f"Downloading {url}...")

    try:
        resp = requests.get(url, timeout=120, stream=True,
                            headers={"User-Agent": "CorruptionPulse/1.0"})
        if resp.status_code == 404:
            log.warning(f"No ZIP available for {year} (404)")
            return None
        resp.raise_for_status()

        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        log.info(f"Saved {local_path.name} ({local_path.stat().st_size / 1e6:.1f} MB)")
        return local_path

    except requests.RequestException as e:
        log.error(f"Download failed for {year}: {e}")
        return None


def parse_xml_index(zip_path: Path) -> list[dict]:
    """
    Extract and parse the XML index from the House FD ZIP.
    Returns list of filing metadata dicts.
    """
    with zipfile.ZipFile(zip_path) as zf:
        # Find the XML file
        xml_files = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_files:
            log.warning(f"No XML index found in {zip_path.name}")
            return []

        with zf.open(xml_files[0]) as f:
            xml_content = f.read()

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        log.error(f"XML parse error: {e}")
        return []

    filings = []
    # The XML structure typically has <Member> elements
    for member in root.iter("Member"):
        filing = {}
        for child in member:
            tag = child.tag.strip()
            text = (child.text or "").strip()
            if tag == "Prefix":
                filing["prefix"] = text
            elif tag == "Last":
                filing["last_name"] = text
            elif tag == "First":
                filing["first_name"] = text
            elif tag == "Suffix":
                filing["suffix"] = text
            elif tag == "FilingType":
                filing["filing_type"] = text
            elif tag == "StateDst":
                filing["state_district"] = text
            elif tag == "Year":
                filing["year"] = text
            elif tag == "FilingDate":
                filing["filing_date"] = text
            elif tag == "DocID":
                filing["doc_id"] = text

        # Only keep PTR filings (Periodic Transaction Reports)
        if filing.get("filing_type", "").upper() in ("P", "PTR"):
            filing["full_name"] = f"{filing.get('first_name', '')} {filing.get('last_name', '')}".strip()
            filings.append(filing)

    log.info(f"Found {len(filings)} PTR filings in XML index")
    return filings


def _extract_pdf_from_zip(zip_path: Path, doc_id: str) -> bytes | None:
    """Try to extract a PDF from the ZIP by doc_id."""
    with zipfile.ZipFile(zip_path) as zf:
        # PDFs might be named {doc_id}.pdf directly
        for name in zf.namelist():
            if doc_id in name and name.lower().endswith(".pdf"):
                return zf.read(name)
    return None


def _download_ptr_pdf(doc_id: str, year: int) -> bytes | None:
    """Download an individual PTR PDF from the House Clerk site."""
    url = HOUSE_PTR_URL.format(year=year, doc_id=doc_id)
    try:
        resp = requests.get(url, timeout=30,
                            headers={"User-Agent": "CorruptionPulse/1.0"})
        if resp.status_code == 200 and len(resp.content) > 500:
            return resp.content
    except requests.RequestException:
        pass
    return None


def parse_pdf_trades(pdf_bytes: bytes, filing: dict) -> list[dict]:
    """
    Extract trade records from a House PTR PDF.
    Uses pdfplumber for table extraction.
    """
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber not installed. Run: pip install pdfplumber")
        return []

    trades = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            all_tables = []

            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"

                tables = page.extract_tables()
                for table in tables:
                    all_tables.append(table)

            # Strategy 1: Parse structured tables
            trades_from_tables = _parse_tables(all_tables, filing)
            if trades_from_tables:
                trades.extend(trades_from_tables)

            # Strategy 2: If no tables found, try text parsing
            if not trades_from_tables:
                trades_from_text = _parse_text(full_text, filing)
                trades.extend(trades_from_text)

    except Exception as e:
        log.debug(f"PDF parse error for {filing.get('doc_id', '?')}: {e}")

    return trades


def _parse_tables(tables: list, filing: dict) -> list[dict]:
    """Parse trade data from extracted PDF tables."""
    trades = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        # Try to identify the header row
        header = None
        data_rows = []

        for i, row in enumerate(table):
            if not row:
                continue
            row_text = " ".join(str(c or "").lower() for c in row)

            # Look for header indicators
            if any(kw in row_text for kw in ["transaction", "asset", "amount", "date", "owner"]):
                header = [str(c or "").strip().lower() for c in row]
                data_rows = table[i + 1:]
                break

        if not header:
            # No clear header — try treating first row as header
            header = [str(c or "").strip().lower() for c in table[0]]
            data_rows = table[1:]

        # Map header columns to our fields
        col_map = _map_columns(header)
        if not col_map:
            continue

        for row in data_rows:
            if not row or all(not c for c in row):
                continue

            trade = _extract_trade_from_row(row, col_map, filing)
            if trade:
                trades.append(trade)

    return trades


def _map_columns(header: list[str]) -> dict[str, int]:
    """Map header column names to field names and their indices."""
    mapping = {}
    for i, col in enumerate(header):
        col = col.lower().strip()
        if not col:
            continue

        if "asset" in col or "description" in col or "security" in col:
            mapping["asset"] = i
        elif "transaction" in col and "type" not in col and "date" not in col:
            mapping["transaction_date"] = i
        elif "type" in col or "transaction type" in col:
            mapping["type"] = i
        elif "notification" in col or "disclosure" in col:
            mapping["disclosure_date"] = i
        elif "date" in col and "transaction" in col:
            mapping["transaction_date"] = i
        elif "date" in col and "disclosure" not in col and "notification" not in col:
            mapping.setdefault("transaction_date", i)
        elif "amount" in col:
            mapping["amount"] = i
        elif "owner" in col:
            mapping["owner"] = i
        elif "ticker" in col or "symbol" in col:
            mapping["ticker"] = i

    return mapping


def _extract_trade_from_row(row: list, col_map: dict, filing: dict) -> dict | None:
    """Extract a trade record from a single table row."""
    def get_cell(field: str) -> str:
        idx = col_map.get(field)
        if idx is not None and idx < len(row):
            return str(row[idx] or "").strip()
        return ""

    # Get asset description and try to extract ticker
    asset = get_cell("asset")
    ticker_cell = get_cell("ticker")

    ticker = None
    if ticker_cell:
        clean = ticker_cell.upper().strip()
        if clean.isalpha() and 1 <= len(clean) <= 5:
            ticker = clean

    if not ticker and asset:
        ticker = _extract_ticker(asset)

    if not ticker:
        return None

    # Transaction type
    tx_type_raw = get_cell("type").lower().strip()
    if not tx_type_raw:
        # Sometimes combined with transaction date column
        tx_combined = get_cell("transaction_date").lower()
        for key in TRANSACTION_TYPE_MAP:
            if key in tx_combined:
                tx_type_raw = key
                break

    trade_type = TRANSACTION_TYPE_MAP.get(tx_type_raw)
    if not trade_type:
        for key, val in TRANSACTION_TYPE_MAP.items():
            if key in tx_type_raw:
                trade_type = val
                break
    if not trade_type:
        return None

    # Dates
    trade_date = _parse_date(get_cell("transaction_date"))
    disclosure_date = _parse_date(get_cell("disclosure_date"))
    if not disclosure_date:
        disclosure_date = _parse_date(filing.get("filing_date", ""))

    # Amount
    amount_text = get_cell("amount")
    amount_lower, amount_upper = _parse_amount(amount_text)

    return {
        "politician_name": filing.get("full_name", ""),
        "first_name": filing.get("first_name", ""),
        "last_name": filing.get("last_name", ""),
        "chamber": "House",
        "state_district": filing.get("state_district", ""),
        "ticker": ticker,
        "company_name": asset,
        "trade_type": trade_type,
        "trade_date": trade_date,
        "disclosure_date": disclosure_date,
        "amount_lower": amount_lower,
        "amount_upper": amount_upper,
        "amount_midpoint": (amount_lower + amount_upper) // 2,
        "asset_type": "stock",
        "doc_id": filing.get("doc_id", ""),
        "source": "house_clerk",
    }


def _parse_text(text: str, filing: dict) -> list[dict]:
    """
    Fallback: extract trades from unstructured PDF text.
    Looks for patterns like ticker symbols near transaction keywords.
    """
    trades = []
    lines = text.split("\n")

    # Look for lines with trade indicators
    current_trade = {}
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # Check for ticker
        ticker_match = TICKER_RE.search(line_clean)
        if ticker_match:
            ticker = next(g for g in ticker_match.groups() if g)
            if ticker:
                current_trade["ticker"] = ticker.upper()
                current_trade["company_name"] = line_clean

        # Check for transaction type
        line_lower = line_clean.lower()
        for key, val in TRANSACTION_TYPE_MAP.items():
            if re.search(rf"\b{re.escape(key)}\b", line_lower):
                current_trade["trade_type"] = val
                break

        # Check for amount
        for pattern, lo, hi in AMOUNT_PATTERNS:
            if re.search(pattern, line_clean):
                current_trade["amount_lower"] = lo
                current_trade["amount_upper"] = hi
                break

        # Check for date
        date_match = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", line_clean)
        if date_match:
            date_str = date_match.group(0)
            if "trade_date" not in current_trade:
                current_trade["trade_date"] = _parse_date(date_str)
            else:
                current_trade["disclosure_date"] = _parse_date(date_str)

        # If we have enough fields, emit a trade
        if current_trade.get("ticker") and current_trade.get("trade_type"):
            trade = {
                "politician_name": filing.get("full_name", ""),
                "first_name": filing.get("first_name", ""),
                "last_name": filing.get("last_name", ""),
                "chamber": "House",
                "state_district": filing.get("state_district", ""),
                "ticker": current_trade.get("ticker", ""),
                "company_name": current_trade.get("company_name", ""),
                "trade_type": current_trade.get("trade_type", ""),
                "trade_date": current_trade.get("trade_date"),
                "disclosure_date": current_trade.get("disclosure_date")
                    or _parse_date(filing.get("filing_date", "")),
                "amount_lower": current_trade.get("amount_lower", 1_001),
                "amount_upper": current_trade.get("amount_upper", 15_000),
                "amount_midpoint": (current_trade.get("amount_lower", 1_001)
                                    + current_trade.get("amount_upper", 15_000)) // 2,
                "asset_type": "stock",
                "doc_id": filing.get("doc_id", ""),
                "source": "house_clerk",
            }
            trades.append(trade)
            current_trade = {}

    return trades


def _extract_ticker(text: str) -> str | None:
    """Extract a stock ticker from asset description text."""
    # Match (AAPL), [AAPL], or standalone tickers
    match = TICKER_RE.search(text)
    if match:
        ticker = next((g for g in match.groups() if g), None)
        if ticker and ticker.upper().isalpha() and 1 <= len(ticker) <= 5:
            return ticker.upper()

    # Look for common patterns: "Common Stock" preceded by company name
    # Try the first capitalized word as a potential ticker
    words = text.split()
    for word in words:
        clean = re.sub(r"[^A-Z]", "", word.upper())
        if clean.isalpha() and 1 <= len(clean) <= 5 and clean == word.upper().strip("()[].,"):
            # Avoid common false positives
            if clean not in {"THE", "AND", "FOR", "INC", "LLC", "LTD", "ETF",
                             "CORP", "CO", "CLASS", "COM", "USD", "NEW", "OLD",
                             "FUND", "TRUST", "BOND", "NOTE", "INDEX"}:
                return clean
    return None


def _parse_date(date_str: str) -> str | None:
    """Parse various date formats into YYYY-MM-DD."""
    if not date_str:
        return None
    date_str = date_str.strip()

    try:
        dt = pd.to_datetime(date_str, format="mixed", dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_amount(text: str) -> tuple[int, int]:
    """Parse amount range from text."""
    if not text:
        return 1_001, 15_000
    for pattern, lo, hi in AMOUNT_PATTERNS:
        if re.search(pattern, text):
            return lo, hi
    return 1_001, 15_000


def collect_house_trades(
    start_year: int = 2022,
    end_year: int = 2026,
    max_pdfs_per_year: int = 2000,
) -> pd.DataFrame:
    """
    Full House disclosure collection pipeline:
    1. Download annual ZIPs
    2. Parse XML index for PTR filings
    3. Extract trade data from PDFs
    4. Save to data/raw/house_trades_raw.csv

    Args:
        start_year: First year to collect
        end_year: Last year to collect (inclusive)
        max_pdfs_per_year: Max PDFs to process per year (safety limit)
    """
    _ensure_dirs()
    all_trades = []

    for year in range(start_year, end_year + 1):
        log.info(f"Processing House disclosures for {year}...")

        # Step 1: Download ZIP
        zip_path = download_zip(year)
        if not zip_path:
            continue

        # Step 2: Parse XML index
        filings = parse_xml_index(zip_path)
        if not filings:
            log.warning(f"No PTR filings found for {year}")
            continue

        log.info(f"Processing {min(len(filings), max_pdfs_per_year)} PTR PDFs for {year}...")

        # Step 3: Extract trades from PDFs
        processed = 0
        for filing in filings[:max_pdfs_per_year]:
            doc_id = filing.get("doc_id", "")
            if not doc_id:
                continue

            # Try ZIP first, then download individually
            pdf_bytes = _extract_pdf_from_zip(zip_path, doc_id)
            if not pdf_bytes:
                pdf_bytes = _download_ptr_pdf(doc_id, year)

            if not pdf_bytes:
                continue

            trades = parse_pdf_trades(pdf_bytes, filing)
            all_trades.extend(trades)
            processed += 1

            if processed % 100 == 0:
                log.info(f"  {year}: processed {processed} PDFs, {len(all_trades)} trades so far")

        log.info(f"  {year}: {processed} PDFs → {sum(1 for t in all_trades if (t.get('trade_date') or '').startswith(str(year)))} trades")

    df = pd.DataFrame(all_trades)

    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df["disclosure_date"] = pd.to_datetime(df["disclosure_date"], errors="coerce")
        df["disclosure_lag_days"] = (df["disclosure_date"] - df["trade_date"]).dt.days

        # Clean
        df = df.dropna(subset=["ticker", "trade_type"])
        df = df.drop_duplicates(
            subset=["politician_name", "ticker", "trade_date", "trade_type"]
        )

    out_path = DATA_RAW / "house_trades_raw.csv"
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} House trades to {out_path}")
    return df


if __name__ == "__main__":
    collect_house_trades()
