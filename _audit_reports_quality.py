"""Audit the quality of generated contextualizer reports."""
import json
from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT
            ar.trade_id, ar.headline, ar.risk_level, ar.severity_quadrant,
            ar.narrative, ar.evidence_json, ar.bill_excerpt, ar.disclaimer,
            ar.video_prompt, ar.narration_script, ar.citation_image_prompts,
            ar.gemini_model, ar.prompt_tokens, ar.output_tokens,
            t.ticker, t.trade_date, t.trade_type, t.amount_midpoint,
            p.full_name,
            a.cohort_index, a.baseline_index
        FROM audit_reports ar
        JOIN trades t ON t.id = ar.trade_id
        JOIN anomaly_scores a ON a.trade_id = ar.trade_id
        LEFT JOIN politicians p ON p.id = t.politician_id
        ORDER BY ar.id
    """)).mappings().all()

    print(f"=== {len(rows)} Audit Reports Generated ===\n")

    issues = []
    for i, r in enumerate(rows, 1):
        d = dict(r)
        tid = d["trade_id"]
        quad = d["severity_quadrant"]
        is_severe = quad == "SEVERE"

        # Parse JSON fields
        try:
            ev = json.loads(d["evidence_json"]) if isinstance(d["evidence_json"], str) else d["evidence_json"]
        except Exception:
            ev = {}
        try:
            cip = json.loads(d["citation_image_prompts"]) if isinstance(d["citation_image_prompts"], str) else (d["citation_image_prompts"] or [])
        except Exception:
            cip = []

        # Quality checks
        problems = []
        headline = d["headline"] or ""
        if len(headline) > 120:
            problems.append(f"headline too long ({len(headline)} chars)")
        if not headline:
            problems.append("missing headline")
        if not d["narrative"]:
            problems.append("missing narrative")
        if not ev:
            problems.append("empty evidence_json")
        elif not ev.get("key_factors"):
            problems.append("no key_factors in evidence")
        elif not ev.get("score_driver"):
            problems.append("no score_driver in evidence")
        if not d["disclaimer"]:
            problems.append("missing disclaimer")
        if is_severe and not d["video_prompt"]:
            problems.append("SEVERE but no video_prompt")
        if is_severe and not d["narration_script"]:
            problems.append("SEVERE but no narration_script")
        if d["risk_level"] != ("very_high" if is_severe else "high"):
            pass  # not a hard requirement

        # Print summary
        status = "OK" if not problems else "ISSUES"
        print(f"  [{i:>3}] trade={tid:<6} {d['ticker']:<6} {str(d['trade_date']):<12} {quad:<10} "
              f"| {d['full_name'] or 'Unknown':<25} | model={d['gemini_model']:<20} "
              f"| bills_cited={len(cip)} | tokens={d['prompt_tokens'] or 0}+{d['output_tokens'] or 0} "
              f"| {status}")

        if problems:
            for p in problems:
                print(f"        [!] {p}")
            issues.append((tid, problems))

    # Summary
    print(f"\n{'='*70}")
    print(f"  Total reports: {len(rows)}")
    severe = [r for r in rows if r["severity_quadrant"] == "SEVERE"]
    systemic = [r for r in rows if r["severity_quadrant"] == "SYSTEMIC"]
    print(f"  SEVERE: {len(severe)}, SYSTEMIC: {len(systemic)}")

    models = {}
    for r in rows:
        m = r["gemini_model"] or "unknown"
        models[m] = models.get(m, 0) + 1
    print(f"  Models: {models}")

    fallback_count = sum(1 for r in rows if r["gemini_model"] == "fallback")
    print(f"  Fallbacks: {fallback_count}")

    total_prompt = sum(r["prompt_tokens"] or 0 for r in rows)
    total_output = sum(r["output_tokens"] or 0 for r in rows)
    print(f"  Total tokens: {total_prompt} prompt + {total_output} output = {total_prompt + total_output}")

    if issues:
        print(f"\n  [!] {len(issues)} reports with issues")
    else:
        print(f"\n  [OK] All reports passed quality checks")
    print(f"{'='*70}")

    # Show 3 sample narratives
    print(f"\n=== Sample Narratives ===\n")
    for r in rows[:3]:
        d = dict(r)
        print(f"  --- trade={d['trade_id']} {d['ticker']} ({d['severity_quadrant']}) ---")
        print(f"  Headline: {d['headline']}")
        print(f"  Narrative: {d['narrative'][:400]}")
        ev = json.loads(d["evidence_json"]) if isinstance(d["evidence_json"], str) else d["evidence_json"]
        factors = ev.get("key_factors", [])
        print(f"  Key factors: {factors[:5]}")
        print(f"  Score driver: {ev.get('score_driver')}")
        print()
