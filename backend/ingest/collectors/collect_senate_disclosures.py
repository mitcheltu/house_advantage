"""
Senate eFD Scraper — Congressional Stock Trades (Senate)

Scrapes Periodic Transaction Reports (PTRs) from the Senate's
Electronic Financial Disclosures system via the DataTables AJAX API.

Source: https://efdsearch.senate.gov/search/
Requires: cloudscraper (to bypass Akamai CDN)
"""
import logging
import re
import time
from datetime import datetime

import cloudscraper
import pandas as pd
from bs4 import BeautifulSoup

from .utils import DATA_RAW

log = logging.getLogger("collector.senate_disclosures")

EFD_HOME_URL = "https://efdsearch.senate.gov/search/home/"
EFD_SEARCH_URL = "https://efdsearch.senate.gov/search/"
EFD_REPORT_DATA_URL = "https://efdsearch.senate.gov/search/report/data/"
EFD_BASE = "https://efdsearch.senate.gov"

DISC_DIR = DATA_RAW / "disclosures" / "senate"

AMOUNT_PATTERNS = [
    (r"\$1,001\s*[-–]\s*\$15,000",        1_001,     15_000),
    (r"\$15,001\s*[-–]\s*\$50,000",        15_001,    50_000),
    (r"\$50,001\s*[-–]\s*\$100,000",       50_001,    100_000),
    (r"\$100,001\s*[-–]\s*\$250,000",      100_001,   250_000),
    (r"\$250,001\s*[-–]\s*\$500,000",      250_001,   500_000),
    (r"\$500,001\s*[-–]\s*\$1,000,000",    500_001,   1_000_000),
    (r"\$1,000,001\s*[-–]\s*\$5,000,000",  1_000_001, 5_000_000),
    (r"\$5,000,001\s*[-–]\s*\$25,000,000", 5_000_001, 25_000_000),
    (r"Over\s*\$5,000,000",                5_000_001, 50_000_000),
]

TRANSACTION_TYPE_MAP = {
    "purchase": "buy", "buy": "buy",
    "sale": "sell", "sell": "sell",
    "sale (full)": "sell", "sale (partial)": "sell",
    "exchange": "exchange",
}

TICKER_RE = re.compile(
    r"(?:\(([A-Z]{1,5})\))"
    r"|(?:\[([A-Z]{1,5})\])"
    r"|(?:ticker[:\s]+([A-Z]{1,5}))",
    re.IGNORECASE
)


