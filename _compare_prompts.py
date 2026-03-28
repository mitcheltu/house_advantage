"""Compare sanitized video prompts for working vs failing trades."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv(".env")
from backend.gemini.media_generation import _sanitize_prompt_for_veo
from sqlalchemy import text
from backend.db.connection import get_engine

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT trade_id, video_prompt FROM audit_reports "
        "WHERE trade_id IN (8143, 9607, 5326, 3837, 4218, 9600)"
    )).mappings().all()

for r in rows:
    sanitized = _sanitize_prompt_for_veo(r["video_prompt"])
    print(f"=== Trade {r['trade_id']} ===")
    print(sanitized)
    print()
