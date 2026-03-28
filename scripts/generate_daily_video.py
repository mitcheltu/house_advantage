"""
Generate a daily summary video for House Advantage demo.

Full pipeline:
  1. Fetch all SEVERE trades (by date or all)
  2. Generate daily narration + veo prompt via Gemini scriptwriter
  3. Generate citation card images (Nano Banana) from top trades
  4. TTS narration audio
  5. Veo video with content-filter-safe prompt + citation refs
  6. FFmpeg mux audio + video
  7. FFmpeg overlay citation images onto final video

Usage:
    # Use today's date (fetches all SEVERE trades)
    python -m scripts.generate_daily_video

    # Specific date
    python -m scripts.generate_daily_video --date 2026-03-28

    # Skip Veo (placeholder video) — just test TTS + images + mux
    python -m scripts.generate_daily_video --skip-veo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text as sa_text
from backend.db.connection import get_engine

OUTPUT_DIR = PROJECT_ROOT / "data" / "media"
VIDEO_DIR = OUTPUT_DIR / "video"
AUDIO_DIR = OUTPUT_DIR / "audio"
CITATION_DIR = OUTPUT_DIR / "citations"


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# 1) Fetch SEVERE trades (all, not date-filtered — for demo)
# ---------------------------------------------------------------------------

def fetch_severe_trades(limit: int = 12) -> list[dict]:
    engine = get_engine()
    sql = sa_text("""
        SELECT
            t.id AS trade_id,
            t.ticker,
            t.trade_type,
            t.trade_date,
            t.amount_midpoint,
            p.full_name,
            p.party,
            p.state,
            a.cohort_index,
            a.baseline_index,
            a.severity_quadrant,
            ar.id AS audit_report_id,
            ar.headline,
            ar.narrative,
            ar.video_prompt,
            ar.narration_script,
            ar.citation_image_prompts
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        JOIN audit_reports ar ON ar.trade_id = t.id
        LEFT JOIN politicians p ON p.id = t.politician_id
        WHERE a.severity_quadrant = 'SEVERE'
          AND ar.video_prompt IS NOT NULL
          AND ar.narration_script IS NOT NULL
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 2) Generate daily script via Gemini
# ---------------------------------------------------------------------------

DAILY_SCRIPT_PROMPT = """
You are the scriptwriter for House Advantage, a civic accountability platform
that statistically flags suspicious stock trades by U.S. elected officials.

Write a concise, professional daily narration script and a Veo video prompt.
The narration should be ~75-100 words summarizing today's most suspicious trades.
Keep the tone factual, serious, and civic-minded. Never accuse — note these are
statistical anomalies for public review.

The veo prompt should describe cinematic visuals for an investigative news segment:
- Use generic descriptions: "an official", "a government building", "stock charts"
- Do NOT name real people, tickers, or political landmarks
- Keep it under 60 words, suitable for AI video generation

Also generate 2+3 short citation card prompts (one sentence each) summarizing
the most newsworthy trades. These will be rendered as overlay cards.

Return ONLY valid JSON:
{{
  "narration_script": "...",
  "veo_prompt": "...",
  "citation_prompts": ["prompt1", "prompt2", "prompt3"]
}}

Date: {report_date}

Today's SEVERE flagged trades ({count} total):
{items}
""".strip()


def generate_daily_script(report_date: date, trades: list[dict]) -> dict:
    """Use Gemini to write narration, veo prompt, and citation prompts."""
    try:
        import google.generativeai as genai
    except ImportError:
        log("google-generativeai not installed, using fallback")
        return _fallback_script(report_date, trades)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if not api_key:
        log("No GEMINI_API_KEY, using fallback")
        return _fallback_script(report_date, trades)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_name)

    lines = []
    for t in trades[:12]:
        lines.append(
            f"- trade_id={t['trade_id']} | {t.get('full_name') or 'Unknown'} ({t.get('party')}-{t.get('state')}) | "
            f"{t.get('ticker')} {t.get('trade_type')} | "
            f"cohort={t.get('cohort_index'):.2f} baseline={t.get('baseline_index'):.2f}"
        )
        if t.get("headline"):
            lines.append(f"  headline: {t['headline']}")

    prompt = DAILY_SCRIPT_PROMPT.format(
        report_date=report_date.isoformat(),
        count=len(trades),
        items="\n".join(lines) or "- none",
    )

    log(f"Calling {model_name} for daily script...")
    response = model.generate_content(prompt)
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()

    payload = json.loads(raw)
    log(f"Gemini returned script ({len(payload.get('narration_script', ''))} chars)")
    return payload


