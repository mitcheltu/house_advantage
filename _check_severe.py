import sys, json
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from sqlalchemy import text
from backend.db.connection import get_engine

engine = get_engine()
with engine.connect() as conn:
    row = conn.execute(text("""
        SELECT t.id, t.ticker, p.full_name,
               a.severity_quadrant, a.cohort_index, a.baseline_index,
               LENGTH(ar.video_prompt) as vp_len,
               LENGTH(ar.narration_script) as ns_len,
               LEFT(ar.narration_script, 200) as ns_preview
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        JOIN audit_reports ar ON ar.trade_id = t.id
        LEFT JOIN politicians p ON p.id = t.politician_id
        WHERE a.severity_quadrant = 'SEVERE'
          AND ar.video_prompt IS NOT NULL
          AND ar.narration_script IS NOT NULL
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
        LIMIT 3
    """)).mappings().all()
    for r in row:
        d = dict(r)
        print(f"Trade {d['id']}: {d['ticker']} by {d['full_name']}")
        print(f"  Quadrant: SEVERE (cohort={d['cohort_index']}, baseline={d['baseline_index']})")
        print(f"  Video prompt: {d['vp_len']} chars, Narration: {d['ns_len']} chars")
        print(f"  Narration preview: {d['ns_preview']}")
        print()
