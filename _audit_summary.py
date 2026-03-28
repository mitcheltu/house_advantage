"""Compact summary audit of all contextualizer reports."""
import json
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    # Overall counts
    total = conn.execute(text("SELECT COUNT(*) FROM audit_reports")).scalar()
    severe = conn.execute(text("SELECT COUNT(*) FROM audit_reports WHERE severity_quadrant='SEVERE'")).scalar()
    systemic = conn.execute(text("SELECT COUNT(*) FROM audit_reports WHERE severity_quadrant='SYSTEMIC'")).scalar()

    # Headline length issues
    long_headlines = conn.execute(text(
        "SELECT trade_id, LENGTH(headline) as len FROM audit_reports WHERE LENGTH(headline) > 120"
    )).fetchall()

    # Missing narratives
    missing_narrative = conn.execute(text(
        "SELECT COUNT(*) FROM audit_reports WHERE narrative IS NULL OR narrative = ''"
    )).scalar()

    # Missing evidence
    missing_evidence = conn.execute(text(
        "SELECT COUNT(*) FROM audit_reports WHERE evidence_json IS NULL"
    )).scalar()

    # SEVERE video/narration check
    severe_no_video = conn.execute(text(
        "SELECT COUNT(*) FROM audit_reports WHERE severity_quadrant='SEVERE' AND video_prompt IS NULL"
    )).scalar()
    severe_no_narration = conn.execute(text(
        "SELECT COUNT(*) FROM audit_reports WHERE severity_quadrant='SEVERE' AND narration_script IS NULL"
    )).scalar()

    # Models used
    models = conn.execute(text(
        "SELECT gemini_model, COUNT(*) as cnt FROM audit_reports GROUP BY gemini_model"
    )).fetchall()

    # Token stats
    token_stats = conn.execute(text("""
        SELECT
            SUM(prompt_tokens) as total_prompt,
            SUM(output_tokens) as total_output,
            AVG(prompt_tokens) as avg_prompt,
            AVG(output_tokens) as avg_output,
            MIN(output_tokens) as min_output,
            MAX(output_tokens) as max_output
        FROM audit_reports
    """)).mappings().first()

    # Bills citation stats
    bill_stats = conn.execute(text("""
        SELECT
            SUM(CASE WHEN citation_image_prompts IS NOT NULL AND JSON_LENGTH(citation_image_prompts) > 0 THEN 1 ELSE 0 END) as with_bills,
            SUM(CASE WHEN citation_image_prompts IS NULL OR JSON_LENGTH(citation_image_prompts) = 0 THEN 1 ELSE 0 END) as without_bills
        FROM audit_reports
    """)).mappings().first()

    # Disclaimers
    missing_disclaimer = conn.execute(text(
        "SELECT COUNT(*) FROM audit_reports WHERE disclaimer IS NULL OR disclaimer = ''"
    )).scalar()

    # Score driver distribution
    drivers = conn.execute(text("""
        SELECT JSON_UNQUOTE(JSON_EXTRACT(evidence_json, '$.score_driver')) as driver, COUNT(*) as cnt
        FROM audit_reports
        WHERE evidence_json IS NOT NULL
        GROUP BY driver
    """)).fetchall()

    # Sample 5 diverse narratives (1 SEVERE, 4 SYSTEMIC from different politicians)
    samples = conn.execute(text("""
        (SELECT trade_id, headline, narrative, severity_quadrant, gemini_model
         FROM audit_reports WHERE severity_quadrant='SEVERE' LIMIT 1)
        UNION ALL
        (SELECT ar.trade_id, ar.headline, ar.narrative, ar.severity_quadrant, ar.gemini_model
         FROM audit_reports ar
         JOIN trades t ON t.id = ar.trade_id
         JOIN politicians p ON p.id = t.politician_id
         WHERE ar.severity_quadrant='SYSTEMIC'
         ORDER BY ar.id DESC LIMIT 4)
    """)).mappings().all()

print("=" * 70)
print(f"  CONTEXTUALIZER RESULTS SUMMARY")
print("=" * 70)
print(f"\n  Total reports:  {total}")
print(f"  SEVERE:         {severe}")
print(f"  SYSTEMIC:       {systemic}")
print(f"\n  --- Quality Checks ---")
print(f"  Headlines > 120 chars: {len(long_headlines)}")
if long_headlines:
    for h in long_headlines[:5]:
        print(f"    trade_id={h[0]} ({h[1]} chars)")
print(f"  Missing narrative:     {missing_narrative}")
print(f"  Missing evidence_json: {missing_evidence}")
print(f"  Missing disclaimer:    {missing_disclaimer}")
print(f"  SEVERE no video_prompt:    {severe_no_video}")
print(f"  SEVERE no narration_script: {severe_no_narration}")
print(f"\n  --- Models ---")
for m in models:
    print(f"    {m[0]}: {m[1]}")
print(f"\n  --- Tokens ---")
ts = dict(token_stats)
print(f"  Total:   {ts['total_prompt']:,.0f} prompt + {ts['total_output']:,.0f} output = {ts['total_prompt']+ts['total_output']:,.0f}")
print(f"  Average: {ts['avg_prompt']:.0f} prompt + {ts['avg_output']:.0f} output per report")
print(f"  Output range: {ts['min_output']} - {ts['max_output']}")
print(f"\n  --- Bill Citations ---")
bs = dict(bill_stats)
print(f"  With bill citations:    {bs['with_bills']}")
print(f"  Without bill citations: {bs['without_bills']}")
print(f"\n  --- Score Driver Distribution ---")
for d in drivers:
    print(f"    {d[0]}: {d[1]}")
print(f"\n  --- Sample Reports ---")
for s in samples:
    sd = dict(s)
    print(f"\n  [{sd['severity_quadrant']}] trade={sd['trade_id']}")
    print(f"  Headline: {sd['headline']}")
    print(f"  Narrative: {sd['narrative'][:250]}...")
print("\n" + "=" * 70)