class SenateScraper:
    """
    Handles the Senate eFD search using cloudscraper (bypasses Akamai CDN)
    and the server-side DataTables AJAX endpoint.
    """

    def __init__(self):
        self.session = cloudscraper.create_scraper()
        self._agreed = False
        self._debug_logged = False

    # ------------------------------------------------------------------
    # Agreement gate
    # ------------------------------------------------------------------
    def _accept_agreement(self) -> bool:
        """Navigate through the eFD agreement page."""
        try:
            resp = self.session.get(EFD_HOME_URL, timeout=30)
            if resp.status_code != 200:
                log.error(f"Failed to load eFD home: {resp.status_code}")
                return False

            soup = BeautifulSoup(resp.text, "html.parser")
            csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
            token = csrf_input["value"] if csrf_input else ""

            agree_resp = self.session.post(
                EFD_HOME_URL,
                data={
                    "csrfmiddlewaretoken": token,
                    "prohibition_agreement": "1",
                },
                headers={
                    "Referer": EFD_HOME_URL,
                    "Origin": EFD_BASE,
                    "X-CSRFToken": self.session.cookies.get("csrftoken", ""),
                },
                timeout=30,
                allow_redirects=True,
            )

            if agree_resp.status_code == 200:
                # Verify we got past the agreement
                s2 = BeautifulSoup(agree_resp.text, "html.parser")
                if not s2.find("input", {"name": "prohibition_agreement"}):
                    self._agreed = True
                    log.info("Accepted Senate eFD agreement")
                    return True

            log.error("Agreement acceptance failed")
            return False

        except Exception as e:
            log.error(f"Failed to accept eFD agreement: {e}")
            return False

    # ------------------------------------------------------------------
    # Search via DataTables AJAX
    # ------------------------------------------------------------------
    def search_ptrs(
        self,
        start_date: str = "01/01/2022",
        end_date: str | None = None,
    ) -> list[dict]:
        """
        Search for PTR filings via the DataTables AJAX endpoint.
        Returns list of filing metadata dicts.
        """
        if not self._agreed:
            if not self._accept_agreement():
                return []

        if end_date is None:
            end_date = datetime.now().strftime("%m/%d/%Y")

        log.info(f"Searching Senate PTRs from {start_date} to {end_date}...")

        # First submit the search form so the server stores criteria
        try:
            form_resp = self.session.post(
                EFD_SEARCH_URL,
                data={
                    "first_name": "",
                    "last_name": "",
                    "filer_type": "1",       # Senator
                    "report_type": "11",     # PTR
                    "submitted_start_date": start_date,
                    "submitted_end_date": end_date,
                },
                headers={
                    "Referer": EFD_SEARCH_URL,
                    "Origin": EFD_BASE,
                    "X-CSRFToken": self.session.cookies.get("csrftoken", ""),
                },
                timeout=30,
                allow_redirects=True,
            )
            if form_resp.status_code != 200:
                log.error(f"Form submit returned {form_resp.status_code}")
                return []
        except Exception as e:
            log.error(f"Form submit failed: {e}")
            return []

        time.sleep(1)

        # Paginate through DataTables results
        all_filings: list[dict] = []
        page_start = 0
        page_length = 100

        while True:
            time.sleep(1.5)  # Be polite
            try:
                dt_resp = self.session.post(
                    EFD_REPORT_DATA_URL,
                    data={
                        "draw": str(len(all_filings) // page_length + 1),
                        "start": str(page_start),
                        "length": str(page_length),
                        "report_types": "[11]",
                        "filer_types": "[1]",
                        "submitted_start_date": f"{start_date} 00:00:00",
                        "submitted_end_date": f"{end_date} 23:59:59",
                        "candidate_state": "",
                        "senator_state": "",
                        "office_id": "",
                        "first_name": "",
                        "last_name": "",
                        "order[0][column]": "1",
                        "order[0][dir]": "asc",
                        "search[value]": "",
                    },
                    headers={
                        "Referer": EFD_SEARCH_URL,
                        "Origin": EFD_BASE,
                        "X-CSRFToken": self.session.cookies.get("csrftoken", ""),
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                    },
                    timeout=30,
                )

                if dt_resp.status_code != 200:
                    log.error(f"DataTables returned {dt_resp.status_code}")
                    break

                data = dt_resp.json()
                rows = data.get("data", [])
                total = data.get("recordsFiltered", 0)

                for row in rows:
                    filing = self._parse_dt_row(row)
                    if filing:
                        all_filings.append(filing)

                log.info(f"  Fetched {len(all_filings)}/{total} filings")

                if page_start + page_length >= total:
                    break
                page_start += page_length

            except Exception as e:
                log.error(f"DataTables request failed: {e}")
                break

        log.info(f"Found {len(all_filings)} PTR filings")
        return all_filings

    @staticmethod
    def _parse_dt_row(row: list) -> dict | None:
        """Parse a DataTables row [first, last, office, report_html, date]."""
        if len(row) < 5:
            return None

        first_name = row[0].strip()
        last_name = row[1].strip()

        # Extract report URL from HTML link
        report_html = row[3]
        soup = BeautifulSoup(report_html, "html.parser")
        link = soup.find("a")
        report_url = link["href"] if link else ""
        report_id = report_url.strip("/").split("/")[-1] if report_url else ""

        return {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}".strip(),
            "filing_type": "Periodic Transaction Report",
            "filing_date": row[4].strip(),
            "report_url": report_url,
            "report_id": report_id,
        }

    def get_report_trades(self, filing: dict) -> list[dict]:
        """
        Fetch and parse an individual PTR report page.
        Returns list of trade records.
        """
        report_url = filing.get("report_url", "")
        if not report_url:
            return []

        # Build full URL if relative
        if report_url.startswith("/"):
            report_url = f"https://efdsearch.senate.gov{report_url}"

        try:
            time.sleep(1.5)  # Be polite
            resp = self.session.get(report_url, timeout=30)
            if resp.status_code != 200:
                log.debug(f"Report {filing.get('report_id','?')}: HTTP {resp.status_code}")
                return []

            trades = self._parse_report_page(resp.text, filing)
            if not self._debug_logged and not trades:
                # Log first empty report for diagnostics
                self._debug_logged = True
                from bs4 import BeautifulSoup as _BS
                _soup = _BS(resp.text, "html.parser")
                _tables = _soup.find_all("table")
                _title = _soup.find("title")
                log.info(f"DEBUG first empty report: url={report_url}, "
                         f"status={resp.status_code}, len={len(resp.text)}, "
                         f"tables={len(_tables)}, title={_title.get_text(strip=True) if _title else 'none'}")
                for _ti, _t in enumerate(_tables[:3]):
                    _rows = _t.find_all("tr")
                    if _rows:
                        _hdrs = [th.get_text(strip=True) for th in _rows[0].find_all(["th","td"])]
                        log.info(f"  Table {_ti}: {len(_rows)} rows, headers={_hdrs}")
            return trades

        except Exception as e:
            log.debug(f"Report fetch failed for {filing.get('report_id', '?')}: {e}")
            return []

    def _parse_report_page(self, html: str, filing: dict) -> list[dict]:
        """Parse trades from a Senate PTR report page."""
        soup = BeautifulSoup(html, "html.parser")
        trades = []

        # Check for agreement/redirect page
        if "prohibition_agreement" in html or "Site Under Maintenance" in html:
            log.debug(f"Report {filing.get('report_id','?')}: got agreement/maintenance page")
            return []

        # Detect paper filings (scanned images, no HTML tables)
        carousel = soup.find("div", class_="carousel-inner")
        if carousel:
            images = carousel.find_all("img", class_="filingImage")
            if images:
                self._paper_count = getattr(self, "_paper_count", 0) + 1
                if self._paper_count <= 3:
                    log.info(f"Report {filing.get('report_id','?')}: paper filing "
                             f"({len(images)} scanned pages) — skipping")
                return []

        # Look for transaction tables
        tables = soup.find_all("table")

        if not tables:
            log.debug(f"Report {filing.get('report_id','?')}: no tables found, "
                      f"page length={len(html)}")

        matched_table = False
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Get header
            header_row = rows[0]
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

            if not any(kw in " ".join(headers) for kw in
                       ["transaction", "asset", "amount", "ticker", "owner"]):
                log.debug(f"Report {filing.get('report_id','?')}: skipped table with headers={headers}")
                continue

            matched_table = True

            # Map columns
            # Real headers: #, Transaction Date, Owner, Ticker, Asset Name,
            #               Asset Type, Type, Amount, Comment
            col_map = {}
            for i, h in enumerate(headers):
                if ("asset" in h and "type" not in h) or "description" in h:
                    col_map["asset"] = i
                elif "asset" in h and "type" in h:
                    col_map["asset_type"] = i          # "Asset Type" (Stock, etc.)
                elif "ticker" in h or "symbol" in h:
                    col_map["ticker"] = i
                elif "transaction" in h and "date" in h:
                    col_map["transaction_date"] = i
                elif "transaction" in h and "type" in h:
                    col_map["type"] = i
                elif h == "type":
                    col_map.setdefault("type", i)      # bare "Type" = transaction type
                elif "type" in h:
                    pass                               # skip other *type* columns
                elif "date" in h and "notification" not in h:
                    col_map.setdefault("transaction_date", i)
                elif "notification" in h or "disclosure" in h:
                    col_map["disclosure_date"] = i
                elif "amount" in h:
                    col_map["amount"] = i
                elif "owner" in h:
                    col_map["owner"] = i
                elif "comment" in h:
                    col_map["comment"] = i

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue

                trade = self._extract_senate_trade(cells, col_map, filing)
                if trade:
                    trades.append(trade)

        return trades

    def _extract_senate_trade(self, cells, col_map: dict, filing: dict) -> dict | None:
        """Extract a single trade from a table row."""
        def get_cell(field):
            idx = col_map.get(field)
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(strip=True)
            return ""

        asset_name = get_cell("asset")

        # Ticker — try explicit column first, then extract from asset name
        ticker = None
        ticker_cell = get_cell("ticker")
        if ticker_cell and ticker_cell not in ("--", "—", "N/A", ""):
            clean = ticker_cell.upper().strip()
            if clean.isalpha() and 1 <= len(clean) <= 5:
                ticker = clean

        if not ticker:
            ticker = _extract_ticker_from_text(asset_name)

        if not ticker:
            ticker = _company_name_to_ticker(asset_name)

        # Asset type — skip clearly non-equity assets
        asset_type_cell = get_cell("asset_type").lower()
        _SKIP_ASSET_TYPES = {
            "municipal bond", "municipal security", "corporate bond",
            "bank deposit", "real estate", "real property",
            "non-public stock", "private equity",
        }
        if asset_type_cell in _SKIP_ASSET_TYPES:
            return None

        if not ticker:
            return None

        # Transaction type
        tx_raw = get_cell("type").lower().strip()
        trade_type = None
        for key, val in TRANSACTION_TYPE_MAP.items():
            if key in tx_raw:
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
            "chamber": "Senate",
            "state_district": "",
            "ticker": ticker,
            "company_name": asset_name,
            "trade_type": trade_type,
            "trade_date": trade_date,
            "disclosure_date": disclosure_date,
            "amount_lower": amount_lower,
            "amount_upper": amount_upper,
            "amount_midpoint": (amount_lower + amount_upper) // 2,
            "asset_type": "stock",
            "doc_id": filing.get("report_id", ""),
            "source": "senate_efd",
        }


