"""
End-to-end evidence pipeline runner.

Pipeline sequence:
1) Contextualize flagged trades (SEVERE + SYSTEMIC) -> audit_reports
2) Generate daily script -> daily_reports
3) Auto-generate per-trade media for SEVERE trades (TTS + video + mux)
4) Auto-generate daily report media (TTS + video + mux)

This is designed to be callable from CLI or API job endpoints.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.db.connection import get_engine
from backend.gemini.contextualizer import contextualize_flagged_trades
from backend.gemini.daily_scriptwriter import generate_daily_report
from backend.gemini.ffmpeg_assembly import (
    assemble_video_with_audio,
    assemble_and_register_trade_video,
    update_media_asset_storage_url,
    overlay_citation_images,
    write_media_asset,
)
from backend.gemini.gcs_storage import gcs_enabled, upload_file_to_gcs
from backend.gemini.media_generation import (
    generate_citation_image,
    generate_video_from_prompt,
    synthesize_narration_audio,
)


def _to_date(value: str | None) -> date:
    if not value:
        return datetime.utcnow().date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fetch_severe_trade_ids_for_date(report_date: date, limit: int = 100) -> list[int]:
    engine = get_engine()
    sql = text(
        """
        SELECT t.id AS trade_id
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        WHERE t.trade_date = :report_date
          AND a.severity_quadrant = 'SEVERE'
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
        LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"report_date": report_date, "limit": limit}).mappings().all()
    return [int(r["trade_id"]) for r in rows]


def _fetch_audit_report_id(trade_id: int) -> int | None:
    engine = get_engine()
    sql = text("SELECT id FROM audit_reports WHERE trade_id = :trade_id LIMIT 1")
    with engine.connect() as conn:
        row = conn.execute(sql, {"trade_id": trade_id}).mappings().first()
    return int(row["id"]) if row else None


def _fetch_severe_trade_media_jobs(report_date: date, limit: int = 100) -> list[dict[str, Any]]:
    engine = get_engine()
    sql = text(
        """
        SELECT
          t.id AS trade_id,
          t.ticker,
          t.trade_date,
          a.severity_quadrant,
          ar.id AS audit_report_id,
          ar.video_prompt,
          ar.narration_script,
          ar.headline,
          ar.citation_image_prompts
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        LEFT JOIN audit_reports ar ON ar.trade_id = t.id
        WHERE t.trade_date = :report_date
          AND a.severity_quadrant = 'SEVERE'
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
        LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"report_date": report_date, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _has_ready_video_asset(trade_id: int) -> bool:
    engine = get_engine()
    sql = text(
        """
        SELECT id
        FROM media_assets
        WHERE trade_id = :trade_id
          AND asset_type = 'video'
          AND generation_status = 'ready'
        ORDER BY generated_at DESC
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"trade_id": trade_id}).mappings().first()
    return row is not None


def _fetch_citation_image_paths(trade_id: int) -> list[str]:
    """Fetch file paths for ready citation_image assets for a trade."""
    engine = get_engine()
    sql = text(
        """
        SELECT storage_url
        FROM media_assets
        WHERE trade_id = :trade_id
          AND asset_type = 'citation_image'
          AND generation_status = 'ready'
        ORDER BY generated_at ASC
        LIMIT 3
        """
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"trade_id": trade_id}).mappings().all()
        return [str(r["storage_url"]) for r in rows]
    except Exception:
        return []


def _generate_citation_images_for_severe(
    report_date: date,
    staging_dir: Path,
    limit: int = 100,
) -> dict[str, Any]:
    """Stage 1.5: Generate citation card images for SEVERE trades with citation_image_prompts."""
    import json as _json

    staging_dir.mkdir(parents=True, exist_ok=True)
    citation_dir = staging_dir / "citation_images"
    citation_dir.mkdir(parents=True, exist_ok=True)

    jobs = _fetch_severe_trade_media_jobs(report_date=report_date, limit=limit)
    generated = 0
    skipped = 0
    failed: list[dict[str, Any]] = []

    for job in jobs:
        trade_id = int(job["trade_id"])
        raw_prompts = job.get("citation_image_prompts")

        if not raw_prompts:
            skipped += 1
            continue

        if isinstance(raw_prompts, str):
            try:
                prompts = _json.loads(raw_prompts)
            except (ValueError, TypeError):
                prompts = []
        else:
            prompts = raw_prompts if isinstance(raw_prompts, list) else []

        if not prompts:
            skipped += 1
            continue

        audit_report_id = int(job["audit_report_id"]) if job.get("audit_report_id") else _fetch_audit_report_id(trade_id)

        for idx, prompt in enumerate(prompts[:3]):
            img_path = citation_dir / f"trade_{trade_id}_citation_{idx}.png"
            try:
                meta = generate_citation_image(
                    prompt=str(prompt),
                    output_path=str(img_path),
                )
                try:
                    write_media_asset(
                        trade_id=trade_id,
                        audit_report_id=audit_report_id,
                        asset_type="citation_image",
                        storage_url=str(img_path),
                        file_size_bytes=meta.get("file_size_bytes"),
                        generation_status="ready",
                        model_used=str(meta.get("provider") or "image-gen"),
                    )
                except Exception:
                    pass  # media_assets table may not exist yet
                generated += 1
            except Exception as exc:
                failed.append({"trade_id": trade_id, "idx": idx, "error": str(exc)})

    return {
        "date": report_date.isoformat(),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
    }


