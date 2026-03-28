"""Check citation_image_prompts for all SEVERE trades."""
import sys, json
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv(".env")
from sqlalchemy import text
from backend.db.connection import get_engine

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT trade_id, citation_image_prompts "
        "FROM audit_reports "
        "WHERE trade_id IN (SELECT trade_id FROM anomaly_scores WHERE severity_quadrant='SEVERE') "
        "ORDER BY trade_id"
    )).mappings().all()
    for r in rows:
        tid = r["trade_id"]
        cip = r["citation_image_prompts"]
        if isinstance(cip, str):
            try:
                parsed = json.loads(cip)
            except:
                parsed = cip
        else:
            parsed = cip
        count = len(parsed) if isinstance(parsed, list) else 0
        preview = str(cip)[:80] if cip else "NULL"
        print(f"Trade {tid}: {count} prompts | {preview}")