def _extract_ticker_from_text(text: str) -> str | None:
    """Extract ticker symbol from asset description."""
    if not text:
        return None
    match = TICKER_RE.search(text)
    if match:
        ticker = next((g for g in match.groups() if g), None)
        if ticker and ticker.upper().isalpha():
            return ticker.upper()
    return None


# Common company name fragments → ticker (case-insensitive matching)
_COMPANY_TICKER_MAP = {
    "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN",
    "alphabet": "GOOGL", "google": "GOOGL", "meta platform": "META",
    "facebook": "META", "tesla": "TSLA", "nvidia": "NVDA",
    "starbuck": "SBUX", "jpmorgan": "JPM", "j.p. morgan": "JPM",
    "bank of america": "BAC", "wells fargo": "WFC", "citigroup": "C",
    "goldman sachs": "GS", "morgan stanley": "MS",
    "johnson & johnson": "JNJ", "johnson and johnson": "JNJ",
    "procter & gamble": "PG", "procter and gamble": "PG",
    "pfizer": "PFE", "eli lilly": "LLY", "merck": "MRK",
    "abbvie": "ABBV", "unitedhealth": "UNH", "chevron": "CVX",
    "exxon": "XOM", "conocophillips": "COP",
    "walt disney": "DIS", "disney": "DIS",
    "netflix": "NFLX", "visa": "V", "mastercard": "MA",
    "coca-cola": "KO", "coca cola": "KO", "pepsi": "PEP",
    "pepsico": "PEP", "boeing": "BA", "lockheed": "LMT",
    "raytheon": "RTX", "general dynamics": "GD", "northrop": "NOC",
    "caterpillar": "CAT", "deere": "DE", "john deere": "DE",
    "home depot": "HD", "walmart": "WMT", "costco": "COST",
    "target": "TGT", "salesforce": "CRM", "adobe": "ADBE",
    "intel": "INTC", "amd": "AMD", "advanced micro": "AMD",
    "broadcom": "AVGO", "qualcomm": "QCOM", "cisco": "CSCO",
    "ibm": "IBM", "oracle": "ORCL", "palantir": "PLTR",
    "snowflake": "SNOW", "uber": "UBER", "airbnb": "ABNB",
    "coinbase": "COIN", "robinhood": "HOOD", "paypal": "PYPL",
    "at&t": "T", "verizon": "VZ", "t-mobile": "TMUS",
    "comcast": "CMCSA", "ford": "F", "general motors": "GM",
    "3m": "MMM",
}


