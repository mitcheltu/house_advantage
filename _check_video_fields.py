"""Check video_prompt and narration_script on SEVERE reports."""
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT trade_id, video_prompt, narration_script "
        "FROM audit_reports WHERE severity_quadrant = 'SEVERE' LIMIT 5"
    )).mappings().all()
    for r in rows:
        d = dict(r)
        vp = d["video_prompt"]
        ns = d["narration_script"]
        print(f"trade_id={d['trade_id']}")
        print(f"  video_prompt: {repr(vp)[:100] if vp else 'NULL'}")
        print(f"  narration_script: {repr(ns)[:100] if ns else 'NULL'}")
        print()
