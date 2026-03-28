"""Verify the contextualizer output for trade 8143."""
import json
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT * FROM audit_reports WHERE trade_id = 8143")).mappings().first()
    if row:
        d = dict(row)
        print(f"headline: {d['headline']}")
        print(f"risk_level: {d['risk_level']}")
        print(f"severity_quadrant: {d['severity_quadrant']}")
        print(f"narrative: {d['narrative'][:300]}...")
        print(f"model: {d['gemini_model']}")
        print(f"tokens: prompt={d['prompt_tokens']}, output={d['output_tokens']}")
        ev = json.loads(d["evidence_json"]) if isinstance(d["evidence_json"], str) else d["evidence_json"]
        print(f"evidence: {json.dumps(ev, indent=2)[:400]}")
        cip = json.loads(d["citation_image_prompts"]) if isinstance(d["citation_image_prompts"], str) else d["citation_image_prompts"]
        print(f"citation_image_prompts: {len(cip)} prompts")
        print(f"video_prompt: {(d['video_prompt'] or '')[:200]}...")
        print(f"narration_script: {(d['narration_script'] or '')[:200]}...")
    else:
        print("NOT FOUND")