def _generate_trade_media_for_severe(
    report_date: date,
    staging_dir: Path,
    output_dir: Path,
    limit: int = 100,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    jobs = _fetch_severe_trade_media_jobs(report_date=report_date, limit=limit)
    processed = 0
    skipped = 0
    failed: list[dict[str, Any]] = []

    for job in jobs:
        trade_id = int(job["trade_id"])
        if not force_regenerate and _has_ready_video_asset(trade_id):
            skipped += 1
            continue

        headline = job.get("headline") or f"Trade {trade_id}"
        narration_script = (
            job.get("narration_script")
            or f"House Advantage flagged {job.get('ticker') or 'this'} trade for investigative review."
        )
        video_prompt = (
            job.get("video_prompt")
            or f"Investigative newsroom, civic accountability visuals, focus on {job.get('ticker') or 'stock'} trade, 9:16"
        )

        audio_path = staging_dir / f"trade_{trade_id}_audio.wav"
        video_path = staging_dir / f"trade_{trade_id}_video.mp4"
        output_path = output_dir / f"trade_{trade_id}_final.mp4"
        audit_report_id = int(job["audit_report_id"]) if job.get("audit_report_id") else _fetch_audit_report_id(trade_id)

        try:
            audio_meta = synthesize_narration_audio(
                script_text=narration_script,
                output_path=str(audio_path),
            )

            video_meta = generate_video_from_prompt(
                prompt=video_prompt,
                output_path=str(video_path),
                duration_seconds=float(audio_meta.get("duration_seconds") or 30.0),
                reference_image_paths=_fetch_citation_image_paths(trade_id) or None,
            )

            audio_storage_url = str(audio_path)
            if gcs_enabled():
                audio_blob = f"media/trades/{trade_id}/audio_{report_date.isoformat()}.wav"
                audio_storage_url = upload_file_to_gcs(str(audio_path), audio_blob, content_type="audio/wav")

            write_media_asset(
                trade_id=trade_id,
                audit_report_id=audit_report_id,
                asset_type="audio",
                storage_url=audio_storage_url,
                file_size_bytes=audio_meta.get("file_size_bytes"),
                duration_seconds=audio_meta.get("duration_seconds"),
                generation_status="ready",
                model_used=str(audio_meta.get("provider") or "tts"),
            )

            assembly = assemble_and_register_trade_video(
                trade_id=trade_id,
                video_path=str(video_path),
                audio_path=str(audio_path),
                output_path=str(output_path),
                audit_report_id=audit_report_id,
                model_used=f"{video_meta.get('provider', 'video')}+ffmpeg-mux",
            )

            if gcs_enabled():
                video_blob = f"media/trades/{trade_id}/video_{report_date.isoformat()}.mp4"
                gs_video_url = upload_file_to_gcs(str(output_path), video_blob, content_type="video/mp4")
                update_media_asset_storage_url(assembly["asset_id"], gs_video_url)
            processed += 1
        except Exception as exc:  # pragma: no cover
            try:
                write_media_asset(
                    trade_id=trade_id,
                    audit_report_id=audit_report_id,
                    asset_type="video",
                    storage_url=str(output_path),
                    generation_status="failed",
                    error_message=str(exc),
                    model_used="pipeline-auto",
                )
            except Exception:
                pass
            failed.append({"trade_id": trade_id, "error": str(exc)})

    return {
        "date": report_date.isoformat(),
        "severe_candidates": len(jobs),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
    }


def _fetch_daily_report_row(report_date: date) -> dict[str, Any] | None:
    engine = get_engine()
    sql = text(
        """
        SELECT
          id,
          report_date,
          narration_script,
          veo_prompt
        FROM daily_reports
        WHERE report_date = :report_date
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"report_date": report_date}).mappings().first()
    return dict(row) if row else None


def _update_daily_report_media(
    report_date: date,
    *,
    video_url: str | None = None,
    audio_url: str | None = None,
    duration_seconds: float | None = None,
    generation_status: str = "ready",
) -> None:
    engine = get_engine()
    sql = text(
        """
        UPDATE daily_reports
        SET
          video_url = :video_url,
          audio_url = :audio_url,
          duration_seconds = :duration_seconds,
          generation_status = :generation_status,
          generated_at = CURRENT_TIMESTAMP
        WHERE report_date = :report_date
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "report_date": report_date,
                "video_url": video_url,
                "audio_url": audio_url,
                "duration_seconds": duration_seconds,
                "generation_status": generation_status,
            },
        )


