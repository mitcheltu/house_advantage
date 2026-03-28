"""
End-to-end evidence pipeline runner.

Pipeline sequence:
1) Contextualize flagged trades (SEVERE + SYSTEMIC) -> audit_reports
2) Generate daily script -> daily_reports
3) Assemble available local media pairs and register media_assets

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
from backend.gemini.ffmpeg_assembly import assemble_and_register_trade_video


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


def _assemble_available_local_media_for_severe(
    report_date: date,
    staging_dir: Path,
    output_dir: Path,
    limit: int = 100,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    trade_ids = _fetch_severe_trade_ids_for_date(report_date=report_date, limit=limit)
    processed = 0
    skipped = 0
    failed: list[dict[str, Any]] = []

    for trade_id in trade_ids:
        input_video = staging_dir / f"trade_{trade_id}_video.mp4"
        input_audio = staging_dir / f"trade_{trade_id}_audio.wav"
        if not input_video.exists() or not input_audio.exists():
            skipped += 1
            continue

        output_path = output_dir / f"trade_{trade_id}_final.mp4"
        audit_report_id = _fetch_audit_report_id(trade_id)

        try:
            assemble_and_register_trade_video(
                trade_id=trade_id,
                video_path=str(input_video),
                audio_path=str(input_audio),
                output_path=str(output_path),
                audit_report_id=audit_report_id,
                model_used="ffmpeg-mux-local",
            )
            processed += 1
        except Exception as exc:  # pragma: no cover
            failed.append({"trade_id": trade_id, "error": str(exc)})

    return {
        "date": report_date.isoformat(),
        "severe_candidates": len(trade_ids),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
    }


def run_daily_evidence_pipeline(
    report_date: str | None = None,
    contextualize_limit: int = 100,
    severe_media_limit: int = 100,
) -> dict[str, Any]:
    target_date = _to_date(report_date)

    stage1 = contextualize_flagged_trades(limit=contextualize_limit, since_date=target_date)
    stage2 = generate_daily_report(report_date=target_date)

    staging_dir = Path(os.getenv("MEDIA_STAGING_DIR", "backend/data/media_staging"))
    output_dir = Path(os.getenv("MEDIA_OUTPUT_DIR", "backend/data/media"))

    stage3 = _assemble_available_local_media_for_severe(
        report_date=target_date,
        staging_dir=staging_dir,
        output_dir=output_dir,
        limit=severe_media_limit,
    )

    return {
        "status": "ok",
        "report_date": target_date.isoformat(),
        "stages": {
            "contextualize_flagged": stage1,
            "daily_scriptwriter": stage2,
            "ffmpeg_media_assembly": stage3,
        },
    }
