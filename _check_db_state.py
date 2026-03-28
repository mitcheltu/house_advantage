"""Quick check of DB state for contextualizer readiness."""
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    # Quadrant counts
    rows = conn.execute(text(
        "SELECT severity_quadrant, COUNT(*) as cnt FROM anomaly_scores GROUP BY severity_quadrant ORDER BY cnt DESC"
    )).mappings().all()
    print("=== Anomaly Scores by Quadrant ===")
    for r in rows:
        print(f"  {r['severity_quadrant']}: {r['cnt']}")

    # audit_reports
    cnt = conn.execute(text("SELECT COUNT(*) FROM audit_reports")).scalar()
    print(f"\n=== audit_reports: {cnt} rows ===")

    # Top SEVERE/SYSTEMIC
    rows2 = conn.execute(text("""
        SELECT t.id, t.ticker, t.trade_date, a.severity_quadrant, a.cohort_index, a.baseline_index
        FROM trades t JOIN anomaly_scores a ON a.trade_id = t.id
        WHERE a.severity_quadrant IN ('SEVERE', 'SYSTEMIC')
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
        LIMIT 10
    """)).mappings().all()
    print(f"\n=== Top 10 SEVERE/SYSTEMIC trades ===")
    for r in rows2:
        print(f"  trade_id={r['id']} ticker={r['ticker']} date={r['trade_date']} quad={r['severity_quadrant']} cohort={r['cohort_index']} baseline={r['baseline_index']}")

    # Total SEVERE + SYSTEMIC
    total = conn.execute(text(
        "SELECT COUNT(*) FROM anomaly_scores WHERE severity_quadrant IN ('SEVERE', 'SYSTEMIC')"
    )).scalar()
    print(f"\n=== Total SEVERE+SYSTEMIC: {total} ===")

    # Table schema
    cols = conn.execute(text("SHOW COLUMNS FROM audit_reports")).fetchall()
    print(f"\n=== audit_reports columns ===")
    for c in cols:
        print(f"  {c[0]} {c[1]}")

    # Check bills table
    bill_cnt = conn.execute(text("SELECT COUNT(*) FROM bills")).scalar()
    print(f"\n=== bills: {bill_cnt} rows ===")