def _generate_daily_report_media(
    report_date: date,
    staging_dir: Path,
    output_dir: Path,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    daily = _fetch_daily_report_row(report_date)
    if not daily:
        return {"status": "skipped", "reason": "daily report not found"}

    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    final_path = output_dir / f"daily_{report_date.isoformat()}_final.mp4"
    if final_path.exists() and not force_regenerate:
        _update_daily_report_media(
            report_date,
            video_url=str(final_path),
            audio_url=str(staging_dir / f"daily_{report_date.isoformat()}_audio.wav"),
            duration_seconds=None,
            generation_status="ready",
        )
        return {"status": "skipped", "reason": "already exists", "video_url": str(final_path)}

    narration_script = daily.get("narration_script") or (
        f"This is House Advantage for {report_date.isoformat()}."
    )
    veo_prompt = daily.get("veo_prompt") or (
        "Investigative newsroom, data overlays, neutral civic reporting tone, 9:16"
    )

    audio_path = staging_dir / f"daily_{report_date.isoformat()}_audio.wav"
    video_path = staging_dir / f"daily_{report_date.isoformat()}_video.mp4"

    try:
        audio_meta = synthesize_narration_audio(
            script_text=narration_script,
            output_path=str(audio_path),
        )

        video_meta = generate_video_from_prompt(
            prompt=veo_prompt,
            output_path=str(video_path),
            duration_seconds=float(audio_meta.get("duration_seconds") or 30.0),
        )

        assembly = assemble_video_with_audio(
            video_path=str(video_path),
            audio_path=str(audio_path),
            output_path=str(final_path),
            overwrite=True,
        )

        video_url = str(final_path)
        audio_url = str(audio_path)
        if gcs_enabled():
            video_blob = f"media/daily/{report_date.isoformat()}/daily_final.mp4"
            audio_blob = f"media/daily/{report_date.isoformat()}/daily_audio.wav"
            video_url = upload_file_to_gcs(str(final_path), video_blob, content_type="video/mp4")
            audio_url = upload_file_to_gcs(str(audio_path), audio_blob, content_type="audio/wav")

        _update_daily_report_media(
            report_date,
            video_url=video_url,
            audio_url=audio_url,
            duration_seconds=assembly.get("duration_seconds"),
            generation_status="ready",
        )

        return {
            "status": "ok",
            "audio_provider": audio_meta.get("provider"),
            "video_provider": video_meta.get("provider"),
            "video_url": video_url,
            "audio_url": audio_url,
            "duration_seconds": assembly.get("duration_seconds"),
        }
    except Exception as exc:
        _update_daily_report_media(
            report_date,
            video_url=None,
            audio_url=None,
            duration_seconds=None,
            generation_status="failed",
        )
        return {"status": "failed", "error": str(exc)}


def run_daily_evidence_pipeline(
    report_date: str | None = None,
    contextualize_limit: int = 100,
    severe_media_limit: int = 100,
) -> dict[str, Any]:
    target_date = _to_date(report_date)

    stage1 = contextualize_flagged_trades(limit=contextualize_limit, since_date=target_date)

    staging_dir = Path(os.getenv("MEDIA_STAGING_DIR", "backend/data/media_staging"))
    output_dir = Path(os.getenv("MEDIA_OUTPUT_DIR", "backend/data/media"))
    force_media_regen = os.getenv("MEDIA_FORCE_REGENERATE", "false").strip().lower() in {"1", "true", "yes"}

    stage1_5 = _generate_citation_images_for_severe(
        report_date=target_date,
        staging_dir=staging_dir,
        limit=severe_media_limit,
    )

    stage2 = generate_daily_report(report_date=target_date)

    stage3 = _generate_trade_media_for_severe(
        report_date=target_date,
        staging_dir=staging_dir,
        output_dir=output_dir,
        limit=severe_media_limit,
        force_regenerate=force_media_regen,
    )

    stage4 = _generate_daily_report_media(
        report_date=target_date,
        staging_dir=staging_dir,
        output_dir=output_dir,
        force_regenerate=force_media_regen,
    )

    return {
        "status": "ok",
        "report_date": target_date.isoformat(),
        "stages": {
            "contextualize_flagged": stage1,
            "citation_image_generation": stage1_5,
            "daily_scriptwriter": stage2,
            "trade_media_generation": stage3,
            "daily_media_generation": stage4,
        },
    }
