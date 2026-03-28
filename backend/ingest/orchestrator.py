"""
Data Collection Orchestrator

Runs all collectors in the correct dependency order:
  1.  Congress.gov  → politicians, committees, votes, bills
  1a. Committee Memberships → from unitedstates/congress-legislators repo
  1b. Senate Votes  → from senate.gov XML roll-call data
  2.  House Clerk   → House stock trade disclosures (PDF scraping)
  3.  Senate eFD    → Senate stock trade disclosures (HTML scraping)
  4.  Merge Trades  → combine House + Senate into unified CSV
  5.  OpenFEC       → candidates, finance totals, PAC contributions
  6.  yfinance      → stock prices (needs tickers from trades)
  7.  SEC 13-F      → institutional holdings
  8.  OpenFIGI      → CUSIP-to-ticker mapping (needs CUSIPs from 13-F)
  9.  GovInfo       → bill full text
  10. DB Load       → push all CSVs to MySQL

Usage:
    python -m backend.ingest.orchestrator            # Run all
    python -m backend.ingest.orchestrator --step 2    # Run step 2 only
    python -m backend.ingest.orchestrator --skip-db   # Skip MySQL load
"""
import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("orchestrator")


def step_1_congress():
    """Collect politicians, committees, and bills from Congress.gov."""
    from backend.ingest.collectors.collect_congress_gov import collect_all
    log.info("=" * 60)
    log.info("STEP 1: Congress.gov — Politicians, Committees, Bills")
    log.info("=" * 60)
    collect_all()


def step_1a_committee_memberships():
    """Collect committee memberships from congress-legislators repo."""
    from backend.ingest.collectors.collect_committee_memberships import collect_committee_memberships
    log.info("=" * 60)
    log.info("STEP 1a: Committee Memberships — congress-legislators repo")
    log.info("=" * 60)
    collect_committee_memberships()


def step_1b_senate_votes():
    """Collect Senate roll-call votes from senate.gov XML."""
    from backend.ingest.collectors.collect_senate_votes import collect_senate_votes
    log.info("=" * 60)
    log.info("STEP 1b: Senate Votes — senate.gov XML")
    log.info("=" * 60)
    collect_senate_votes()


def step_2_house():
    """Scrape House financial disclosures from House Clerk."""
    from backend.ingest.collectors.collect_house_disclosures import collect_house_trades
    log.info("=" * 60)
    log.info("STEP 2: House Clerk — House Stock Trade Disclosures")
    log.info("=" * 60)
    collect_house_trades()


def step_3_senate():
    """Scrape Senate financial disclosures from Senate eFD."""
    from backend.ingest.collectors.collect_senate_disclosures import collect_senate_trades
    log.info("=" * 60)
    log.info("STEP 3: Senate eFD — Senate Stock Trade Disclosures")
    log.info("=" * 60)
    collect_senate_trades()


def step_4_merge():
    """Merge House + Senate trades into unified CSV."""
    from backend.ingest.collectors.merge_trades import merge_trades
    log.info("=" * 60)
    log.info("STEP 4: Merge — Combine House + Senate Trades")
    log.info("=" * 60)
    merge_trades()


def step_5_fec():
    """Collect campaign finance data from OpenFEC."""
    from backend.ingest.collectors.collect_openfec import collect_all
    log.info("=" * 60)
    log.info("STEP 5: OpenFEC — Candidates & Campaign Finance")
    log.info("=" * 60)
    collect_all()


def step_6_prices():
    """Download stock prices for tickers found in trade data."""
    from backend.ingest.collectors.collect_prices import collect_prices
    log.info("=" * 60)
    log.info("STEP 6: yfinance — Stock Prices")
    log.info("=" * 60)
    collect_prices()


def step_7_13f():
    """Download SEC 13-F institutional holdings."""
    from backend.ingest.collectors.collect_sec_13f import collect_all
    log.info("=" * 60)
    log.info("STEP 7: SEC 13-F — Institutional Holdings")
    log.info("=" * 60)
    collect_all()


def step_8_figi():
    """Resolve CUSIPs to tickers via OpenFIGI."""
    from backend.ingest.collectors.collect_openfigi import build_cusip_ticker_map
    log.info("=" * 60)
    log.info("STEP 8: OpenFIGI — CUSIP→Ticker Resolution")
    log.info("=" * 60)
    build_cusip_ticker_map()


def step_9_govinfo():
    """Collect bill text from GovInfo."""
    from backend.ingest.collectors.collect_govinfo import collect_all
    log.info("=" * 60)
    log.info("STEP 9: GovInfo — Bill Full Text")
    log.info("=" * 60)
    collect_all()


def step_10_db_load():
    """Load all collected CSVs into MySQL."""
    from backend.db.setup_db import setup_all
    log.info("=" * 60)
    log.info("STEP 10: MySQL — Schema + Data Load")
    log.info("=" * 60)
    setup_all()


STEPS = {
    1:  ("Congress.gov", step_1_congress),
    2:  ("Committee Memberships", step_1a_committee_memberships),
    3:  ("Senate Votes", step_1b_senate_votes),
    4:  ("House Disclosures", step_2_house),
    5:  ("Senate Disclosures", step_3_senate),
    6:  ("Merge Trades", step_4_merge),
    7:  ("OpenFEC", step_5_fec),
    8:  ("yfinance", step_6_prices),
    9:  ("SEC 13-F", step_7_13f),
    10: ("OpenFIGI", step_8_figi),
    11: ("GovInfo", step_9_govinfo),
    12: ("MySQL Load", step_10_db_load),
}


def run_step(step_num: int) -> bool:
    """Run a single step. Returns True on success."""
    name, func = STEPS[step_num]
    start = time.time()
    try:
        func()
        elapsed = time.time() - start
        log.info(f"✓ Step {step_num} ({name}) completed in {elapsed:.1f}s")
        return True
    except Exception as e:
        elapsed = time.time() - start
        log.error(f"✗ Step {step_num} ({name}) FAILED after {elapsed:.1f}s: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="House Advantage Data Orchestrator")
    parser.add_argument("--step", type=int, help="Run a specific step (1-12)")
    parser.add_argument("--from-step", type=int, default=1, help="Start from step N")
    parser.add_argument("--to-step", type=int, default=12, help="End at step N")
    parser.add_argument("--skip-db", action="store_true", help="Skip MySQL load (step 12)")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="Continue to next step even if current fails")
    args = parser.parse_args()

    log.info("House Advantage — Data Collection Orchestrator")
    log.info(f"Steps available: {', '.join(f'{k}={v[0]}' for k, v in STEPS.items())}")

    if args.step:
        if args.step not in STEPS:
            log.error(f"Invalid step: {args.step}. Valid: 1-12")
            sys.exit(1)
        success = run_step(args.step)
        sys.exit(0 if success else 1)

    end_step = 11 if args.skip_db else args.to_step
    results = {}

    for step_num in range(args.from_step, end_step + 1):
        if step_num not in STEPS:
            continue
        success = run_step(step_num)
        results[step_num] = success
        if not success and not args.continue_on_error:
            log.error(f"Stopping at step {step_num}. Use --continue-on-error to proceed.")
            break

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("COLLECTION SUMMARY")
    log.info("=" * 60)
    for step_num, success in results.items():
        name = STEPS[step_num][0]
        status = "OK" if success else "FAILED"
        log.info(f"  Step {step_num} ({name}): {status}")

    failed = sum(1 for v in results.values() if not v)
    if failed:
        log.warning(f"{failed} step(s) failed")
        sys.exit(1)
    else:
        log.info("All steps completed successfully")


if __name__ == "__main__":
    main()
