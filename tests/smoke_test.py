"""
Smoke test for all collectors — verifies connectivity & basic parsing
without doing a full data pull.

Usage:
    python tests/smoke_test.py              # Test all
    python tests/smoke_test.py house        # Test House scraper only
    python tests/smoke_test.py senate       # Test Senate scraper only
    python tests/smoke_test.py congress     # Test Congress.gov API
    python tests/smoke_test.py fec          # Test OpenFEC API
    python tests/smoke_test.py govinfo      # Test GovInfo API
    python tests/smoke_test.py prices       # Test yfinance
    python tests/smoke_test.py sec13f       # Test SEC 13-F download
    python tests/smoke_test.py figi         # Test OpenFIGI resolution
"""
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("smoke_test")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def test_house():
    """Test House disclosure scraper — download 1 ZIP, parse XML, try 1 PDF."""
    log.info("=" * 50)
    log.info("Testing: House Clerk Disclosure Scraper")
    log.info("=" * 50)

    from backend.ingest.collectors.collect_house_disclosures import (
        download_zip, parse_xml_index, parse_pdf_trades, _download_ptr_pdf
    )

    # Test 1: Download a ZIP (use 2024 — known to exist)
    log.info("1. Downloading 2024 ZIP...")
    zip_path = download_zip(2024)
    if not zip_path:
        log.error("   Failed to download ZIP")
        return FAIL
    log.info(f"   ZIP downloaded: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")

    # Test 2: Parse XML index
    log.info("2. Parsing XML index...")
    filings = parse_xml_index(zip_path)
    log.info(f"   Found {len(filings)} PTR filings")
    if not filings:
        log.error("   No filings found in XML")
        return FAIL

    # Show first 3 filings
    for f in filings[:3]:
        log.info(f"   - {f.get('full_name', '?')} | {f.get('filing_date', '?')} | DocID: {f.get('doc_id', '?')}")

    # Test 3: Try parsing 1 PDF
    log.info("3. Attempting to parse first PTR PDF...")
    test_filing = filings[0]
    doc_id = test_filing.get("doc_id", "")

    from backend.ingest.collectors.collect_house_disclosures import _extract_pdf_from_zip
    pdf_bytes = _extract_pdf_from_zip(zip_path, doc_id)
    if not pdf_bytes:
        log.info("   PDF not in ZIP, trying direct download...")
        pdf_bytes = _download_ptr_pdf(doc_id, 2024)

    if pdf_bytes:
        log.info(f"   PDF loaded: {len(pdf_bytes)} bytes")
        trades = parse_pdf_trades(pdf_bytes, test_filing)
        log.info(f"   Extracted {len(trades)} trades from PDF")
        for t in trades[:3]:
            log.info(f"   - {t.get('ticker')} | {t.get('trade_type')} | {t.get('trade_date')} | ${t.get('amount_lower', '?')}-${t.get('amount_upper', '?')}")
    else:
        log.warning("   Could not load PDF (non-fatal — ZIP may not contain individual PDFs)")

    return PASS


def test_senate():
    """Test Senate eFD scraper — accept agreement, search, parse 1 report."""
    log.info("=" * 50)
    log.info("Testing: Senate eFD Disclosure Scraper")
    log.info("=" * 50)

    from backend.ingest.collectors.collect_senate_disclosures import SenateScraper

    scraper = SenateScraper()

    # Test 1: Accept agreement
    log.info("1. Accepting eFD agreement...")
    if not scraper._accept_agreement():
        log.error("   Failed to accept agreement (site may be down or changed)")
        return FAIL
    log.info("   Agreement accepted")

    # Test 2: Search for recent PTRs (last 90 days)
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%m/%d/%Y")
    start = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")

    log.info(f"2. Searching PTRs from {start} to {end}...")
    filings = scraper.search_ptrs(start_date=start, end_date=end)
    log.info(f"   Found {len(filings)} filings")
    if not filings:
        log.warning("   No filings found (may be legitimate if none filed recently)")
        return PASS  # Not a failure — could be quiet period

    for f in filings[:3]:
        log.info(f"   - {f.get('full_name', '?')} | {f.get('filing_date', '?')}")

    # Test 3: Try parsing first report
    log.info("3. Fetching first report...")
    trades = scraper.get_report_trades(filings[0])
    log.info(f"   Extracted {len(trades)} trades")
    for t in trades[:3]:
        log.info(f"   - {t.get('ticker')} | {t.get('trade_type')} | {t.get('trade_date')}")

    return PASS


def test_congress():
    """Test Congress.gov API — fetch 1 page of members."""
    log.info("=" * 50)
    log.info("Testing: Congress.gov API")
    log.info("=" * 50)

    from backend.ingest.collectors.utils import get_env, rate_limited_get

    api_key = get_env("CONGRESS_GOV_API_KEY")
    log.info("1. Fetching members (limit 5)...")
    resp = rate_limited_get(
        "https://api.congress.gov/v3/member",
        params={"api_key": api_key, "limit": 5, "format": "json"},
        delay=0.5,
    )
    data = resp.json()
    members = data.get("members", [])
    log.info(f"   Got {len(members)} members")
    for m in members[:3]:
        log.info(f"   - {m.get('name', '?')} | {m.get('partyName', '?')} | {m.get('state', '?')}")

    return PASS if members else FAIL


