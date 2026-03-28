"""
Run the Gemini contextualizer on all SEVERE + SYSTEMIC trades.

Usage:
    # Dry run — show what would be processed
    python -m scripts.run_contextualizer --dry-run

    # Run on all flagged trades (default limit 393)
    python -m scripts.run_contextualizer

    # Run only SEVERE trades
    python -m scripts.run_contextualizer --quadrant SEVERE

    # Limit to 10 trades (for testing)
    python -m scripts.run_contextualizer --limit 10

    # Force re-run on already-contextualized trades
    python -m scripts.run_contextualizer --force

    # Filter by trade date
    python -m scripts.run_contextualizer --since 2025-01-01
"""

from __future__ import annotations

import argparse
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from sqlalchemy import text

from backend.db.connection import get_engine
from backend.gemini.contextualizer import contextualize_trade


def _fetch_flagged_trade_ids(
    limit: int,
    quadrant: str | None = None,
    since_date: str | None = None,
    skip_existing: bool = True,
) -> list[dict]:
    """Fetch trade IDs eligible for contextualization."""
    engine = get_engine()

    quadrants = ("SEVERE", "SYSTEMIC")
    if quadrant:
        quadrants = (quadrant.upper(),)

    placeholders = ", ".join(f":q{i}" for i in range(len(quadrants)))
    params: dict = {f"q{i}": q for i, q in enumerate(quadrants)}
    params["limit"] = limit

    where_clauses = [f"a.severity_quadrant IN ({placeholders})"]

    if since_date:
        where_clauses.append("t.trade_date >= :since_date")
        params["since_date"] = since_date

    if skip_existing:
        where_clauses.append("ar.id IS NULL")

    where = " AND ".join(where_clauses)

    sql = text(f"""
        SELECT
            t.id AS trade_id,
            t.ticker,
            t.trade_date,
            a.severity_quadrant,
            a.cohort_index,
            a.baseline_index,
            p.full_name
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        LEFT JOIN politicians p ON p.id = t.politician_id
        LEFT JOIN audit_reports ar ON ar.trade_id = t.id
        WHERE {where}
        ORDER BY
            FIELD(a.severity_quadrant, 'SEVERE', 'SYSTEMIC'),
            GREATEST(a.cohort_index, a.baseline_index) DESC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def _print_summary(trades: list[dict]) -> None:
    """Print a summary table of trades to be contextualized."""
    severe = [t for t in trades if t["severity_quadrant"] == "SEVERE"]
    systemic = [t for t in trades if t["severity_quadrant"] == "SYSTEMIC"]

    print(f"\n{'='*70}")
    print(f"  Trades to contextualize: {len(trades)}")
    print(f"    SEVERE:   {len(severe)}")
    print(f"    SYSTEMIC: {len(systemic)}")
    print(f"{'='*70}\n")

    if not trades:
        print("  No eligible trades found.\n")
        return

    # Header
    print(f"  {'ID':>6}  {'Ticker':<8}  {'Date':<12}  {'Quadrant':<12}  {'Cohort':>6}  {'Base':>6}  {'Politician':<30}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*12}  {'-'*12}  {'-'*6}  {'-'*6}  {'-'*30}")
    for t in trades[:30]:  # Show first 30
        print(
            f"  {t['trade_id']:>6}  {t['ticker']:<8}  {str(t['trade_date']):<12}  "
            f"{t['severity_quadrant']:<12}  {t['cohort_index']:>6}  {t['baseline_index']:>6}  "
            f"{(t['full_name'] or 'Unknown')[:30]:<30}"
        )
    if len(trades) > 30:
        print(f"  ... and {len(trades) - 30} more")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contextualize SEVERE and SYSTEMIC trades with Gemini"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show which trades would be processed without calling Gemini",
    )
    parser.add_argument(
        "--limit", type=int, default=500,
        help="Max trades to process (default: 500)",
    )
    parser.add_argument(
        "--quadrant", choices=["SEVERE", "SYSTEMIC"],
        help="Only process one quadrant",
    )
    parser.add_argument(
        "--since", dest="since_date",
        help="Only trades on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-contextualize trades that already have audit reports",
    )
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="Seconds to wait between Gemini API calls per worker (default: 0)",
    )
    parser.add_argument(
        "--workers", type=int, default=5,
        help="Number of parallel Gemini workers (default: 5)",
    )
    args = parser.parse_args()

    print("\n  House Advantage — Gemini Contextualizer")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Fetch eligible trades
    trades = _fetch_flagged_trade_ids(
        limit=args.limit,
        quadrant=args.quadrant,
        since_date=args.since_date,
        skip_existing=not args.force,
    )

    _print_summary(trades)

    if args.dry_run:
        print("  [DRY RUN] No changes made.\n")
        return

    if not trades:
        return

    # Contextualize trades with parallel workers
    processed = 0
    failed = []
    start = time.time()
    counter_lock = threading.Lock()
    counter = [0]  # mutable counter for threads

    def _process_one(t: dict) -> dict:
        tid = t["trade_id"]
        if args.delay > 0:
            time.sleep(args.delay)
        try:
            result = contextualize_trade(tid, force=args.force)
            with counter_lock:
                counter[0] += 1
                idx = counter[0]
            model = result.get("model", "unknown")
            print(f"  OK [{idx}/{len(trades)}] trade_id={tid} {t['ticker']} ({t['severity_quadrant']}) -> {model}")
            return {"trade_id": tid, "status": "ok"}
        except Exception as exc:
            with counter_lock:
                counter[0] += 1
                idx = counter[0]
            print(f"  FAIL [{idx}/{len(trades)}] trade_id={tid} {t['ticker']} -> {exc}")
            return {"trade_id": tid, "status": "failed", "error": str(exc)}

    workers = min(args.workers, len(trades))
    print(f"  Using {workers} parallel workers\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_process_one, t): t for t in trades}
        for future in as_completed(futures):
            res = future.result()
            if res["status"] == "ok":
                processed += 1
            else:
                failed.append(res)

    elapsed = time.time() - start

    # Final summary
    print(f"\n{'='*70}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Processed: {processed}/{len(trades)}")
    if failed:
        print(f"  Failed:    {len(failed)}")
        for f in failed[:10]:
            print(f"    trade_id={f['trade_id']}: {f['error']}")
    print(f"{'='*70}\n")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