def _company_name_to_ticker(name: str) -> str | None:
    """Try to resolve a company name to a ticker via known mappings."""
    if not name:
        return None
    lower = name.lower().strip()
    for fragment, ticker in _COMPANY_TICKER_MAP.items():
        if fragment in lower:
            return ticker
    return None


def _parse_date(date_str: str) -> str | None:
    """Parse date string to YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        dt = pd.to_datetime(date_str, format="mixed", dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_amount(text: str) -> tuple[int, int]:
    """Parse amount range."""
    if not text:
        return 1_001, 15_000
    for pattern, lo, hi in AMOUNT_PATTERNS:
        if re.search(pattern, text):
            return lo, hi
    return 1_001, 15_000


def collect_senate_trades(
    start_year: int = 2022,
    end_year: int = 2026,
) -> pd.DataFrame:
    """
    Full Senate disclosure collection pipeline.
    Saves to data/raw/senate_trades_raw.csv
    """
    DISC_DIR.mkdir(parents=True, exist_ok=True)

    scraper = SenateScraper()
    all_trades = []

    for year in range(start_year, end_year + 1):
        start_date = f"01/01/{year}"
        end_date = f"12/31/{year}" if year < datetime.now().year else datetime.now().strftime("%m/%d/%Y")

        log.info(f"Collecting Senate PTRs for {year}...")
        filings = scraper.search_ptrs(start_date=start_date, end_date=end_date)

        for i, filing in enumerate(filings):
            trades = scraper.get_report_trades(filing)
            all_trades.extend(trades)

            if (i + 1) % 50 == 0:
                log.info(f"  {year}: processed {i + 1}/{len(filings)} reports, "
                         f"{len(all_trades)} trades so far")

        log.info(f"  {year}: {len(filings)} reports → "
                 f"{sum(1 for t in all_trades if str(t.get('trade_date', '')).startswith(str(year)))} trades")

    df = pd.DataFrame(all_trades)

    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df["disclosure_date"] = pd.to_datetime(df["disclosure_date"], errors="coerce")
        df["disclosure_lag_days"] = (df["disclosure_date"] - df["trade_date"]).dt.days

        df = df.dropna(subset=["ticker", "trade_type"])
        df = df.drop_duplicates(
            subset=["politician_name", "ticker", "trade_date", "trade_type"]
        )

    out_path = DATA_RAW / "senate_trades_raw.csv"
    df.to_csv(out_path, index=False)
    paper = getattr(scraper, "_paper_count", 0)
    if paper:
        log.info(f"Skipped {paper} paper filings (scanned images, not electronic)")
    log.info(f"Saved {len(df)} Senate trades to {out_path}")
    return df


if __name__ == "__main__":
    collect_senate_trades()