def test_fec():
    """Test OpenFEC API — search 1 candidate."""
    log.info("=" * 50)
    log.info("Testing: OpenFEC API")
    log.info("=" * 50)

    from backend.ingest.collectors.utils import get_env, rate_limited_get

    api_key = get_env("FEC_API_KEY")
    log.info("1. Searching candidates (limit 3)...")
    resp = rate_limited_get(
        "https://api.open.fec.gov/v1/candidates/search/",
        params={"api_key": api_key, "per_page": 3, "election_year": 2024, "office": "S"},
        delay=1.0,
    )
    data = resp.json()
    results = data.get("results", [])
    log.info(f"   Got {len(results)} candidates")
    for c in results:
        log.info(f"   - {c.get('name', '?')} | {c.get('party_full', '?')} | {c.get('state', '?')}")

    return PASS if results else FAIL


def test_govinfo():
    """Test GovInfo API — fetch 1 page of bills."""
    log.info("=" * 50)
    log.info("Testing: GovInfo API")
    log.info("=" * 50)

    from backend.ingest.collectors.utils import get_env, rate_limited_get

    api_key = get_env("GOVINFO_API_KEY")
    log.info("1. Fetching BILLS collection (limit 3)...")
    resp = rate_limited_get(
        "https://api.govinfo.gov/collections/BILLS/2025-01-01T00:00:00Z",
        params={"api_key": api_key, "pageSize": 3, "congress": 119, "offset": 0},
        delay=1.0,
    )
    data = resp.json()
    packages = data.get("packages", [])
    log.info(f"   Got {len(packages)} packages")
    for p in packages[:3]:
        log.info(f"   - {p.get('packageId', '?')} | {p.get('title', '?')[:60]}")

    return PASS if packages else FAIL


def test_prices():
    """Test yfinance — download 5 days of SPY."""
    log.info("=" * 50)
    log.info("Testing: yfinance (SPY)")
    log.info("=" * 50)

    import yfinance as yf
    log.info("1. Downloading 5 days of SPY...")
    data = yf.download("SPY", period="5d", progress=False)
    log.info(f"   Got {len(data)} rows")
    if not data.empty:
        close_val = data['Close'].iloc[-1].item()
        log.info(f"   Latest close: ${close_val:.2f}")
        return PASS
    return FAIL


def test_sec13f():
    """Test SEC 13-F — try downloading latest available file."""
    log.info("=" * 50)
    log.info("Testing: SEC 13-F Bulk Download")
    log.info("=" * 50)

    from backend.ingest.collectors.collect_sec_13f import _download_latest
    log.info("1. Downloading latest 13-F ZIP...")
    data = _download_latest()
    if data:
        log.info(f"   Downloaded {len(data) / 1e6:.1f} MB")
        return PASS
    log.warning("   Could not download (site may be unreachable)")
    return FAIL


def test_figi():
    """Test OpenFIGI — resolve 1 CUSIP."""
    log.info("=" * 50)
    log.info("Testing: OpenFIGI v3")
    log.info("=" * 50)

    from backend.ingest.collectors.collect_openfigi import resolve_cusips
    # AAPL CUSIP: 037833100
    log.info("1. Resolving AAPL CUSIP (037833100)...")
    result = resolve_cusips(["037833100"])
    if result:
        info = list(result.values())[0]
        log.info(f"   Resolved: {info.get('ticker')} | {info.get('name')} | {info.get('exchange')}")
        return PASS
    log.warning("   Resolution failed")
    return FAIL


TESTS = {
    "house": ("House Disclosures", test_house),
    "senate": ("Senate Disclosures", test_senate),
    "congress": ("Congress.gov API", test_congress),
    "fec": ("OpenFEC API", test_fec),
    "govinfo": ("GovInfo API", test_govinfo),
    "prices": ("yfinance", test_prices),
    "sec13f": ("SEC 13-F", test_sec13f),
    "figi": ("OpenFIGI", test_figi),
}


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(TESTS.keys())
    results = {}

    for key in targets:
        if key not in TESTS:
            log.error(f"Unknown test: {key}. Options: {', '.join(TESTS.keys())}")
            continue

        name, func = TESTS[key]
        try:
            result = func()
        except Exception as e:
            log.error(f"Test crashed: {e}")
            result = FAIL
        results[key] = result
        log.info("")

    # Summary
    log.info("=" * 50)
    log.info("SMOKE TEST RESULTS")
    log.info("=" * 50)
    for key, status in results.items():
        name = TESTS[key][0]
        icon = {"PASS": "+", "FAIL": "X", "SKIP": "-"}[status]
        log.info(f"  [{icon}] {name}: {status}")

    failed = sum(1 for v in results.values() if v == FAIL)
    if failed:
        log.warning(f"\n{failed} test(s) failed")
        sys.exit(1)
    else:
        log.info("\nAll tests passed!")


if __name__ == "__main__":
    main()
