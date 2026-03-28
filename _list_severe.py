import sys; sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv(".env")
from sqlalchemy import text
from backend.db.connection import get_engine
engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT t.id, t.ticker, p.full_name,
               a.cohort_index, a.baseline_index,
               CASE WHEN ar.video_prompt IS NOT NULL AND ar.narration_script IS NOT NULL THEN true ELSE false END as has_media
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        LEFT JOIN audit_reports ar ON ar.trade_id = t.id
        LEFT JOIN politicians p ON p.id = t.politician_id
        WHERE a.severity_quadrant = 'SEVERE'
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
    """)).mappings().all()
    print(f"Total SEVERE trades: {len(rows)}")
    ids = []
    for r in rows:
        d = dict(r)
        ids.append(str(d['id']))
        ready = "YES" if d['has_media'] else "NO"
        print(f"  Trade {d['id']}: {d['ticker']} by {d['full_name']} | media_ready={ready}")
    print(f"\nAll IDs: {','.join(ids)}")
