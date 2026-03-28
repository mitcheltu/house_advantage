"""Check video_prompt and narration_script on SYSTEMIC reports."""
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    # Count nulls vs non-nulls for SYSTEMIC
    rows = conn.execute(text("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN video_prompt IS NOT NULL THEN 1 ELSE 0 END) as has_video,
            SUM(CASE WHEN video_prompt IS NULL THEN 1 ELSE 0 END) as no_video,
            SUM(CASE WHEN narration_script IS NOT NULL THEN 1 ELSE 0 END) as has_narration,
            SUM(CASE WHEN narration_script IS NULL THEN 1 ELSE 0 END) as no_narration
        FROM audit_reports
        WHERE severity_quadrant = 'SYSTEMIC'
    """)).mappings().first()
    d = dict(rows)
    print(f"SYSTEMIC reports: {d['total']}")
    print(f"  video_prompt:    {d['has_video']} have / {d['no_video']} null")
    print(f"  narration_script: {d['has_narration']} have / {d['no_narration']} null")

    # Same for SEVERE
    rows2 = conn.execute(text("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN video_prompt IS NOT NULL THEN 1 ELSE 0 END) as has_video,
            SUM(CASE WHEN video_prompt IS NULL THEN 1 ELSE 0 END) as no_video,
            SUM(CASE WHEN narration_script IS NOT NULL THEN 1 ELSE 0 END) as has_narration,
            SUM(CASE WHEN narration_script IS NULL THEN 1 ELSE 0 END) as no_narration
        FROM audit_reports
        WHERE severity_quadrant = 'SEVERE'
    """)).mappings().first()
    d2 = dict(rows2)
    print(f"\nSEVERE reports: {d2['total']}")
    print(f"  video_prompt:    {d2['has_video']} have / {d2['no_video']} null")
    print(f"  narration_script: {d2['has_narration']} have / {d2['no_narration']} null")
