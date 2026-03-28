"""
Test one SEVERE trade through the full video pipeline:
  1. Fetch audit report (already contextualized)
  2. Generate citation images from saved prompts
  3. Generate TTS audio from narration_script
  4. Generate Veo video from video_prompt (with citation images as references)
  5. FFmpeg mux audio + video -> final.mp4

Usage:
    # Auto-pick the highest-scoring SEVERE trade
    python -m scripts.test_video_pipeline

    # Specific trade
    python -m scripts.test_video_pipeline --trade-id 8143

    # Skip Veo (use placeholder video) — just test TTS + images + mux
    python -m scripts.test_video_pipeline --skip-veo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text as sa_text
from backend.db.connection import get_engine


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def fetch_severe_trade_with_report(trade_id: int | None = None) -> dict | None:
    """Fetch a SEVERE trade that already has an audit_report."""
    engine = get_engine()

    if trade_id:
        sql = sa_text("""
            SELECT
                t.id AS trade_id, t.ticker, t.trade_date, t.trade_type,
                p.full_name,
                a.severity_quadrant, a.cohort_index, a.baseline_index,
                ar.id AS audit_report_id,
                ar.headline, ar.narrative,
                ar.video_prompt, ar.narration_script,
                ar.citation_image_prompts
            FROM trades t
            JOIN anomaly_scores a ON a.trade_id = t.id
            JOIN audit_reports ar ON ar.trade_id = t.id
            LEFT JOIN politicians p ON p.id = t.politician_id
            WHERE t.id = :trade_id
            LIMIT 1
        """)
        params = {"trade_id": trade_id}
    else:
        sql = sa_text("""
            SELECT
                t.id AS trade_id, t.ticker, t.trade_date, t.trade_type,
                p.full_name,
                a.severity_quadrant, a.cohort_index, a.baseline_index,
                ar.id AS audit_report_id,
                ar.headline, ar.narrative,
                ar.video_prompt, ar.narration_script,
                ar.citation_image_prompts
            FROM trades t
            JOIN anomaly_scores a ON a.trade_id = t.id
            JOIN audit_reports ar ON ar.trade_id = t.id
            LEFT JOIN politicians p ON p.id = t.politician_id
            WHERE a.severity_quadrant = 'SEVERE'
              AND ar.video_prompt IS NOT NULL
              AND ar.narration_script IS NOT NULL
            ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
            LIMIT 1
        """)
        params = {}

    with engine.connect() as conn:
        row = conn.execute(sql, params).mappings().first()
    if not row:
        return None
    d = dict(row)
    # Parse citation_image_prompts from JSON
    cip = d.get("citation_image_prompts")
    if isinstance(cip, str):
        try:
            d["citation_image_prompts"] = json.loads(cip)
        except Exception:
            d["citation_image_prompts"] = []
    elif not isinstance(cip, list):
        d["citation_image_prompts"] = cip if cip else []
    return d


def main() -> None:
    parser = argparse.ArgumentParser(description="Test full video pipeline on one SEVERE trade")
    parser.add_argument("--trade-id", type=int, default=None)
    parser.add_argument("--skip-veo", action="store_true", help="Use placeholder video instead of Veo")
    parser.add_argument("--skip-images", action="store_true", help="Skip citation image generation")
    args = parser.parse_args()

    section("VIDEO PIPELINE TEST")

    # ── Step 0: Fetch trade + audit report ──────────────────────────────
    log("Fetching SEVERE trade with audit report...")
    trade = fetch_severe_trade_with_report(args.trade_id)
    if not trade:
        print("  ERROR: No SEVERE trade with audit report found. Run contextualizer first.")
        sys.exit(1)

    tid = trade["trade_id"]
    log(f"Trade ID:    {tid}")
    log(f"Ticker:      {trade['ticker']}")
    log(f"Politician:  {trade['full_name']}")
    log(f"Date:        {trade['trade_date']}")
    log(f"Quadrant:    {trade['severity_quadrant']} (cohort={trade['cohort_index']}, baseline={trade['baseline_index']})")
    log(f"Headline:    {trade['headline'][:100]}")
    log(f"Narration:   {(trade['narration_script'] or '')[:100]}...")
    log(f"Video prompt: {(trade['video_prompt'] or '')[:100]}...")
    log(f"Citation prompts: {len(trade['citation_image_prompts'] or [])}")

    output_dir = PROJECT_ROOT / "media" / "test_video"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Citation images ─────────────────────────────────────────
    citation_paths: list[str] = []
    if not args.skip_images and trade["citation_image_prompts"]:
        section("STEP 1: Citation Image Generation")
        from backend.gemini.media_generation import generate_citation_image

        img_dir = output_dir / "citations"
        img_dir.mkdir(parents=True, exist_ok=True)

        for i, prompt in enumerate(trade["citation_image_prompts"][:3]):
            img_path = img_dir / f"trade_{tid}_citation_{i}.png"
            log(f"Generating citation image {i+1}...")
            t0 = time.time()
            result = generate_citation_image(
                prompt=str(prompt),
                output_path=str(img_path),
                aspect_ratio="16:9",
            )
            elapsed = time.time() - t0
            actual_path = result.get("path", str(img_path))
            size = result.get("file_size_bytes", 0)
            provider = result.get("provider", "unknown")
            err = result.get("error")

            if err:
                log(f"  [{i+1}] FALLBACK: {err}")
            else:
                log(f"  [{i+1}] OK: {provider}, {size:,} bytes, {elapsed:.1f}s -> {actual_path}")
                citation_paths.append(actual_path)
    else:
        log("Skipping citation images")

    # ── Step 2: TTS Audio ───────────────────────────────────────────────
    section("STEP 2: TTS Audio Generation")
    from backend.gemini.media_generation import synthesize_narration_audio

    audio_path = output_dir / f"trade_{tid}_audio.wav"
    narration = trade["narration_script"]
    log(f"Script: {narration}")
    log(f"Output: {audio_path}")

    t0 = time.time()
    audio_result = synthesize_narration_audio(narration, str(audio_path))
    elapsed = time.time() - t0

    audio_provider = audio_result.get("provider", "unknown")
    audio_duration = audio_result.get("duration_seconds")
    audio_size = audio_result.get("file_size_bytes", 0)
    audio_err = audio_result.get("error")

    if audio_err:
        log(f"TTS FALLBACK: {audio_err}")
    log(f"Provider: {audio_provider}")
    log(f"Duration: {audio_duration}s")
    log(f"Size:     {audio_size:,} bytes")
    log(f"Time:     {elapsed:.1f}s")

    # ── Step 3: Video Generation ────────────────────────────────────────
    section("STEP 3: Video Generation")
    from backend.gemini.media_generation import generate_video_from_prompt

    video_path = output_dir / f"trade_{tid}_video.mp4"
    video_prompt = trade["video_prompt"]
    target_duration = float(audio_duration or 15.0)

    if args.skip_veo:
        log("Skipping Veo (--skip-veo), generating placeholder video")
        os.environ["VEO_PROVIDER"] = "disabled"

    log(f"Prompt: {video_prompt[:150]}...")
    log(f"Target duration: {target_duration}s")
    log(f"Reference images: {len(citation_paths)}")
    log(f"Output: {video_path}")

    t0 = time.time()
    video_result = generate_video_from_prompt(
        prompt=video_prompt,
        output_path=str(video_path),
        duration_seconds=target_duration,
        aspect_ratio="16:9",
        reference_image_paths=citation_paths or None,
    )
    elapsed = time.time() - t0

    video_provider = video_result.get("provider", "unknown")
    video_duration = video_result.get("duration_seconds")
    video_size = video_result.get("file_size_bytes", 0)
    video_resolution = video_result.get("resolution")
    video_error = video_result.get("error")

    if video_error:
        log(f"*** VEO FAILED: {video_error}")
    log(f"Provider:   {video_provider}")
    log(f"Duration:   {video_duration}s")
    log(f"Resolution: {video_resolution}")
    log(f"Size:       {video_size:,} bytes")
    log(f"Time:       {elapsed:.1f}s")

    # ── Step 4: FFmpeg Mux ──────────────────────────────────────────────
    section("STEP 4: FFmpeg Assembly (Audio + Video)")
    from backend.gemini.ffmpeg_assembly import assemble_video_with_audio, overlay_citation_images

    muxed_path = output_dir / f"trade_{tid}_muxed.mp4"
    log(f"Audio: {audio_result.get('path')}")
    log(f"Video: {video_result.get('path')}")
    log(f"Output: {muxed_path}")

    t0 = time.time()
    try:
        mux_result = assemble_video_with_audio(
            video_path=str(video_result.get("path", video_path)),
            audio_path=str(audio_result.get("path", audio_path)),
            output_path=str(muxed_path),
        )
        elapsed = time.time() - t0
        log(f"Duration: {mux_result.get('duration_seconds')}s")
        log(f"Size:     {mux_result.get('file_size_bytes', 0):,} bytes")
        log(f"Time:     {elapsed:.1f}s")
    except Exception as exc:
        log(f"FFmpeg mux FAILED: {exc}")
        mux_result = None

    # ── Step 5: Citation Image Overlay ──────────────────────────────────
    final_path = output_dir / f"trade_{tid}_final.mp4"
    if mux_result and citation_paths:
        section("STEP 5: Citation Image Overlay")
        log(f"Input video: {mux_result.get('output_path')}")
        log(f"Citation images: {len(citation_paths)}")
        for cp in citation_paths:
            log(f"  - {cp}")
        log(f"Output: {final_path}")

        t0 = time.time()
        try:
            overlay_result = overlay_citation_images(
                video_path=str(mux_result.get("output_path", muxed_path)),
                citation_image_paths=citation_paths,
                output_path=str(final_path),
            )
            elapsed = time.time() - t0
            log(f"Duration: {overlay_result.get('duration_seconds')}s")
            log(f"Size:     {overlay_result.get('file_size_bytes', 0):,} bytes")
            log(f"Time:     {elapsed:.1f}s")
            mux_result = overlay_result  # use overlay as final
        except Exception as exc:
            log(f"Overlay FAILED: {exc}")
            log(f"Falling back to muxed video without overlay")
            # Copy muxed to final path as fallback
            import shutil
            shutil.copy2(str(muxed_path), str(final_path))
    elif mux_result:
        log("No citation images to overlay, using muxed video as final")
        import shutil
        shutil.copy2(str(muxed_path), str(final_path))

    # ── Summary ─────────────────────────────────────────────────────────
    section("SUMMARY")
    log(f"Trade:      {trade['ticker']} by {trade['full_name']} ({trade['severity_quadrant']})")
    log(f"Headline:   {trade['headline'][:100]}")
    log(f"Citations:  {len(citation_paths)} generated")
    log(f"TTS:        {audio_provider} ({audio_duration}s)")
    log(f"Video:      {video_provider} ({video_duration}s, {video_resolution})")
    if mux_result:
        log(f"Final:      {final_path}")
        log(f"            {mux_result.get('duration_seconds')}s, {mux_result.get('file_size_bytes', 0):,} bytes")
        log(f"")
        log(f">>> OPEN: {final_path}")
    else:
        log(f"Final:      FAILED")


if __name__ == "__main__":
    main()