def _fallback_script(report_date: date, trades: list[dict]) -> dict:
    top = trades[:3]
    mentions = "; ".join(
        f"{t.get('full_name', 'Unknown')} traded {t.get('ticker', '???')} ({t.get('severity_quadrant')})"
        for t in top
    )
    return {
        "narration_script": (
            f"This is House Advantage for {report_date}. "
            f"Today's highest-risk congressional trading activity includes {mentions}. "
            "These flags are statistical anomalies surfaced for public-interest review, "
            "not proof of misconduct. Stay informed."
        ),
        "veo_prompt": (
            "Serious investigative newsroom set, dim blue lighting, "
            "document overlays and stock chart motion graphics scrolling, "
            "data visualization panels, broadcast journalism atmosphere, "
            "16:9 cinematic landscape"
        ),
        "citation_prompts": [
            f"Create a clean data card showing a flagged stock trade by a public official in {t.get('ticker', 'a stock')}, "
            f"with anomaly score indicators and formal civic design."
            for t in top[:3]
        ],
    }


# ---------------------------------------------------------------------------
# 3) Upsert daily_reports row
# ---------------------------------------------------------------------------

def upsert_daily_report(report_date: date, trade_ids: list[int], payload: dict) -> None:
    engine = get_engine()
    sql = sa_text("""
        INSERT INTO daily_reports (
            report_date, trade_ids_covered, narration_script, veo_prompt,
            generation_status, generated_at
        ) VALUES (
            :report_date, :trade_ids_covered, :narration_script, :veo_prompt,
            'pending', CURRENT_TIMESTAMP
        )
        ON DUPLICATE KEY UPDATE
            trade_ids_covered = VALUES(trade_ids_covered),
            narration_script = VALUES(narration_script),
            veo_prompt = VALUES(veo_prompt),
            generation_status = 'pending',
            generated_at = CURRENT_TIMESTAMP
    """)
    with engine.begin() as conn:
        conn.execute(sql, {
            "report_date": report_date,
            "trade_ids_covered": json.dumps(trade_ids),
            "narration_script": payload.get("narration_script"),
            "veo_prompt": payload.get("veo_prompt"),
        })
    log(f"Upserted daily_reports row for {report_date}")


# ---------------------------------------------------------------------------
# 4) Update daily_reports with final media URLs
# ---------------------------------------------------------------------------

