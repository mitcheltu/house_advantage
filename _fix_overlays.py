"""
Generate citation_image_prompts for trades missing them (no sector => no bills),
then create citation images and re-overlay onto existing muxed videos.
"""
import sys, json
sys.path.insert(0, ".")
from pathlib import Path
from dotenv import load_dotenv; load_dotenv(".env")

import os
import google.generativeai as genai
from sqlalchemy import text
from backend.db.connection import get_engine
from backend.gemini.media_generation import generate_citation_image
from backend.gemini.ffmpeg_assembly import overlay_citation_images

OUTPUT_DIR = Path("media/test_video")
CITATIONS_DIR = OUTPUT_DIR / "citations"
CITATIONS_DIR.mkdir(parents=True, exist_ok=True)

TRADE_IDS = [3687, 3720, 6537]

PROMPT_TEMPLATE = """
You are a data-visualization designer. Given trade anomaly data, produce exactly 3 
image-generation prompts for dark-themed infographic citation cards.

Each prompt must describe a card with:
- Background: #090d14, text: #e5ebf5, clean sans-serif typography
- Top edge: severity stripe in red (#dc2626)
- 16:9 aspect ratio, high legibility, no photographs, no real faces
- Data visualization style, investigative tone

Card 1: Trade Overview — show ticker, trade type, date, amount, politician name, severity quadrant
Card 2: Anomaly Scores — show cohort_index, baseline_index, key features driving the score  
Card 3: Investigation Summary — show the headline and narrative from the audit report

Output ONLY a JSON array of 3 strings (the prompts). No markdown, no explanation.

Trade Data:
{trade_data}
"""


def get_trade_data(trade_id):
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT t.id as trade_id, t.ticker, t.trade_type, t.trade_date, 
                   t.amount_midpoint, t.industry_sector,
                   p.full_name,
                   a.cohort_index, a.baseline_index, a.severity_quadrant,
                   a.feat_cohort_alpha, a.feat_pre_trade_alpha,
                   a.feat_proximity_days, a.feat_committee_relevance,
                   a.feat_amount_zscore, a.feat_cluster_score,
                   ar.headline, ar.narrative
            FROM trades t
            JOIN anomaly_scores a ON a.trade_id = t.id
            JOIN audit_reports ar ON ar.trade_id = t.id
            LEFT JOIN politicians p ON p.id = t.politician_id
            WHERE t.id = :tid
        """), {"tid": trade_id}).mappings().first()
    return dict(row) if row else None


def generate_prompts_for_trade(trade_data):
    api_key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    # Format trade data for the prompt
    data_str = json.dumps({k: str(v) for k, v in trade_data.items()}, indent=2)
    prompt = PROMPT_TEMPLATE.format(trade_data=data_str)

    response = model.generate_content(prompt)
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def save_prompts_to_db(trade_id, prompts):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE audit_reports SET citation_image_prompts = :cip WHERE trade_id = :tid"),
            {"cip": json.dumps(prompts), "tid": trade_id}
        )


def main():
    for tid in TRADE_IDS:
        print(f"\n{'='*60}")
        print(f"  Trade {tid}")
        print(f"{'='*60}")

        # 1. Get trade data
        trade = get_trade_data(tid)
        if not trade:
            print(f"  SKIP: trade not found")
            continue
        print(f"  {trade['ticker']} | {trade['full_name']} | {trade['severity_quadrant']}")

        # 2. Generate citation image prompts via Gemini
        print(f"  Generating citation prompts...")
        prompts = generate_prompts_for_trade(trade)
        print(f"  Got {len(prompts)} prompts")

        # 3. Save to DB
        save_prompts_to_db(tid, prompts)
        print(f"  Saved to DB")

        # 4. Generate citation images
        citation_paths = []
        for i, prompt in enumerate(prompts[:3]):
            img_path = CITATIONS_DIR / f"trade_{tid}_citation_{i}.png"
            print(f"  Generating citation image {i+1}...")
            result = generate_citation_image(
                prompt=str(prompt),
                output_path=str(img_path),
                aspect_ratio="16:9",
            )
            err = result.get("error")
            if err:
                print(f"    FALLBACK: {err}")
            else:
                citation_paths.append(result.get("path", str(img_path)))
                print(f"    OK: {result.get('path')}")

        if not citation_paths:
            print(f"  NO citation images generated, skipping overlay")
            continue

        # 5. Re-overlay onto existing muxed video
        muxed = OUTPUT_DIR / f"trade_{tid}_muxed.mp4"
        final = OUTPUT_DIR / f"trade_{tid}_final.mp4"
        if not muxed.exists():
            print(f"  SKIP: {muxed} not found")
            continue

        print(f"  Overlaying {len(citation_paths)} citations onto muxed video...")
        try:
            overlay_result = overlay_citation_images(
                video_path=str(muxed),
                citation_image_paths=citation_paths,
                output_path=str(final),
            )
            size_mb = overlay_result.get("file_size_bytes", 0) / 1024 / 1024
            print(f"  DONE: {final} ({size_mb:.1f} MB)")
        except Exception as exc:
            print(f"  OVERLAY FAILED: {exc}")

    print(f"\n{'='*60}")
    print(f"  ALL DONE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
