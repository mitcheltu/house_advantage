"""
End-to-end TTS pipeline test.

Follows the same flow as the production implementation:
  1. Build contextualizer input (using a real or synthetic trade)
  2. Call Gemini to generate the narration_script
  3. Feed narration_script into synthesize_narration_audio (Gemini TTS)
  4. Report results and audio file info

Usage:
    python -m scripts.test_tts_pipeline
    python -m scripts.test_tts_pipeline --trade-id 42
    python -m scripts.test_tts_pipeline --synthetic
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
_T0 = time.time()

def _log(level: str, msg: str) -> None:
    elapsed = time.time() - _T0
    print(f"[{elapsed:8.2f}s] [{level:>5s}] {msg}", flush=True)

def info(msg: str) -> None:
    _log("INFO", msg)

def warn(msg: str) -> None:
    _log("WARN", msg)

def error(msg: str) -> None:
    _log("ERROR", msg)

def debug(msg: str) -> None:
    _log("DEBUG", msg)

def section(title: str) -> None:
    print(f"\n{'='*70}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'='*70}", flush=True)


# ---------------------------------------------------------------------------
# Synthetic trade data (used when --synthetic or no DB available)
# ---------------------------------------------------------------------------
SYNTHETIC_TRADE: dict = {
    "trade_id": 0,
    "ticker": "LMT",
    "trade_type": "purchase",
    "trade_date": "2025-10-15",
    "disclosure_date": "2025-11-20",
    "disclosure_lag_days": 36,
    "amount_midpoint": 250_000,
    "industry_sector": "Defense",
    "bioguide_id": "S000148",
    "full_name": "Jack Reed",
    "cohort_index": 0.87,
    "baseline_index": 0.92,
    "severity_quadrant": "SEVERE",
    "feat_cohort_alpha": 0.14,
    "feat_pre_trade_alpha": 0.09,
    "feat_proximity_days": 12,
    "feat_bill_proximity": 0.78,
    "feat_has_proximity_data": 1,
    "feat_committee_relevance": 1.0,
    "feat_amount_zscore": 2.3,
    "feat_cluster_score": 0.65,
    "feat_disclosure_lag": 36,
    "nearby_bills": [
        {
            "bill_id": "hr3847-118",
            "title": "National Defense Authorization Act for Fiscal Year 2026",
            "policy_area": "Armed Forces and National Security",
            "latest_action_date": "2025-10-02",
            "url": "https://www.congress.gov/bill/118th-congress/house-bill/3847",
        },
        {
            "bill_id": "s2100-118",
            "title": "Defense Industrial Base Resilience Act",
            "policy_area": "Armed Forces and National Security",
            "latest_action_date": "2025-10-20",
            "url": "https://www.congress.gov/bill/118th-congress/senate-bill/2100",
        },
    ],
}


def _fetch_real_trade(trade_id: int) -> dict | None:
    """Attempt to load a real trade from the database."""
    try:
        from backend.gemini.contextualizer import _fetch_trade_context
        info(f"Fetching trade {trade_id} from database ...")
        trade = _fetch_trade_context(trade_id)
        if trade:
            info(f"  -> Found trade: {trade.get('ticker')} by {trade.get('full_name')} ({trade.get('severity_quadrant')})")
        else:
            warn(f"  -> Trade {trade_id} not found in database")
        return trade
    except Exception as exc:
        warn(f"  -> DB fetch failed: {exc}")
        return None


def _pick_severe_trade() -> dict | None:
    """Pick the first SEVERE trade from the database."""
    try:
        from backend.db.connection import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        sql = sa_text("""
            SELECT t.id
            FROM trades t
            JOIN anomaly_scores a ON a.trade_id = t.id
            WHERE a.severity_quadrant = 'SEVERE'
            ORDER BY t.trade_date DESC
            LIMIT 1
        """)
        with engine.connect() as conn:
            row = conn.execute(sql).mappings().first()
        if row:
            trade_id = int(row["id"])
            info(f"Auto-selected SEVERE trade_id={trade_id}")
            return _fetch_real_trade(trade_id)
        else:
            warn("No SEVERE trades found in database")
            return None
    except Exception as exc:
        warn(f"DB query failed: {exc}")
        return None


# ===========================================================================
# STAGE 1: Contextualizer — build prompt & call Gemini
# ===========================================================================
def stage_contextualizer(trade: dict) -> dict | None:
    section("STAGE 1: Contextualizer (Gemini structured analysis)")

    from backend.gemini.contextualizer import (
        build_initial_message,
        SYSTEM_PROMPT,
        _safe_json_loads,
    )

    info("Building initial message from trade context ...")
    initial_message = build_initial_message(trade)
    debug(f"Prompt length: {len(initial_message)} chars, ~{len(initial_message.split())} words")
    print(f"\n--- PROMPT (first 800 chars) ---\n{initial_message[:800]}\n---\n", flush=True)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        error("GEMINI_API_KEY is not set — cannot call contextualizer")
        return None

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    info(f"Calling Gemini model={model_name} ...")

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=model_name, system_instruction=SYSTEM_PROMPT)

        t0 = time.time()
        response = model.generate_content(initial_message)
        elapsed = time.time() - t0

        info(f"Gemini responded in {elapsed:.2f}s")

        usage = getattr(response, "usage_metadata", None)
        if usage:
            info(f"  prompt_tokens={getattr(usage, 'prompt_token_count', '?')}, "
                 f"output_tokens={getattr(usage, 'candidates_token_count', '?')}")

        raw_text = response.text
        debug(f"Raw response length: {len(raw_text)} chars")
        print(f"\n--- RAW GEMINI RESPONSE (first 1500 chars) ---\n{raw_text[:1500]}\n---\n", flush=True)

        parsed = _safe_json_loads(raw_text)
        info("JSON parse: OK")

        # Validate expected keys
        expected_keys = ["headline", "narrative", "narration_script", "video_prompt", "citation_image_prompts"]
        for k in expected_keys:
            val = parsed.get(k)
            status = "present" if val else "MISSING/null"
            info(f"  {k}: {status}")
            if val and isinstance(val, str):
                debug(f"    -> ({len(val)} chars) {val[:120]}{'...' if len(val) > 120 else ''}")
            elif val and isinstance(val, list):
                debug(f"    -> {len(val)} items")

        return parsed

    except Exception as exc:
        error(f"Contextualizer Gemini call failed: {exc}")
        traceback.print_exc()
        return None


# ===========================================================================
# STAGE 2: TTS — synthesize_narration_audio
# ===========================================================================
def stage_tts(narration_script: str) -> dict | None:
    section("STAGE 2: TTS (narration_script -> audio)")

    from backend.gemini.media_generation import synthesize_narration_audio

    info(f"Narration script: {len(narration_script)} chars, ~{len(narration_script.split())} words")
    print(f"\n--- NARRATION SCRIPT ---\n{narration_script}\n---\n", flush=True)

    output_dir = PROJECT_ROOT / "media" / "test_tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "test_narration.wav")

    info(f"Output path: {output_path}")

    provider = os.getenv("TTS_PROVIDER", "auto")
    tts_model = os.getenv("TTS_GEMINI_MODEL", "gemini-2.5-pro-preview-tts")
    tts_voice = os.getenv("TTS_GEMINI_VOICE", "Kore")
    info(f"TTS_PROVIDER={provider}, model={tts_model}, voice={tts_voice}")

    t0 = time.time()
    try:
        result = synthesize_narration_audio(narration_script, output_path)
        elapsed = time.time() - t0

        info(f"TTS completed in {elapsed:.2f}s")
        info(f"  provider: {result.get('provider')}")
        info(f"  duration_seconds: {result.get('duration_seconds')}")
        info(f"  file_size_bytes: {result.get('file_size_bytes')}")
        info(f"  path: {result.get('path')}")

        if result.get("error"):
            warn(f"  error (fallback used): {result.get('error')}")

        # Check the actual file
        p = Path(result.get("path", ""))
        if p.exists():
            info(f"  file exists: YES ({p.stat().st_size:,} bytes)")
            # Quick WAV header check
            if p.suffix == ".wav" and p.stat().st_size > 44:
                info("  WAV header: valid (file > 44 bytes)")
            elif p.stat().st_size <= 44:
                warn("  WAV file suspiciously small (<=44 bytes, header only?)")
        else:
            error("  file exists: NO")

        return result

    except Exception as exc:
        elapsed = time.time() - t0
        error(f"TTS failed after {elapsed:.2f}s: {exc}")
        traceback.print_exc()
        return None


# ===========================================================================
# STAGE 2.5: Citation image generation (Nano Banana)
# ===========================================================================
def stage_citation_images(citation_prompts: list[str]) -> list[dict]:
    section("STAGE 2.5: Citation Image Generation (Nano Banana)")

    from backend.gemini.media_generation import generate_citation_image

    info(f"Number of citation image prompts: {len(citation_prompts)}")

    output_dir = PROJECT_ROOT / "media" / "test_tts" / "citations"
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, prompt in enumerate(citation_prompts):
        info(f"\n--- Citation Image {i+1}/{len(citation_prompts)} ---")
        debug(f"Prompt ({len(prompt)} chars): {prompt[:300]}{'...' if len(prompt) > 300 else ''}")

        output_path = str(output_dir / f"citation_{i+1}.png")
        info(f"Output: {output_path}")

        t0 = time.time()
        try:
            result = generate_citation_image(
                prompt=prompt,
                output_path=output_path,
                aspect_ratio="16:9",
            )
            elapsed = time.time() - t0

            info(f"  completed in {elapsed:.2f}s")
            info(f"  provider: {result.get('provider')}")
            info(f"  file_size_bytes: {result.get('file_size_bytes')}")
            info(f"  path: {result.get('path')}")

            if result.get("error"):
                warn(f"  error: {result.get('error')}")

            p = Path(result.get("path", ""))
            if p.exists():
                info(f"  file exists: YES ({p.stat().st_size:,} bytes)")
                if p.stat().st_size < 200:
                    warn("  file suspiciously small — likely placeholder")
                else:
                    info("  image looks real (>200 bytes)")
            else:
                error("  file exists: NO")

            results.append(result)

        except Exception as exc:
            elapsed = time.time() - t0
            error(f"  failed after {elapsed:.2f}s: {exc}")
            traceback.print_exc()
            results.append({"error": str(exc)})

    return results


# ===========================================================================
# STAGE 3: Video generation (Veo or placeholder)
# ===========================================================================
def stage_video(video_prompt: str, audio_duration: float | None) -> dict | None:
    section("STAGE 3: Video generation (Veo / placeholder)")

    from backend.gemini.media_generation import generate_video_from_prompt

    info(f"Video prompt: {len(video_prompt)} chars")
    print(f"\n--- VIDEO PROMPT ---\n{video_prompt}\n---\n", flush=True)

    output_dir = PROJECT_ROOT / "media" / "test_tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "test_video_raw.mp4")

    duration = audio_duration or 15.0
    info(f"Target duration: {duration}s, aspect_ratio=9:16")
    info(f"VEO_PROVIDER={os.getenv('VEO_PROVIDER', 'auto')}")
    info(f"Output path: {output_path}")

    t0 = time.time()
    try:
        result = generate_video_from_prompt(
            prompt=video_prompt,
            output_path=output_path,
            duration_seconds=duration,
            aspect_ratio="9:16",
        )
        elapsed = time.time() - t0

        info(f"Video generation completed in {elapsed:.2f}s")
        info(f"  provider: {result.get('provider')}")
        info(f"  duration_seconds: {result.get('duration_seconds')}")
        info(f"  file_size_bytes: {result.get('file_size_bytes')}")
        info(f"  resolution: {result.get('resolution')}")
        info(f"  path: {result.get('path')}")

        if result.get("error"):
            warn(f"  error: {result.get('error')}")

        p = Path(result.get("path", ""))
        if p.exists():
            info(f"  file exists: YES ({p.stat().st_size:,} bytes)")
        else:
            error("  file exists: NO")

        return result

    except Exception as exc:
        elapsed = time.time() - t0
        error(f"Video generation failed after {elapsed:.2f}s: {exc}")
        traceback.print_exc()
        return None


# ===========================================================================
# STAGE 4: FFmpeg mux (audio + video -> final mp4)
# ===========================================================================
def stage_mux(audio_path: str, video_path: str) -> dict | None:
    section("STAGE 4: FFmpeg mux (audio + video -> final .mp4)")

    from backend.gemini.ffmpeg_assembly import assemble_video_with_audio

    output_dir = PROJECT_ROOT / "media" / "test_tts"
    output_path = str(output_dir / "test_final.mp4")

    info(f"Audio: {audio_path}")
    info(f"Video: {video_path}")
    info(f"Output: {output_path}")

    t0 = time.time()
    try:
        result = assemble_video_with_audio(
            video_path=video_path,
            audio_path=audio_path,
            output_path=output_path,
        )
        elapsed = time.time() - t0

        info(f"Mux completed in {elapsed:.2f}s")
        info(f"  output_path: {result.get('output_path')}")
        info(f"  duration_seconds: {result.get('duration_seconds')}")
        info(f"  file_size_bytes: {result.get('file_size_bytes')}")

        p = Path(result.get("output_path", ""))
        if p.exists():
            info(f"  file exists: YES ({p.stat().st_size:,} bytes)")
        else:
            error("  file exists: NO")

        return result

    except Exception as exc:
        elapsed = time.time() - t0
        error(f"FFmpeg mux failed after {elapsed:.2f}s: {exc}")
        traceback.print_exc()
        return None


# ===========================================================================
# Summary
# ===========================================================================
def print_summary(trade: dict, ctx_result: dict | None, tts_result: dict | None,
                  video_result: dict | None, mux_result: dict | None,
                  citation_results: list | None = None) -> None:
    section("SUMMARY")

    print(f"  Trade:        {trade.get('ticker')} by {trade.get('full_name')}", flush=True)
    print(f"  Quadrant:     {trade.get('severity_quadrant')}", flush=True)
    print(f"  Trade Date:   {trade.get('trade_date')}", flush=True)
    print()

    if ctx_result:
        print(f"  Contextualizer: OK", flush=True)
        print(f"    headline:     {ctx_result.get('headline', 'N/A')[:100]}", flush=True)
        print(f"    has narration: {'YES' if ctx_result.get('narration_script') else 'NO'}", flush=True)
        print(f"    has video_prompt: {'YES' if ctx_result.get('video_prompt') else 'NO'}", flush=True)
        n_images = len(ctx_result.get("citation_image_prompts") or [])
        print(f"    citation_image_prompts: {n_images}", flush=True)
    else:
        print(f"  Contextualizer: FAILED", flush=True)

    print()
    if tts_result:
        provider = tts_result.get("provider", "unknown")
        err = tts_result.get("error")
        if err:
            print(f"  TTS:          FALLBACK ({provider})", flush=True)
            print(f"    error:      {err[:200]}", flush=True)
        else:
            print(f"  TTS:          OK ({provider})", flush=True)
        print(f"    duration:   {tts_result.get('duration_seconds')}s", flush=True)
        print(f"    file size:  {tts_result.get('file_size_bytes'):,} bytes" if tts_result.get('file_size_bytes') else "    file size:  N/A", flush=True)
        print(f"    path:       {tts_result.get('path')}", flush=True)
    else:
        print(f"  TTS:          FAILED / SKIPPED", flush=True)

    print()
    if citation_results:
        real = sum(1 for r in citation_results if r.get('provider') and 'placeholder' not in r.get('provider', ''))
        placeholder = sum(1 for r in citation_results if 'placeholder' in r.get('provider', ''))
        errored = sum(1 for r in citation_results if r.get('error') and not r.get('path'))
        print(f"  Citations:    {len(citation_results)} total ({real} real, {placeholder} placeholder, {errored} errored)", flush=True)
        for i, cr in enumerate(citation_results):
            print(f"    [{i+1}] {cr.get('provider', 'N/A')} — {cr.get('file_size_bytes', 'N/A')} bytes — {cr.get('path', 'N/A')}", flush=True)
            if cr.get('error'):
                print(f"         error: {str(cr.get('error'))[:200]}", flush=True)
    else:
        print(f"  Citations:    NONE", flush=True)

    print()
    if video_result:
        print(f"  Video:        OK ({video_result.get('provider')})", flush=True)
        print(f"    duration:   {video_result.get('duration_seconds')}s", flush=True)
        print(f"    resolution: {video_result.get('resolution')}", flush=True)
        sz = video_result.get('file_size_bytes')
        print(f"    file size:  {sz:,} bytes" if sz else "    file size:  N/A", flush=True)
    else:
        print(f"  Video:        FAILED / SKIPPED", flush=True)

    print()
    if mux_result:
        print(f"  Final Video:  OK", flush=True)
        print(f"    duration:   {mux_result.get('duration_seconds')}s", flush=True)
        sz = mux_result.get('file_size_bytes')
        print(f"    file size:  {sz:,} bytes" if sz else "    file size:  N/A", flush=True)
        print(f"    path:       {mux_result.get('output_path')}", flush=True)
        print(f"\n  >>> OPEN THIS FILE TO WATCH: {mux_result.get('output_path')}", flush=True)
    else:
        print(f"  Final Video:  FAILED / SKIPPED", flush=True)

    print(f"\n{'='*70}\n", flush=True)


# ===========================================================================
# Main
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(description="Test TTS pipeline end-to-end")
    parser.add_argument("--trade-id", type=int, default=None, help="Specific trade ID to contextualize")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic trade data (skip DB)")
    parser.add_argument("--skip-contextualizer", action="store_true",
                        help="Skip Gemini contextualizer, use a canned narration script for TTS only")
    args = parser.parse_args()

    section("TTS PIPELINE TEST")
    info(f"Project root: {PROJECT_ROOT}")
    info(f"GEMINI_API_KEY set: {'YES' if os.getenv('GEMINI_API_KEY') else 'NO'}")
    info(f"TTS_PROVIDER: {os.getenv('TTS_PROVIDER', 'auto')}")
    info(f"TTS_GEMINI_MODEL: {os.getenv('TTS_GEMINI_MODEL', 'gemini-2.5-pro-preview-tts')}")
    info(f"TTS_GEMINI_VOICE: {os.getenv('TTS_GEMINI_VOICE', 'Kore')}")

    # --- Resolve trade data ---
    trade = None
    if args.synthetic:
        info("Using synthetic trade data (--synthetic)")
        trade = SYNTHETIC_TRADE
    elif args.trade_id:
        trade = _fetch_real_trade(args.trade_id)
        if not trade:
            warn(f"Trade {args.trade_id} not found, falling back to synthetic data")
            trade = SYNTHETIC_TRADE
    else:
        info("No trade ID specified, auto-selecting a SEVERE trade from DB ...")
        trade = _pick_severe_trade()
        if not trade:
            warn("Could not auto-select; using synthetic trade data")
            trade = SYNTHETIC_TRADE

    info(f"Trade: {trade.get('ticker')} | {trade.get('full_name')} | {trade.get('severity_quadrant')}")

    # --- Stage 1: Contextualizer ---
    ctx_result = None
    narration_script = None

    if args.skip_contextualizer:
        info("Skipping contextualizer (--skip-contextualizer)")
        narration_script = (
            "House Advantage has flagged a significant Lockheed Martin trade by Senator Jack Reed, "
            "categorized in the SEVERE quadrant by our dual-model anomaly scoring system. "
            "The trade occurred just twelve days before the National Defense Authorization Act "
            "advanced through committee, raising questions about information asymmetry. "
            "A committee relevance score of 1.0 and cohort index of 0.87 place this trade "
            "well above statistical norms. This is an automated anomaly alert, not a legal determination."
        )
    else:
        ctx_result = stage_contextualizer(trade)
        if ctx_result:
            narration_script = ctx_result.get("narration_script")
            if not narration_script:
                warn("Contextualizer returned null narration_script — using fallback text")
                narration_script = (
                    f"House Advantage has flagged a {trade.get('ticker')} trade by {trade.get('full_name')} "
                    f"in the {trade.get('severity_quadrant')} quadrant. "
                    f"The dual-model anomaly score is driven by a cohort index of {trade.get('cohort_index')} "
                    f"and baseline index of {trade.get('baseline_index')}. "
                    "This is an automated statistical finding, not a legal conclusion."
                )

    if not narration_script:
        error("No narration script available — cannot proceed to TTS. Aborting.")
        sys.exit(1)

    # --- Stage 2: TTS ---
    tts_result = stage_tts(narration_script)

    # --- Stage 2.5: Citation images ---
    citation_results = []
    citation_prompts = (ctx_result or {}).get("citation_image_prompts") or []
    if citation_prompts:
        citation_results = stage_citation_images(citation_prompts)
    else:
        info("No citation_image_prompts from contextualizer — skipping image generation")

    # --- Stage 3: Video generation ---
    video_prompt = None
    if ctx_result and ctx_result.get("video_prompt"):
        video_prompt = ctx_result["video_prompt"]
    if not video_prompt:
        video_prompt = (
            "Dark newsroom desk with scattered legal documents and a glowing monitor "
            "showing stock charts. Subtle motion graphics of data flowing, investigative "
            "journalism tone. LMT ticker visible. Moody blue-green lighting, 9:16 vertical format."
        )
        info("Using fallback video prompt (contextualizer didn't provide one)")

    audio_duration = None
    if tts_result:
        audio_duration = tts_result.get("duration_seconds")
        # If ffprobe couldn't determine duration, estimate from script length
        if not audio_duration:
            audio_duration = max(8, min(120, round(len(narration_script.split()) / 2.4)))
            info(f"Estimated audio duration from word count: {audio_duration}s")

    # Collect citation image paths for ffmpeg overlay
    citation_paths = [r.get("path") for r in citation_results if r.get("path") and Path(r["path"]).exists()] if citation_results else []

    video_result = stage_video(video_prompt, audio_duration)

    # --- Stage 4: FFmpeg mux ---
    mux_result = None
    if tts_result and video_result:
        audio_path = tts_result.get("path")
        video_path = video_result.get("path")
        if audio_path and video_path and Path(audio_path).exists() and Path(video_path).exists():
            mux_result = stage_mux(audio_path, video_path)
        else:
            warn("Cannot mux: audio or video file missing")
    else:
        warn("Skipping mux: TTS or video stage failed")

    # --- Stage 5: Overlay citation images onto final video ---
    if mux_result and citation_paths:
        mux_path = mux_result.get("output_path")
        if mux_path and Path(mux_path).exists():
            section("STAGE 5: Citation Image Overlay (FFmpeg)")
            from backend.gemini.ffmpeg_assembly import overlay_citation_images

            overlay_output = str(PROJECT_ROOT / "media" / "test_tts" / "test_final_with_citations.mp4")
            info(f"Overlaying {len(citation_paths)} unaltered citation images onto final video")
            info(f"Input:  {mux_path}")
            info(f"Output: {overlay_output}")
            for i, cp in enumerate(citation_paths):
                info(f"  Citation [{i+1}]: {cp}")

            t0 = time.time()
            try:
                overlay_result = overlay_citation_images(
                    video_path=mux_path,
                    citation_image_paths=citation_paths,
                    output_path=overlay_output,
                )
                elapsed = time.time() - t0
                info(f"Overlay completed in {elapsed:.2f}s")
                info(f"  output_path: {overlay_result.get('output_path')}")
                info(f"  duration:    {overlay_result.get('duration_seconds')}s")
                sz = overlay_result.get('file_size_bytes')
                info(f"  file_size:   {sz:,} bytes" if sz else "  file_size:   N/A")

                # Update mux_result to point to the final video with citations
                mux_result = {**mux_result, **overlay_result}
            except Exception as exc:
                elapsed = time.time() - t0
                error(f"Citation overlay failed after {elapsed:.2f}s: {exc}")
                traceback.print_exc()
                warn("Keeping mux result without citation overlays")

    # --- Summary ---
    print_summary(trade, ctx_result, tts_result, video_result, mux_result, citation_results)

    # Exit code
    if mux_result and Path(mux_result.get("output_path", "")).exists():
        info("Pipeline test PASSED — final video ready")
        sys.exit(0)
    elif tts_result and not tts_result.get("error"):
        warn("Pipeline partially passed (audio OK, video/mux may have issues)")
        sys.exit(0)
    else:
        error("Pipeline test FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