def update_daily_report_media(
    report_date: date,
    video_url: str,
    audio_url: str,
    duration_seconds: float | None = None,
    status: str = "ready",
) -> None:
    engine = get_engine()
    sql = sa_text("""
        UPDATE daily_reports
        SET video_url = :video_url,
            audio_url = :audio_url,
            duration_seconds = :duration_seconds,
            generation_status = :status,
            generated_at = CURRENT_TIMESTAMP
        WHERE report_date = :report_date
    """)
    with engine.begin() as conn:
        conn.execute(sql, {
            "report_date": report_date,
            "video_url": video_url,
            "audio_url": audio_url,
            "duration_seconds": duration_seconds,
            "status": status,
        })


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate House Advantage daily video")
    parser.add_argument("--date", default=None, help="Report date YYYY-MM-DD (default: today)")
    parser.add_argument("--skip-veo", action="store_true", help="Use placeholder video (skip Veo)")
    parser.add_argument("--limit", type=int, default=12, help="Max trades to include")
    args = parser.parse_args()

    report_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else datetime.utcnow().date()
    )

    # Ensure output directories
    for d in [VIDEO_DIR, AUDIO_DIR, CITATION_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # -- Stage 1: Fetch SEVERE trades --
    section("Stage 1: Fetching SEVERE trades")
    trades = fetch_severe_trades(limit=args.limit)
    if not trades:
        log("No SEVERE trades with audit reports found. Aborting.")
        sys.exit(1)
    log(f"Found {len(trades)} SEVERE trades")
    for t in trades[:5]:
        log(f"  #{t['trade_id']} {t.get('full_name', '?')} / {t.get('ticker')} "
            f"(cohort={t.get('cohort_index'):.2f}, baseline={t.get('baseline_index'):.2f})")
    if len(trades) > 5:
        log(f"  ... and {len(trades) - 5} more")

    # -- Stage 2: Generate daily script --
    section("Stage 2: Generating daily narration + veo prompt")
    script_payload = generate_daily_script(report_date, trades)

    narration = script_payload["narration_script"]
    veo_prompt = script_payload["veo_prompt"]
    citation_prompts = script_payload.get("citation_prompts", [])

    log(f"Narration ({len(narration.split())} words):")
    log(f"  \"{narration[:200]}...\"" if len(narration) > 200 else f"  \"{narration}\"")
    log(f"Veo prompt: \"{veo_prompt[:150]}...\"" if len(veo_prompt) > 150 else f"Veo prompt: \"{veo_prompt}\"")
    log(f"Citation prompts: {len(citation_prompts)}")

    # Upsert daily_reports
    trade_ids = [int(t["trade_id"]) for t in trades]
    upsert_daily_report(report_date, trade_ids, script_payload)

    # -- Stage 3: Generate citation images (Nano Banana) --
    section("Stage 3: Generating citation card images (Nano Banana)")
    from backend.gemini.media_generation import generate_citation_image

    citation_paths: list[str] = []

    # If no citation prompts from Gemini, build from top trades' existing prompts
    if not citation_prompts:
        log("No citation_prompts from scriptwriter, extracting from top trades...")
        for t in trades[:3]:
            raw = t.get("citation_image_prompts")
            if raw:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list) and parsed:
                        citation_prompts.append(str(parsed[0]))
                except (json.JSONDecodeError, TypeError):
                    pass

    if not citation_prompts:
        log("No citation prompts available, will skip overlay")
    else:
        for idx, prompt in enumerate(citation_prompts[:3]):
            img_path = CITATION_DIR / f"daily_{report_date.isoformat()}_citation_{idx}.png"
            log(f"  Generating citation {idx+1}/{min(len(citation_prompts), 3)}...")
            t0 = time.time()
            meta = generate_citation_image(
                prompt=prompt,
                output_path=str(img_path),
            )
            actual_path = meta.get("path", str(img_path))
            elapsed = time.time() - t0
            size_kb = meta.get("file_size_bytes", 0) / 1024
            provider = meta.get("provider", "unknown")
            log(f"    -> {Path(actual_path).name} ({size_kb:.1f} KB, {elapsed:.1f}s, {provider})")
            if meta.get("error"):
                log(f"    WARNING: {meta['error']}")
            citation_paths.append(actual_path)

    # -- Stage 4: TTS narration --
    section("Stage 4: Synthesizing TTS narration")
    from backend.gemini.media_generation import synthesize_narration_audio

    audio_path = AUDIO_DIR / f"daily_{report_date.isoformat()}_audio.wav"
    log(f"Generating TTS for {len(narration.split())} words...")
    t0 = time.time()
    audio_meta = synthesize_narration_audio(
        script_text=narration,
        output_path=str(audio_path),
    )
    elapsed = time.time() - t0
    duration = audio_meta.get("duration_seconds", 0)
    provider = audio_meta.get("provider", "unknown")
    log(f"  Audio: {audio_path.name} ({duration:.1f}s, {elapsed:.1f}s gen, {provider})")

    # -- Stage 5: Veo video generation --
    section("Stage 5: Generating Veo video")
    from backend.gemini.media_generation import generate_video_from_prompt

    video_path = VIDEO_DIR / f"daily_{report_date.isoformat()}_video.mp4"

    if args.skip_veo:
        log("--skip-veo: using placeholder video")
        os.environ["VEO_PROVIDER"] = "disabled"

    log(f"Generating video (target duration: {duration:.1f}s)...")
    log(f"  Prompt will be sanitized for Veo content filter")
    if citation_paths:
        log(f"  Using {len(citation_paths)} citation image(s) as Veo reference")

    t0 = time.time()
    video_meta = generate_video_from_prompt(
        prompt=veo_prompt,
        output_path=str(video_path),
        duration_seconds=float(duration or 30.0),
        aspect_ratio="16:9",
        reference_image_paths=citation_paths or None,
    )
    elapsed = time.time() - t0
    vsize_kb = Path(str(video_meta.get("path", video_path))).stat().st_size / 1024 if Path(str(video_meta.get("path", video_path))).exists() else 0
    vprovider = video_meta.get("provider", "unknown")
    log(f"  Video: {video_path.name} ({vsize_kb:.1f} KB, {elapsed:.1f}s, {vprovider})")
    if video_meta.get("error"):
        log(f"  WARNING: {video_meta['error']}")

    # -- Stage 6: FFmpeg mux audio + video --
    section("Stage 6: Muxing audio + video")
    from backend.gemini.ffmpeg_assembly import assemble_video_with_audio

    muxed_path = VIDEO_DIR / f"daily_{report_date.isoformat()}_muxed.mp4"
    log("Muxing with FFmpeg...")
    t0 = time.time()
    mux_result = assemble_video_with_audio(
        video_path=str(video_path),
        audio_path=str(audio_path),
        output_path=str(muxed_path),
        overwrite=True,
    )
    elapsed = time.time() - t0
    mux_dur = mux_result.get("duration_seconds", 0)
    mux_size = (mux_result.get("file_size_bytes") or 0) / 1024
    log(f"  Muxed: {muxed_path.name} ({mux_size:.1f} KB, {mux_dur:.1f}s, {elapsed:.1f}s)")

    # -- Stage 7: Citation image overlay --
    section("Stage 7: Overlaying citation images")
    from backend.gemini.ffmpeg_assembly import overlay_citation_images

    final_path = VIDEO_DIR / f"daily_{report_date.isoformat()}_final.mp4"

    if citation_paths:
        log(f"Overlaying {len(citation_paths)} citation card(s)...")
        t0 = time.time()
        overlay_result = overlay_citation_images(
            video_path=str(muxed_path),
            citation_image_paths=citation_paths,
            output_path=str(final_path),
        )
        elapsed = time.time() - t0
        final_size = (overlay_result.get("file_size_bytes") or 0) / 1024
        final_dur = overlay_result.get("duration_seconds") or mux_dur
        log(f"  Final: {final_path.name} ({final_size:.1f} KB, {final_dur:.1f}s, {elapsed:.1f}s)")
    else:
        log("No citations to overlay, copying muxed as final")
        import shutil
        shutil.copy2(str(muxed_path), str(final_path))
        final_dur = mux_dur

    # -- Update DB --
    section("Updating daily_reports")
    update_daily_report_media(
        report_date=report_date,
        video_url=str(final_path),
        audio_url=str(audio_path),
        duration_seconds=final_dur,
        status="ready",
    )
    log("daily_reports updated -> status=ready")

    # -- Summary --
    section("DONE")
    final_size_mb = final_path.stat().st_size / (1024 * 1024) if final_path.exists() else 0
    log(f"Daily video:  {final_path}")
    log(f"Size:         {final_size_mb:.1f} MB")
    log(f"Duration:     {final_dur:.1f}s")
    log(f"Audio:        {audio_path}")
    log(f"Citations:    {len(citation_paths)} cards")
    log(f"Report date:  {report_date}")
    log(f"Trades:       {len(trades)} SEVERE")


if __name__ == "__main__":
    main()
