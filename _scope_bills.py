"""Scope which bills need enrichment for severe/systemic trades."""
import sys
sys.path.insert(0, ".")
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT a.severity_quadrant, t.industry_sector, COUNT(*) as cnt "
        "FROM anomaly_scores a "
        "JOIN trades t ON a.trade_id = t.id "
        "WHERE a.severity_quadrant IN ('SEVERE', 'SYSTEMIC') "
        "GROUP BY a.severity_quadrant, t.industry_sector "
        "ORDER BY a.severity_quadrant, cnt DESC"
    )).fetchall()

    print("=== Severe/Systemic trades by sector ===")
    total = 0
    sectors = set()
    for row in rows:
        label, sector, cnt = row
        print(f"  {label:10s} | {str(sector):30s} | {cnt}")
        total += cnt
        if sector:
            sectors.add(sector)
    print(f"\nTotal trades: {total}")
    print(f"Unique sectors: {len(sectors)}")
    print(f"Sectors: {sorted(sectors)}")

    # Now check how many bills are in those sectors
    bills_count = conn.execute(text(
        "SELECT COUNT(*) FROM bills"
    )).scalar()
    bills_with_policy = conn.execute(text(
        "SELECT policy_area, COUNT(*) FROM bills "
        "WHERE policy_area IS NOT NULL AND policy_area != '' "
        "GROUP BY policy_area ORDER BY COUNT(*) DESC"
    )).fetchall()
    print(f"\n=== Bills in DB ===")
    print(f"Total bills: {bills_count}")
    print(f"Bills with policy_area assigned:")
    for row in bills_with_policy:
        print(f"  {row[0]:40s} | {row[1]}")

    # Check bills table columns
    null_check = conn.execute(text(
        "SELECT COUNT(*) as total, "
        "SUM(url IS NOT NULL AND url != '') as has_url, "
        "SUM(latest_action IS NOT NULL AND latest_action != '') as has_action, "
        "SUM(origin_chamber IS NOT NULL AND origin_chamber != '') as has_chamber, "
        "SUM(sponsor_bioguide IS NOT NULL AND sponsor_bioguide != '') as has_sponsor "
        "FROM bills"
    )).fetchone()
    print(f"\n=== Bill column population ===")
    print(f"  Total:          {null_check[0]}")
    print(f"  Has URL:        {null_check[1]}")
    print(f"  Has action:     {null_check[2]}")
    print(f"  Has chamber:    {null_check[3]}")
    print(f"  Has sponsor:    {null_check[4]}")
