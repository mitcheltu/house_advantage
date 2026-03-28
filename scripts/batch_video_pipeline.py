"""
Batch-generate videos for all 17 SEVERE trades.
Runs the same pipeline as test_video_pipeline.py for each trade sequentially.
Skips trades that already have a final video in media/test_video/.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text as sa_text
from backend.db.connection import get_engine

OUTPUT_DIR = PROJECT_ROOT / "media" / "test_video"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n", flush=True)


def get_all_severe_trades() -> list[dict]:
    engine = get_engine()
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
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    trades = []
    for row in rows:
        d = dict(row)
        cip = d.get("citation_image_prompts")
        if isinstance(cip, str):
            try:
                d["citation_image_prompts"] = json.loads(cip)
            except Exception:
                d["citation_image_prompts"] = []
        elif not isinstance(cip, list):
            d["citation_image_prompts"] = cip if cip else []
        trades.append(d)
    return trades


def process_trade(trade: dict) -> dict:
    """Run the full video pipeline for one trade. Returns a result dict."""
    tid = trade["trade_id"]
    result = {"trade_id": tid, "ticker": trade["ticker"], "politician": trade["full_name"]}
    t_start = time.time()

    try:
        # ── Step 1: Citation images ─────────────────────────────────
        citation_paths: list[str] = []
        if trade["citation_image_prompts"]:
            from backend.gemini.media_generation import generate_citation_image

            img_dir = OUTPUT_DIR / "citations"
            img_dir.mkdir(parents=True, exist_ok=True)

            for i, prompt in enumerate(trade["citation_image_prompts"][:3]):
                img_path = img_dir / f"trade_{tid}_citation_{i}.png"
                log(f"  Citation image {i+1}...")
                img_result = generate_citation_image(
                    prompt=str(prompt),
                    output_path=str(img_path),
                    aspect_ratio="16:9",
                )
                err = img_result.get("error")
                if err:
                    log(f"    FALLBACK: {err}")
                else:
                    citation_paths.append(img_result.get("path", str(img_path)))

        # ── Step 2: TTS Audio ───────────────────────────────────────
        from backend.gemini.media_generation import synthesize_narration_audio

        audio_path = OUTPUT_DIR / f"trade_{tid}_audio.wav"
        audio_result = synthesize_narration_audio(trade["narration_script"], str(audio_path))
        audio_duration = audio_result.get("duration_seconds")
        audio_err = audio_result.get("error")
        if audio_err:
            log(f"  TTS fallback: {audio_err}")
        log(f"  TTS: {audio_result.get('provider')} ({audio_duration}s)")

        # ── Step 3: Video Generation ────────────────────────────────
        from backend.gemini.media_generation import generate_video_from_prompt

        video_path = OUTPUT_DIR / f"trade_{tid}_video.mp4"
        target_duration = float(audio_duration or 15.0)

        video_result = generate_video_from_prompt(
            prompt=trade["video_prompt"],
            output_path=str(video_path),
            duration_seconds=target_duration,
            aspect_ratio="16:9",
            reference_image_paths=citation_paths or None,
        )
        video_err = video_result.get("error")
        if video_err:
            log(f"  Video fallback: {video_err}")
        log(f"  Video: {video_result.get('provider')} ({video_result.get('duration_seconds')}s)")

        # ── Step 4: FFmpeg Mux ──────────────────────────────────────
        from backend.gemini.ffmpeg_assembly import assemble_video_with_audio, overlay_citation_images

        muxed_path = OUTPUT_DIR / f"trade_{tid}_muxed.mp4"
        mux_result = assemble_video_with_audio(
            video_path=str(video_result.get("path", video_path)),
            audio_path=str(audio_result.get("path", audio_path)),
            output_path=str(muxed_path),
        )

        # ── Step 5: Citation Image Overlay ──────────────────────────
        final_path = OUTPUT_DIR / f"trade_{tid}_final.mp4"
        if mux_result and citation_paths:
            try:
                overlay_result = overlay_citation_images(
                    video_path=str(mux_result.get("output_path", muxed_path)),
                    citation_image_paths=citation_paths,
                    output_path=str(final_path),
                )
                mux_result = overlay_result
            except Exception as exc:
                log(f"  Overlay failed: {exc}, using muxed")
                shutil.copy2(str(muxed_path), str(final_path))
        elif mux_result:
            shutil.copy2(str(muxed_path), str(final_path))

        elapsed = time.time() - t_start
        result["status"] = "OK"
        result["final_path"] = str(final_path)
        result["duration_seconds"] = mux_result.get("duration_seconds") if mux_result else None
        result["file_size_bytes"] = mux_result.get("file_size_bytes", 0) if mux_result else 0
        result["elapsed"] = round(elapsed, 1)
        log(f"  DONE in {elapsed:.1f}s -> {final_path}")

    except Exception as exc:
        elapsed = time.time() - t_start
        result["status"] = "FAILED"
        result["error"] = str(exc)
        result["elapsed"] = round(elapsed, 1)
        log(f"  FAILED in {elapsed:.1f}s: {exc}")
        traceback.print_exc()

    return result


def main() -> None:
    section("BATCH VIDEO GENERATION — ALL SEVERE TRADES")

    trades = get_all_severe_trades()
    log(f"Found {len(trades)} SEVERE trades with media data")

    # Check which already have final videos
    to_process = []
    skipped = []
    for trade in trades:
        tid = trade["trade_id"]
        final = OUTPUT_DIR / f"trade_{tid}_final.mp4"
        if final.exists() and final.stat().st_size > 10000:
            skipped.append(tid)
        else:
            to_process.append(trade)

    if skipped:
        log(f"Skipping {len(skipped)} trades with existing videos: {skipped}")
    log(f"Processing {len(to_process)} trades\n")

    results = []
    for idx, trade in enumerate(to_process, 1):
        tid = trade["trade_id"]
        section(f"[{idx}/{len(to_process)}] Trade {tid}: {trade['ticker']} by {trade['full_name']}")
        result = process_trade(trade)
        results.append(result)

    # ── Final Summary ───────────────────────────────────────────────────
    section("BATCH SUMMARY")
    ok = [r for r in results if r["status"] == "OK"]
    failed = [r for r in results if r["status"] == "FAILED"]
    log(f"Processed: {len(results)}")
    log(f"Succeeded: {len(ok)}")
    log(f"Failed:    {len(failed)}")
    log(f"Skipped:   {len(skipped)} (already existed)")
    log("")
    for r in results:
        status = "OK" if r["status"] == "OK" else "FAIL"
        log(f"  [{status}] Trade {r['trade_id']}: {r['ticker']} by {r['politician']} ({r['elapsed']}s)")
    if failed:
        log("\nFailed trades:")
        for r in failed:
            log(f"  Trade {r['trade_id']}: {r.get('error', 'unknown')}")


if __name__ == "__main__":
    main()
