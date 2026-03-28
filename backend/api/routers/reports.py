from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from backend.db.connection import get_engine
from backend.gemini.gcs_storage import resolve_media_url

router = APIRouter(prefix="/api/v1", tags=["reports"])


@router.get("/daily-report/latest")
def get_latest_daily_report() -> dict:
    engine = get_engine()
    sql = text(
        """
        SELECT
          id,
          report_date,
          trade_ids_covered,
          narration_script,
          veo_prompt,
          video_url,
          audio_url,
          duration_seconds,
          generation_status,
          generated_at
        FROM daily_reports
        ORDER BY report_date DESC
        LIMIT 1
        """
    )

    with engine.connect() as conn:
        row = conn.execute(sql).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No daily report found")

    data = dict(row)
    if data.get("video_url"):
        data["video_url"] = resolve_media_url(data["video_url"])
    if data.get("audio_url"):
        data["audio_url"] = resolve_media_url(data["audio_url"])
    return data


@router.get("/daily-report/{report_date}")
def get_daily_report(report_date: str) -> dict:
    engine = get_engine()
    sql = text(
        """
        SELECT
          id,
          report_date,
          trade_ids_covered,
          narration_script,
          veo_prompt,
          video_url,
          audio_url,
          duration_seconds,
          generation_status,
          generated_at
        FROM daily_reports
        WHERE report_date = :report_date
        LIMIT 1
        """
    )

    with engine.connect() as conn:
        row = conn.execute(sql, {"report_date": report_date}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Daily report not found")

    data = dict(row)
    if data.get("video_url"):
        data["video_url"] = resolve_media_url(data["video_url"])
    if data.get("audio_url"):
        data["audio_url"] = resolve_media_url(data["audio_url"])
    return data
